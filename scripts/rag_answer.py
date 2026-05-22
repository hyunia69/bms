"""RAG 답변 파이프라인 + 사후 검증 가드 (T5 / eng-review D4).

질문 → 검색(match_documents + threshold) → [근거 있으면] GPT-4o 구조화 출력 생성
→ 사후 가드(가짜인용 0·인용 100%·제어지시 0·원인후보≤N) → 위반 시 1회 재생성 → 근거없음.

핵심 규율(D4): **LLM 출력을 신뢰하지 않고 검증한다.** 얇은 threshold 마진(T4 결론, gap≈0.0006)의
두 번째 방어선. 근거: eng-review D4 / CEO#2(근거없음 별도 응답 타입) / CEO#8(출처 인용) / pass-bar.
answer-eval(#6)과 구조 공유 — scripts/answer_eval.py 가 이 모듈의 answer() 를 호출해 회귀를 검출.

검색·임베딩 컨벤션은 rag_eval.py / rag_index.py 와 동일(.env, httpx REST, EMBED_MODEL env).

실행(전역 VLibras PYTHONPATH 먼저 비우기 — 프로젝트 노트):
  $env:PYTHONPATH=""; .venv\\Scripts\\python.exe -s scripts\\rag_answer.py "냉매가 새는 것 같아요"
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Literal

import httpx
import yaml
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

try:  # Windows 콘솔은 cp949 — 한글 print 깨짐 방지
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
EVAL_FILE = ROOT / "eval" / "retrieval_eval.yaml"  # threshold·모델 기본값 SoT 재사용

# ── config knobs (env override 가능 — A/B·튜닝) ───────────────────────────────
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-large")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "1536"))
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o")     # CEO#16: GPT-4o로 시작
MAX_CAUSES = int(os.environ.get("MAX_CAUSES", "3"))   # 원인후보 상한 N (가드 4)
MATCH_COUNT = int(os.environ.get("MATCH_COUNT", "5")) # 검색 Top-K (생성용 맥락; eval 기준은 Top-3)


def _thresholds() -> tuple[float, float]:
    """strict = retrieval_eval.yaml recommended_threshold(0.34), widen = strict - 0.04.
    CEO#2: threshold 넓혀 재검색 → 그래도 0건이면 근거없음. env로 override 가능."""
    rec = 0.34
    try:
        rec = float(yaml.safe_load(EVAL_FILE.read_text(encoding="utf-8")).get("recommended_threshold", 0.34))
    except Exception:
        pass
    strict = float(os.environ.get("STRICT_THRESHOLD", rec))
    widen = float(os.environ.get("WIDEN_THRESHOLD", round(strict - 0.04, 3)))
    return strict, widen


# ── 구조화 출력 스키마 (chat.completions.parse 로 강제) ──────────────────────
class Citation(BaseModel):
    chunk_id: int      # 아래 제공된 청크 번호만 (가드: 존재 검증)
    source: str
    section: str
    snippet: str       # 청크에서 인용한 짧은 근거 문구


class RootCause(BaseModel):
    cause: str
    confidence: Literal["high", "medium", "low"]
    evidence_chunk_ids: list[int]   # 가드: 모두 실제 청크여야 + ≥1개 필수(grounded)


class Answer(BaseModel):
    answer_type: Literal["grounded", "no_basis"]
    summary: str
    root_cause_candidates: list[RootCause]
    recommended_checks: list[str]   # 점검·확인 가이드 (제어지시 아님)
    citations: list[Citation]


SYSTEM = f"""당신은 공장 빌딩 HVAC(공조) 모니터링 보조자다. 아래 '근거 문서'만을 사용해 한국어로 답한다.

규칙(엄수):
- 근거 문서에 없는 사실을 지어내지 않는다. 모든 요약·원인 후보 주장은 근거 청크를 인용(chunk_id)해야 한다.
- chunk_id 는 아래 제공된 청크 번호만 사용한다. 제공되지 않은 번호를 인용하면 안 된다.
- 원인 후보는 최대 {MAX_CAUSES}개. 가능성 높은 순으로.
- 절대 기기 작동(제어) 지시를 하지 않는다: 기동/정지/켜기/끄기/밸브 개폐/설정값(설정온도·압력) 변경/
  주파수·인버터·rpm 조정/차단기·전원 조작/리셋 등 금지. 너는 '점검·확인' 가이드만 제시한다
  (예: "필터 차압을 점검하세요", "냉매 압력 추세를 확인하세요"). 정비 행위 설명은 가능하나 운전 제어 지시는 금지.
- 근거 문서가 질문과 무관하거나 부족하면 answer_type="no_basis" 로 답하고,
  root_cause_candidates 와 citations 는 비우고, recommended_checks 에 일반 확인 항목만 둔다.
"""

