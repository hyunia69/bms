from slack_format import format_slack


def test_grounded_includes_summary_causes_checks_sources():
    res = {
        "answer_type": "grounded",
        "summary": "필터 막힘으로 풍량이 저하될 수 있습니다.",
        "root_cause_candidates": [
            {"cause": "공기 필터 막힘", "confidence": "high", "evidence_chunk_ids": [0]},
        ],
        "recommended_checks": ["필터 차압계를 점검하세요."],
        "sources": [
            {"source": "P-1001_filter_replacement.md", "section": "증상",
             "similarity": 0.386, "origin": "POC 생성 문서"},
        ],
    }
    out = format_slack(res)
    assert "🔎 *요약*" in out
    assert "필터 막힘으로 풍량" in out
    assert "[high] 공기 필터 막힘" in out
    assert "• 필터 차압계를 점검하세요." in out
    assert "P-1001_filter_replacement.md / 증상" in out
    assert "유사도 0.39" in out


def test_no_basis_shows_warning_and_checks_only():
    res = {
        "answer_type": "no_basis",
        "summary": "근거 없음",
        "root_cause_candidates": [],
        "recommended_checks": ["현재 발생한 알람 코드와 발생 시각을 확인하세요."],
        "sources": [],
    }
    out = format_slack(res)
    assert out.startswith("⚠️")
    assert "충분한 근거를 찾지 못했습니다" in out
    assert "• 현재 발생한 알람 코드" in out
    assert "원인 후보" not in out
    assert "출처" not in out
