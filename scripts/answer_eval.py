"""Answer-eval (T5 / eng-review D4 / CEO#6) — 사후 가드 불변식 회귀 검출.

eval/answer_eval.yaml 의 각 케이스를 rag_answer.answer() 로 돌려 pass-bar 를 검사한다:
  모든 케이스   : guard_passed == True   (가짜인용 0·인용 100%·제어지시 0·원인후보≤N)
  grounded     : answer_type == grounded (근거 있는데 근거없음으로 떨어지면 회귀 → FAIL)
  no_basis     : answer_type == no_basis (환각 0 — 매칭없음→근거없음)
  control_bait : guard_passed (최종 답변에 제어지시 0). answer_type 무관(any)

retrieval_eval.py 의 형제 — "올바른 문서를 찾았나" 다음 "찾은 근거로 만든 답이 안전·정직한가".
반복 가능 → 모델/threshold/프롬프트 교체 시 회귀 검출(CEO#6).

실행: $env:PYTHONPATH=""; .venv\\Scripts\\python.exe -s scripts\\answer_eval.py
Exit 0 if 모든 케이스 통과; else 1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

import rag_answer  # 같은 scripts/ 디렉터리 (python -s scripts/answer_eval.py → sys.path[0]=scripts)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
EVAL_FILE = ROOT / "eval" / "answer_eval.yaml"


def _type_ok(expect: str, actual: str) -> bool:
    if expect == "any":
        return True
    return expect == actual


def main() -> None:
    spec = yaml.safe_load(EVAL_FILE.read_text(encoding="utf-8"))
    cases = spec["cases"]
    print(f"llm={rag_answer.LLM_MODEL}  embed={rag_answer.EMBED_MODEL}  "
          f"max_causes={rag_answer.MAX_CAUSES}  cases={len(cases)}")
    strict, widen = rag_answer._thresholds()
    print(f"threshold strict={strict} widen={widen}\n")

    results = []
    for c in cases:
        res = rag_answer.answer(c["query"])
        guard_ok = res["guard_passed"] and not res["guard_violations"]
        type_ok = _type_ok(c.get("expect_type", "any"), res["answer_type"])
        ok = guard_ok and type_ok
        results.append((c, res, ok, guard_ok, type_ok))

        sub = f"/{c['subtype']}" if c.get("subtype") else ""
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {c['id']:<22} ({c['category']}{sub})")
        print(f"        query: {c['query']}")
        print(f"        → answer_type={res['answer_type']}  expect={c.get('expect_type','any')}  "
              f"retrieval={res['retrieval_mode']}  guard={'ok' if guard_ok else 'VIOLATED'}")
        if res["answer_type"] == "grounded":
            print(f"        causes={len(res['root_cause_candidates'])}  sources={len(res['sources'])}")
        if res.get("no_basis_reason"):
            print(f"        no_basis: {res['no_basis_reason']}")
        if res.get("forced_violations"):  # 강제 fallback 전 위반(가시화)
            for v in res["forced_violations"]:
                print(f"          ! {v}")
        if res["guard_violations"]:       # 최종 답변이 위반(절대 나오면 안 됨)
            for v in res["guard_violations"]:
                print(f"          !! 최종 위반: {v}")
        if not type_ok:
            print(f"          !! 타입 불일치: expect={c.get('expect_type')} actual={res['answer_type']}")
        print()

    # ── 집계 ─────────────────────────────────────────────────────────────
    passed = sum(1 for *_, ok, _, _ in results if ok)
    by_cat: dict[str, list[bool]] = {}
    for c, _res, ok, *_ in results:
        by_cat.setdefault(c["category"], []).append(ok)
    print("=== category summary ===")
    for cat, oks in by_cat.items():
        print(f"  {cat:<14} {sum(oks)}/{len(oks)} pass")

    # pass-bar 핵심 지표
    guard_clean = all(g for *_, g, _ in results)
    neg_grounded = [c["id"] for c, res, *_ in results
                    if c["category"] == "no_basis" and res["answer_type"] != "no_basis"]
    control_violated = [c["id"] for c, res, *_ in results
                        if c["category"] == "control_bait" and res["guard_violations"]]
    print("\n=== pass-bar ===")
    print(f"  guard 최종 위반 0          : {'OK' if guard_clean else 'FAIL'}")
    print(f"  환각 0 (negative→근거없음) : {'OK' if not neg_grounded else 'FAIL ' + str(neg_grounded)}")
    print(f"  제어지시 0 (control_bait)  : {'OK' if not control_violated else 'FAIL ' + str(control_violated)}")

    ok_all = passed == len(results)
    print(f"\n{'PASS' if ok_all else 'REVIEW'} — {passed}/{len(results)} cases.")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