# 제어(운전) 지시 탐지 — 정비/점검 어휘(점검·확인·교체·청소·측정·보충)는 허용, 운전 작동만 금지.
# POC 수준 lexicon: explicit 작동 명령형을 잡는다(한계는 answer_eval control_bait 케이스로 회귀 감시).
_CONTROL_PATTERNS = [
    r"기동(?:하|시)", r"가동(?:하|시|을 시작)", r"운전.{0,4}(?:개시|시작|정지|중지)",
    r"정지(?:하세요|하십시오|해\s|시키|할\s|하라)", r"멈추(?:세요|십시오|도록|게\s|어라)",
    r"(?:켜|끄)(?:세요|십시오|기를|도록|라\b| 주)", r"전원.{0,4}(?:차단|투입|내리|올리|끄|켜)",
    r"차단기.{0,4}(?:내리|올리|차단|투입)", r"리셋(?:하|시)", r"재기동", r"재부팅",
    r"밸브.{0,6}(?:열|닫|개방|폐쇄|잠그|조절)", r"댐퍼.{0,6}(?:열|닫|조절)",
    r"설정\s*(?:온도|값|압력|유량).{0,8}(?:변경|조정|올리|낮추|바꾸|로\s*설정|으로\s*설정|로\s*맞추)",
    r"(?:주파수|인버터|rpm|회전수).{0,8}(?:조정|변경|올리|낮추|높이)",
]
_CONTROL_RE = re.compile("|".join(_CONTROL_PATTERNS))

# CEO#2: 0건/가드 위반 지속 시 — 구체 제어지시·가짜 인용 없이 확인 체크리스트만.
NO_BASIS_CHECKS = [
    "현재 발생한 알람 코드와 발생 시각을 확인하세요.",
    "해당 기기의 최근 센서 추세(온도·압력·유량·전류)를 점검하세요.",
    "기기 운전 매뉴얼·제조사 문서에서 관련 절차를 확인하세요.",
    "필요 시 설비 담당자에게 현장 점검을 요청하세요.",
]


def _rest(url: str, key: str) -> tuple[str, dict]:
    return url.rstrip("/") + "/rest/v1", {
        "apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def retrieve(query: str, *, client: OpenAI, http: httpx.Client, rest: str,
             headers: dict, k: int = MATCH_COUNT) -> list[dict]:
    """질문 임베딩 → match_documents Top-K. chunk_id = 반환 순서(LLM 이 인용할 안정 번호)."""
    qe = client.embeddings.create(model=EMBED_MODEL, dimensions=EMBED_DIM,
                                  input=[query]).data[0].embedding
    r = http.post(f"{rest}/rpc/match_documents", headers=headers,
                  json={"query_embedding": qe, "match_count": k, "filter": {}})
    r.raise_for_status()
    chunks = []
    for i, h in enumerate(r.json()):
        md = h.get("metadata") or {}
        chunks.append({
            "chunk_id": i,
            "source": md.get("source", "?"),
            "title": md.get("title", "?"),
            "section": md.get("section", "?"),
            "content": h.get("content", ""),
            "similarity": float(h.get("similarity", 0.0)),
        })
    return chunks


def gate(chunks: list[dict], strict: float, widen: float) -> tuple[list[dict], str]:
    """threshold 게이트(CEO#2). strict 통과 없으면 widen 재시도, 그래도 없으면 근거없음."""
    kept = [c for c in chunks if c["similarity"] >= strict]
    if kept:
        return kept, "strict"
    kept = [c for c in chunks if c["similarity"] >= widen]
    if kept:
        return kept, "widen"
    return [], "none"


def _build_user_msg(query: str, chunks: list[dict], violations: list[str] | None) -> str:
    lines = [f"[질문]\n{query}\n", "[근거 문서]"]
    for c in chunks:
        lines.append(f"--- chunk_id={c['chunk_id']} | source={c['source']} | "
                     f"section={c['section']} | similarity={c['similarity']:.3f} ---\n{c['content']}")
    if violations:
        lines.append("\n[직전 출력이 위반한 규칙 — 반드시 수정해 다시 답하라]")
        lines += [f"- {v}" for v in violations]
    return "\n".join(lines)


