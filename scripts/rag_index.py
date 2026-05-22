"""RAG indexer (T3) — chunk all RAG source docs, embed, load into rag_documents,
then verify the guaranteed retrieval scenarios.

Pipeline:
  1. chunk each docs/rag_sources/*.md by '## ' section (chunk carries doc title)
  2. embed every chunk (text-embedding-3-small, 1536d — eng-review locked)
  3. clear rag_documents and insert chunk rows
     (metadata: source / title / section / code / doc_type)
  4. verify the guaranteed scenarios against match_documents (expected doc in Top-3)

This REPLACES the prior whole-doc rows with section chunks (chunking lifted E-3002
from #2 to #1 in earlier experiments). Hybrid lookup later can filter on metadata.code.

Run (clear the global VLibras PYTHONPATH first — see project notes):
  $env:PYTHONPATH=""; .venv\\Scripts\\python.exe -s scripts\\rag_index.py
"""
from __future__ import annotations

import glob
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

try:  # Windows console is cp949; force UTF-8 so Korean prints don't crash.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs" / "rag_sources"
load_dotenv(ROOT / ".env")
# Embedding model is a config knob (eval-driven — CEO T1). Override via env to A/B
# models without editing code. dimensions=1536 keeps the vector(1536) schema fixed,
# so swapping models needs no DB migration — just a re-index.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-large")  # T4 결정 (small은 한글 변별력 부족)
EMBED_DIM = int(os.environ.get("EMBED_DIM", "1536"))
MATCH_COUNT = 3

# Guaranteed retrieval scenarios. Pass bar (eng-review): expected doc in Top-3.
SCENARIOS = [
    ("냉매가 새는 것 같아요", {"E-3002_refrigerant_leak.md"}),
    ("필터 언제 갈아요?", {"P-1001_filter_replacement.md"}),
    ("새벽에 온도가 갑자기 올라갔어요",
     {"E-1002_supply_temp_high.md", "P-2001_seasonal_changeover.md"}),
    ("냉동기 응축압력이 오르고 냉각수 온도도 같이 올라가요",
     {"P-4001_cooling_tower_water.md", "M-2001_chiller_operating_manual.md"}),
]

DOC_TYPE_MAP = {
    "에러코드 레퍼런스": "error_code",
    "점검 및 수리 절차서": "procedure",
    "기기 운전 매뉴얼": "manual",
    "에너지 관리 가이드": "energy",
}
CODE_RE = re.compile(r"^- (?:에러코드|절차코드|매뉴얼코드):\s*([A-Z]-?\d+)", re.M)
DOCTYPE_RE = re.compile(r"^- 문서 종류:\s*(.+)$", re.M)


def chunk_doc(name: str, text: str) -> list[dict]:
    """Split a doc into one chunk per '## ' section; carry title + section meta."""
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip() if lines else name
    code_m = CODE_RE.search(text)
    code = code_m.group(1) if code_m else None
    dt_m = DOCTYPE_RE.search(text)
    doc_type = DOC_TYPE_MAP.get(dt_m.group(1).strip(), "other") if dt_m else "other"

    parts = re.split(r"(?m)^##\s+(.+)$", text)  # [pre, hdr, body, hdr, body, ...]
    chunks, it = [], iter(parts[1:])
    for header in it:
        body = next(it, "").strip()
        header = header.strip()
        chunks.append({
            "content": f"{title} — {header}\n{body}",
            "metadata": {
                "source": name,
                "title": title,
                "section": header,
                "code": code,
                "doc_type": doc_type,
            },
        })
    return chunks


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set — add it to .env.")
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — add to .env.")

    # 1) chunk -------------------------------------------------------------
    chunks: list[dict] = []
    per_doc: dict[str, int] = {}
    for path in sorted(glob.glob(str(DOCS_DIR / "*.md"))):
        name = Path(path).name
        dchunks = chunk_doc(name, Path(path).read_text(encoding="utf-8"))
        chunks += dchunks
        per_doc[name] = len(dchunks)
    if not chunks:
        sys.exit(f"No .md docs found in {DOCS_DIR}")

    print(f"Docs: {len(per_doc)}  Chunks: {len(chunks)}")
    for name, n in per_doc.items():
        print(f"  {name:<42} {n} chunks")

    # 2) embed -------------------------------------------------------------
    client = OpenAI()
    resp = client.embeddings.create(model=EMBED_MODEL, dimensions=EMBED_DIM,
                                    input=[c["content"] for c in chunks])
    for c, e in zip(chunks, resp.data):
        c["embedding"] = e.embedding
    print(f"\nEmbedded {len(chunks)} chunks ({len(chunks[0]['embedding'])}d, {EMBED_MODEL})")

    # 3) clear + load ------------------------------------------------------
    import httpx
    rest = url.rstrip("/") + "/rest/v1"
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    rows = [{"content": c["content"], "metadata": c["metadata"],
             "embedding": c["embedding"]} for c in chunks]
    with httpx.Client(timeout=60) as http:
        http.request("DELETE", f"{rest}/rag_documents", headers=headers,
                     params={"id": "gt.0"}).raise_for_status()
        for i in range(0, len(rows), 50):
            http.post(f"{rest}/rag_documents", headers=headers,
                      json=rows[i:i + 50]).raise_for_status()
    print(f"Loaded {len(rows)} chunk rows into rag_documents (cleared first).")

    # 4) verify scenarios --------------------------------------------------
    print("\n=== Scenario verification (expected doc in Top-3) ===")
    qresp = client.embeddings.create(model=EMBED_MODEL, dimensions=EMBED_DIM,
                                     input=[q for q, _ in SCENARIOS])
    passed = 0
    with httpx.Client(timeout=60) as http:
        for (query, expected), qe in zip(SCENARIOS, qresp.data):
            r = http.post(f"{rest}/rpc/match_documents", headers=headers, json={
                "query_embedding": qe.embedding, "match_count": MATCH_COUNT,
                "filter": {}})
            r.raise_for_status()
            hits = r.json()
            sources = [(h.get("metadata") or {}).get("source", "?") for h in hits]
            ok = any(s in expected for s in sources)
            passed += ok
            print(f"\n  [{'PASS' if ok else 'FAIL'}] {query!r}")
            print(f"        expect one of: {sorted(expected)}")
            for j, (h, s) in enumerate(zip(hits, sources), 1):
                sec = (h.get("metadata") or {}).get("section", "?")
                print(f"        {j}. {s:<40} {h.get('similarity', 0):.4f}  [{sec}]")

    print(f"\n{passed}/{len(SCENARIOS)} scenarios pass (expected doc in Top-{MATCH_COUNT}).")
    sys.exit(0 if passed == len(SCENARIOS) else 1)


if __name__ == "__main__":
    main()
