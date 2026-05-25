"""rag_answer.answer() dict → Slack 마크다운 텍스트 (T7 flow3 포맷터).

순수 함수 — 외부 의존 없음(단위 테스트 가능). rag_api(FastAPI)가 호출해
응답 dict 에 slack_text 필드로 동봉하고, Activepieces 는 그대로 스레드에 회신한다.
제어지시는 rag_answer 가드가 이미 차단하므로 여기선 표시 로직만 담당.
"""
from __future__ import annotations


def format_slack(res: dict) -> str:
    if res.get("answer_type") == "no_basis":
        return _format_no_basis(res)
    # no_basis 외 answer_type은 grounded로 처리 (현 계약: grounded | no_basis)
    return _format_grounded(res)


def _format_grounded(res: dict) -> str:
    lines = [f"🔎 *요약*: {(res.get('summary') or '').strip()}"]

    causes = res.get("root_cause_candidates") or []
    if causes:
        lines.append("\n*원인 후보*")
        for i, rc in enumerate(causes, 1):
            conf = rc.get("confidence", "?")
            lines.append(f"{i}. [{conf}] {(rc.get('cause') or '').strip()}")

    checks = res.get("recommended_checks") or []
    if checks:
        lines.append("\n*점검 체크리스트*")
        lines += [f"• {(c or '').strip()}" for c in checks]

    sources = res.get("sources") or []
    if sources:
        lines.append("\n*출처*")
        for s in sources:
            sim = float(s.get("similarity") or 0.0)
            lines.append(
                f"• {s.get('source', '?')} / {s.get('section', '?')} "
                f"(유사도 {sim:.2f}) ※{s.get('origin', 'POC 생성 문서')}"
            )
    return "\n".join(lines)


def _format_no_basis(res: dict) -> str:
    lines = ["⚠️ 제공된 기술 문서에서 이 질문에 대한 충분한 근거를 찾지 못했습니다."]
    checks = res.get("recommended_checks") or []
    if checks:
        lines.append("\n*확인해 보세요*")
        lines += [f"• {(c or '').strip()}" for c in checks]
    return "\n".join(lines)