def _parse(client: OpenAI, **kw):
    """openai 2.x 는 chat.completions.parse(구조화 출력). 구버전 호환으로 beta 폴백."""
    fn = getattr(client.chat.completions, "parse", None)
    if fn is None:
        fn = client.beta.chat.completions.parse
    return fn(**kw)


def generate(query: str, chunks: list[dict], *, client: OpenAI,
             violations: list[str] | None = None) -> Answer | None:
    """GPT-4o 구조화 출력. temperature=0(eval 안정·재현성). 거부 시 None."""
    completion = _parse(
        client, model=LLM_MODEL, temperature=0, response_format=Answer,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": _build_user_msg(query, chunks, violations)}],
    )
    return completion.choices[0].message.parsed  # 거부되면 None


def _scan_control(ans: Answer) -> list[str]:
    """LLM 자체 서술(요약·원인·체크리스트)에서 운전 제어 지시 탐지. 인용 스니펫(문서 발췌)은 제외."""
    hits = []
    fields = [("summary", ans.summary)]
    fields += [(f"check[{i}]", t) for i, t in enumerate(ans.recommended_checks)]
    fields += [(f"cause[{i}]", rc.cause) for i, rc in enumerate(ans.root_cause_candidates)]
    for where, text in fields:
        m = _CONTROL_RE.search(text or "")
        if m:
            hits.append(f"{where}: …{m.group(0)}…")
    return hits


def guard(ans: Answer, chunks: list[dict]) -> list[str]:
    """사후 검증기(D4). 위반 목록 반환(빈 리스트 = 통과)."""
    valid = {c["chunk_id"] for c in chunks}
    v: list[str] = []

    # 가짜인용 0 — 존재하지 않는 chunk_id 인용 금지
    for cit in ans.citations:
        if cit.chunk_id not in valid:
            v.append(f"가짜인용: citations 에 없는 chunk_id={cit.chunk_id}")
    for rc in ans.root_cause_candidates:
        for cid in rc.evidence_chunk_ids:
            if cid not in valid:
                v.append(f"가짜인용: 원인후보 '{rc.cause[:18]}…' 가 없는 chunk_id={cid} 인용")

    # 원인후보 ≤ N
    if len(ans.root_cause_candidates) > MAX_CAUSES:
        v.append(f"원인후보 초과: {len(ans.root_cause_candidates)} > {MAX_CAUSES}")

    # 제어지시 0
    for h in _scan_control(ans):
        v.append(f"제어지시 검출: {h}")

    if ans.answer_type == "grounded":
        # 인용 100% — grounded 면 출처가 있어야 + 각 원인후보가 유효 근거 ≥1
        if not ans.citations:
            v.append("인용 누락: grounded 인데 citations 비어 있음")
        for rc in ans.root_cause_candidates:
            if not any(cid in valid for cid in rc.evidence_chunk_ids):
                v.append(f"인용 누락: 원인후보 '{rc.cause[:18]}…' 에 유효 근거 청크 없음")
    else:  # no_basis 일관성
        if ans.root_cause_candidates:
            v.append("no_basis 일관성 위반: 근거없음인데 원인후보 존재")
        if ans.citations:
            v.append("no_basis 일관성 위반: 근거없음인데 citations 존재")
    return v


def _sources(ans: Answer, kept: list[dict]) -> list[dict]:
    """CEO#8: 인용된 청크를 출처로(제목+섹션+유사도+스니펫). 현 코퍼스는 전부 POC 생성 문서."""
    by_id = {c["chunk_id"]: c for c in kept}
    cited_ids, snippets = [], {}
    for cit in ans.citations:
        if cit.chunk_id in by_id:
            cited_ids.append(cit.chunk_id)
            snippets.setdefault(cit.chunk_id, cit.snippet)
    for rc in ans.root_cause_candidates:
        for cid in rc.evidence_chunk_ids:
            if cid in by_id:
                cited_ids.append(cid)
    out = []
    for cid in dict.fromkeys(cited_ids):  # 순서 유지 dedup
        c = by_id[cid]
        out.append({"source": c["source"], "title": c["title"], "section": c["section"],
                    "similarity": c["similarity"],
                    "snippet": snippets.get(cid) or (c["content"][:120] + "…"),
                    "origin": "POC 생성 문서"})
    return out


