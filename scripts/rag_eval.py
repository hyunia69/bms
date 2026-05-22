"""Retrieval eval (T4) — measure recall and recommend a 근거없음 threshold.

Loads eval/retrieval_eval.yaml, runs each query through match_documents, then:
  - positive / rag_forcing: is an expected doc in Top-K?  (recall@K)
  - negative: what is the top similarity?  (should fall BELOW threshold)

It then compares the positive-hit similarity distribution against the negative-top
distribution, sweeps candidate thresholds, and recommends the one that best keeps
positives while rejecting negatives. The separation (or overlap) tells us whether
text-embedding-3-small's 한글 변별력 is good enough or we need the -large lever.

Repeatable → run after any model/corpus change to catch regressions (CEO#6).
Threshold is a build-time DESIGN value, not late tuning (CEO T1).

Run: $env:PYTHONPATH=""; .venv\\Scripts\\python.exe -s scripts\\rag_eval.py
Exit 0 if recall == 100% AND negatives separate cleanly; else 1.
"""
from __future__ import annotations

import os
import statistics
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
EVAL_FILE = ROOT / "eval" / "retrieval_eval.yaml"
load_dotenv(ROOT / ".env")


def main() -> None:
    spec = yaml.safe_load(EVAL_FILE.read_text(encoding="utf-8"))
    k = spec.get("match_count", 3)
    # env override lets us A/B a model against the same eval set; yaml records the default.
    model = os.environ.get("EMBED_MODEL", spec.get("embed_model", "text-embedding-3-large"))
    dim = int(os.environ.get("EMBED_DIM", "1536"))
    cases = spec["cases"]

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set — add it to .env.")
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — add to .env.")

    client = OpenAI()
    qresp = client.embeddings.create(model=model, dimensions=dim, input=[c["query"] for c in cases])

    import httpx
    rest = url.rstrip("/") + "/rest/v1"
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}

    pos_hit_sims: list[float] = []   # similarity of the expected doc when it hit
    neg_top_sims: list[float] = []   # top-1 similarity for off-domain queries
    pos_total = pos_hit = 0
    results = []

    with httpx.Client(timeout=60) as http:
        for c, qe in zip(cases, qresp.data):
            r = http.post(f"{rest}/rpc/match_documents", headers=headers, json={
                "query_embedding": qe.embedding, "match_count": k, "filter": {}})
            r.raise_for_status()
            ranked = [((h.get("metadata") or {}).get("source", "?"),
                       float(h.get("similarity", 0.0))) for h in r.json()]
            top_sim = ranked[0][1] if ranked else 0.0
            expect = set(c.get("expect_any") or [])
            if expect:  # positive or rag_forcing
                pos_total += 1
                hit = next((s for src, s in ranked if src in expect), None)
                if hit is not None:
                    pos_hit += 1
                    pos_hit_sims.append(hit)
                results.append((c, "HIT" if hit is not None else "MISS",
                                hit if hit is not None else top_sim, ranked))
            else:       # negative
                neg_top_sims.append(top_sim)
                results.append((c, "neg", top_sim, ranked))

    # ---- per-case ----
    print(f"model={model}  match_count={k}  cases={len(cases)}\n")
    print("=== per-case ===")
    for c, verdict, sim, ranked in results:
        tag = {"HIT": "PASS", "MISS": "FAIL", "neg": "neg "}[verdict]
        sub = f"/{c['subtype']}" if c.get("subtype") else ""
        print(f"  [{tag}] {c['id']:<18} ({c['category']}{sub})  key_sim={sim:.4f}")
        for j, (src, s) in enumerate(ranked, 1):
            mark = "*" if src in set(c.get("expect_any") or []) else " "
            print(f"        {mark}{j}. {src:<40} {s:.4f}")

    # ---- recall ----
    recall = pos_hit / pos_total if pos_total else 0.0
    print(f"\n=== recall ===\n  positives: {pos_hit}/{pos_total} in Top-{k}  (recall={recall:.0%})")
    misses = [c["id"] for c, v, *_ in results if v == "MISS"]
    if misses:
        print(f"  MISSES: {misses}")

    # ---- similarity distributions ----
    def stat(xs):
        return (min(xs), statistics.median(xs), max(xs)) if xs else (0, 0, 0)
    p_min, p_med, p_max = stat(pos_hit_sims)
    n_min, n_med, n_max = stat(neg_top_sims)
    print("\n=== similarity distributions ===")
    print(f"  positive-hit : min={p_min:.4f}  median={p_med:.4f}  max={p_max:.4f}  (n={len(pos_hit_sims)})")
    print(f"  negative-top : min={n_min:.4f}  median={n_med:.4f}  max={n_max:.4f}  (n={len(neg_top_sims)})")
    gap = p_min - n_max
    print(f"  separation gap (min positive - max negative) = {gap:+.4f}")

    # ---- threshold sweep ----
    print("\n=== threshold sweep (keep positives / reject negatives) ===")
    lo = min(pos_hit_sims + neg_top_sims) if (pos_hit_sims or neg_top_sims) else 0.0
    hi = max(pos_hit_sims + neg_top_sims) if (pos_hit_sims or neg_top_sims) else 1.0
    best_t, best_score = None, -1.0
    t = round(lo - 0.01, 2)
    while t <= hi + 0.01:
        kept = sum(1 for s in pos_hit_sims if s >= t)
        rejected = sum(1 for s in neg_top_sims if s < t)
        # balanced score: fraction of positives kept + fraction of negatives rejected
        score = (kept / len(pos_hit_sims) if pos_hit_sims else 0) + \
                (rejected / len(neg_top_sims) if neg_top_sims else 0)
        flag = ""
        if score > best_score:
            best_score, best_t, flag = score, t, ""
        print(f"  t={t:.2f}  pos kept {kept}/{len(pos_hit_sims)}   neg rejected {rejected}/{len(neg_top_sims)}")
        t = round(t + 0.02, 2)

    # ---- verdict ----
    print("\n=== verdict ===")
    clean = gap > 0
    if clean:
        rec_t = round((p_min + n_max) / 2, 3)
        print(f"  CLEAN SEPARATION (gap {gap:+.4f}). 추천 threshold ≈ {rec_t} "
              f"(긍정 최저 {p_min:.3f} ~ 부정 최고 {n_max:.3f} 사이).")
        print(f"  {model} 한글 변별력 충분 (clean) — 현재 임베딩 모델 유지.")
    else:
        kept_at_best = sum(1 for s in pos_hit_sims if s >= best_t)
        rej_at_best = sum(1 for s in neg_top_sims if s < best_t)
        print(f"  OVERLAP (gap {gap:+.4f}) — 긍정 최저({p_min:.3f}) < 부정 최고({n_max:.3f}).")
        print(f"  단일 임계값으로 완전 분리 불가. 절충 best t≈{best_t:.2f} "
              f"(긍정 {kept_at_best}/{len(pos_hit_sims)} 유지, 부정 {rej_at_best}/{len(neg_top_sims)} 거부).")
        print(f"  → 한글 변별력 부족 신호. lever: embed_model=text-embedding-3-large "
              f"(dimensions=1536로 스키마 유지) 후 재평가.")

    ok = (recall >= 1.0) and clean
    print(f"\n{'PASS' if ok else 'REVIEW'} — recall {recall:.0%}, "
          f"{'clean' if clean else 'overlapping'} negative separation.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
