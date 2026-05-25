from fastapi.testclient import TestClient

import rag_api

client = TestClient(rag_api.app)

FAKE_GROUNDED = {
    "answer_type": "grounded", "query": "",
    "summary": "필터 교체 주기 안내.",
    "root_cause_candidates": [],
    "recommended_checks": ["차압계를 점검하세요."],
    "sources": [{"source": "P-1001_filter_replacement.md", "section": "교체 주기",
                 "similarity": 0.5, "origin": "POC 생성 문서"}],
    "retrieval_mode": "strict", "regenerated": False,
    "guard_passed": True, "guard_violations": [], "no_basis_reason": None,
}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_answer_requires_token(monkeypatch):
    monkeypatch.setattr(rag_api, "API_TOKEN", "secret")
    r = client.post("/answer", json={"query": "필터 언제 갈아요?"})  # 토큰 없음
    assert r.status_code == 401


def test_answer_success_includes_slack_text(monkeypatch):
    monkeypatch.setattr(rag_api, "API_TOKEN", "secret")
    monkeypatch.setattr(rag_api.rag_answer, "answer",
                        lambda q: dict(FAKE_GROUNDED, query=q))
    r = client.post("/answer", json={"query": "필터 언제 갈아요?"},
                    headers={"X-API-Token": "secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer_type"] == "grounded"
    assert "slack_text" in body
    assert "🔎 *요약*" in body["slack_text"]


def test_answer_empty_query_422(monkeypatch):
    monkeypatch.setattr(rag_api, "API_TOKEN", "secret")
    r = client.post("/answer", json={"query": "   "},
                    headers={"X-API-Token": "secret"})
    assert r.status_code == 422


def test_answer_engine_not_configured_503(monkeypatch):
    monkeypatch.setattr(rag_api, "API_TOKEN", "secret")
    def boom(q):
        raise SystemExit("missing env")
    monkeypatch.setattr(rag_api.rag_answer, "answer", boom)
    r = client.post("/answer", json={"query": "필터 언제 갈아요?"},
                    headers={"X-API-Token": "secret"})
    assert r.status_code == 503