def _no_basis(query: str, *, reason: str, retrieval_mode: str,
              violations: list[str] | None = None, forced: bool = False) -> dict:
    return {
        "answer_type": "no_basis", "query": query,
        "summary": "제공된 기술 문서에서 이 질문에 대한 충분한 근거를 찾지 못했습니다. (⚠️ 근거 없음)",
        "root_cause_candidates": [], "recommended_checks": list(NO_BASIS_CHECKS), "sources": [],
        "retrieval_mode": retrieval_mode, "regenerated": forced,
        "guard_passed": True, "guard_violations": [], "no_basis_reason": reason,
        "forced_violations": violations or [],
    }


def answer(query: str) -> dict:
    """파이프라인 오케스트레이터. CLI·answer_eval 공용. 반환 dict 는 항상 가드-clean."""
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set — add it to .env.")
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — add to .env.")

    strict, widen = _thresholds()
    client = OpenAI()
    rest, headers = _rest(url, key)
    with httpx.Client(timeout=60) as http:
        chunks = retrieve(query, client=client, http=http, rest=rest, headers=headers)
    kept, mode = gate(chunks, strict, widen)

    if not kept:  # 0건 → LLM 호출 없이 근거없음 (환각 0)
        return _no_basis(query, reason=f"검색 결과 threshold({strict}) 미달", retrieval_mode=mode)

    ans = generate(query, kept, client=client)
    violations = guard(ans, kept) if ans is not None else ["LLM 거부/파싱 실패(parsed=None)"]

    if violations:  # D4: 위반 시 1회 재생성
        ans = generate(query, kept, client=client, violations=violations)
        violations = guard(ans, kept) if ans is not None else ["LLM 거부/파싱 실패(재생성)"]

    if violations:  # 재생성에도 위반 → 안전하게 근거없음
        return _no_basis(query, reason="가드 위반 지속(2회)", retrieval_mode=mode,
                         violations=violations, forced=True)

    if ans.answer_type == "no_basis":  # LLM 이 스스로 근거없음 판정
        return _no_basis(query, reason="LLM 근거없음 판정(맥락 부적합)", retrieval_mode=mode)

    return {
        "answer_type": "grounded", "query": query, "summary": ans.summary,
        "root_cause_candidates": [rc.model_dump() for rc in ans.root_cause_candidates],
        "recommended_checks": list(ans.recommended_checks), "sources": _sources(ans, kept),
        "retrieval_mode": mode, "regenerated": False, "guard_passed": True,
        "guard_violations": [], "no_basis_reason": None,
    }


def _print_report(res: dict) -> None:
    print(f"질문: {res['query']}")
    print(f"[검색] mode={res['retrieval_mode']}   [가드] {'PASS' if res['guard_passed'] else 'FAIL'}"
          f"   재생성/강제={res['regenerated']}")
    print(f"\n답변 유형: {res['answer_type']}")
    if res.get("no_basis_reason"):
        print(f"사유: {res['no_basis_reason']}")
        if res.get("forced_violations"):
            print("  강제 전 위반:")
            for v in res["forced_violations"]:
                print(f"    - {v}")
    print(f"\n요약:\n  {res['summary']}")
    if res["root_cause_candidates"]:
        print(f"\n원인 후보 (≤{MAX_CAUSES}):")
        for i, rc in enumerate(res["root_cause_candidates"], 1):
            ev = ",".join(str(c) for c in rc["evidence_chunk_ids"])
            print(f"  {i}. [{rc['confidence']}] {rc['cause']}  (근거 chunk {ev})")
    if res["recommended_checks"]:
        print("\n점검 체크리스트:")
        for c in res["recommended_checks"]:
            print(f"  - {c}")
    if res["sources"]:
        print("\n출처:")
        for i, s in enumerate(res["sources"], 1):
            print(f"  {i}. {s['source']} / {s['section']}  (유사도 {s['similarity']:.3f})  ※ {s['origin']}")
            print(f"     \"{s['snippet']}\"")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('Usage: python -s scripts/rag_answer.py "질문 텍스트"')
    _print_report(answer(" ".join(sys.argv[1:])))


if __name__ == "__main__":
    main()
