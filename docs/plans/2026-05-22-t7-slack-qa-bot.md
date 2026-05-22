# T7 flow3 — Slack Q&A 봇 (1단계) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slack에서 `@봇 질문` 멘션 시 BMS RAG 답변 엔진(`rag_answer.answer()`)이 기술 문서 기반 답변을 스레드로 회신하는 1단계 작동 봇.

**Architecture:** 로컬 FastAPI가 `rag_answer.answer()`를 HTTP로 노출(rag_answer 수정 없음 → 가드·eval 그대로). ngrok 터널로 공개 URL 확보. Activepieces 클라우드가 Slack 멘션을 받아 HTTP 호출 후 스레드 회신. Slack 메시지 포맷은 순수 함수로 분리해 FastAPI가 `slack_text` 필드에 동봉 → Activepieces는 패스스루.

**Tech Stack:** Python FastAPI + uvicorn, pytest(신규), ngrok, Activepieces 클라우드, Slack 앱. 기존 rag_answer(OpenAI 임베딩+GPT-4o, Supabase pgvector).

**실행 함정(전 task 공통):** Python 실행 전 항상 `$env:PYTHONPATH=""` + `-s`(전역 VLibras PYTHONPATH 회피). venv = `.venv\Scripts\python.exe`.

---

## File Structure

| 파일 | 역할 |
|---|---|
| `scripts/slack_format.py` (생성) | `format_slack(res: dict) -> str` 순수 함수. rag_answer dict → Slack 마크다운. 외부 의존 0(테스트 쉬움) |
| `scripts/rag_api.py` (생성) | FastAPI 래퍼. `GET /health`, `POST /answer`(토큰 인증→rag_answer.answer→slack_format→dict+slack_text). `import rag_answer` 패턴 |
| `tests/conftest.py` (생성) | scripts/를 sys.path에 추가(pytest가 `import rag_answer`/`slack_format`/`rag_api` 가능하게) |
| `tests/test_slack_format.py` (생성) | 포맷터 단위 테스트(순수, 모킹 불필요) |
| `tests/test_rag_api.py` (생성) | FastAPI TestClient + `rag_answer.answer` monkeypatch(OpenAI/Supabase 미호출) |
| `requirements.txt` (수정) | `fastapi`, `uvicorn[standard]`, `pytest` 추가 |
| `.env` / `.env.example` (수정) | `RAG_API_TOKEN` 추가(공유 시크릿) |
| (외부) Slack 앱 · Activepieces flow · ngrok | 사용자 셋업(Task 5–7 가이드) |

---

## Task 1: 의존성 + 환경 변수

**Files:**
- Modify: `requirements.txt`
- Modify: `.env`, `.env.example`

- [ ] **Step 1: requirements.txt에 추가**

`requirements.txt` 끝에 추가:
```
fastapi>=0.110       # T7: rag_answer 를 HTTP 로 노출
uvicorn[standard]>=0.29  # T7: ASGI 서버
pytest>=8            # T7: rag_api / slack_format 단위 테스트
```

- [ ] **Step 2: 설치**

Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pip install -r requirements.txt`
Expected: fastapi, uvicorn, pytest 설치 완료(이미 있는 것은 skip).

- [ ] **Step 3: `.env.example`에 토큰 항목 추가**

`.env.example` 끝에 추가:
```
# T7: rag_api(FastAPI) 공유 토큰 — Activepieces HTTP 헤더 X-API-Token 과 비교. 임의 난수 문자열.
RAG_API_TOKEN=
```

- [ ] **Step 4: `.env`에 실제 토큰 설정(로컬, 커밋 안 됨)**

`.env`에 추가(난수 생성):
Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -c "import secrets; print('RAG_API_TOKEN=' + secrets.token_urlsafe(32))"`
출력된 줄을 `.env`에 붙여넣기. (`.env`는 .gitignore 대상이라 안전.)

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example
git commit -m "chore(T7): add fastapi/uvicorn/pytest deps + RAG_API_TOKEN env"
```

---

## Task 2: Slack 메시지 포맷터 (`slack_format.py`)

**Files:**
- Create: `scripts/slack_format.py`
- Create: `tests/conftest.py`
- Test: `tests/test_slack_format.py`

- [ ] **Step 1: `tests/conftest.py` 작성(테스트가 scripts 모듈을 import 가능하게)**

```python
"""pytest 부트스트랩 — scripts/ 를 sys.path 에 올린다.

scripts 는 패키지(__init__.py)가 아니라 직접 실행 스크립트 묶음이라
(answer_eval.py 의 `import rag_answer` 패턴), 테스트도 같은 경로 규약을 쓴다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
```

- [ ] **Step 2: 실패하는 테스트 작성 `tests/test_slack_format.py`**

```python
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
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pytest tests\test_slack_format.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'slack_format'`

- [ ] **Step 4: `scripts/slack_format.py` 구현**

```python
"""rag_answer.answer() dict → Slack 마크다운 텍스트 (T7 flow3 포맷터).

순수 함수 — 외부 의존 없음(단위 테스트 가능). rag_api(FastAPI)가 호출해
응답 dict 에 slack_text 필드로 동봉하고, Activepieces 는 그대로 스레드에 회신한다.
제어지시는 rag_answer 가드가 이미 차단하므로 여기선 표시 로직만 담당.
"""
from __future__ import annotations


def format_slack(res: dict) -> str:
    if res.get("answer_type") == "no_basis":
        return _format_no_basis(res)
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
            sim = float(s.get("similarity", 0.0))
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
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pytest tests\test_slack_format.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add scripts/slack_format.py tests/conftest.py tests/test_slack_format.py
git commit -m "feat(T7): slack_format — rag_answer dict to Slack markdown"
```

---

## Task 3: FastAPI 래퍼 (`rag_api.py`)

**Files:**
- Create: `scripts/rag_api.py`
- Test: `tests/test_rag_api.py`

- [ ] **Step 1: 실패하는 테스트 작성 `tests/test_rag_api.py`**

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pytest tests\test_rag_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rag_api'`

- [ ] **Step 3: `scripts/rag_api.py` 구현**

```python
"""FastAPI 래퍼 — rag_answer.answer() 를 HTTP 로 노출 (T7 flow3, 1단계).

[Slack 멘션] → [Activepieces] → POST /answer → 이 서버 → rag_answer.answer()
→ {**dict, "slack_text": ...} → Activepieces 가 slack_text 를 스레드 회신.

rag_answer 는 import 만 — 수정 없음(가드·eval 그대로). slack_format 도 동일.
인증: 헤더 X-API-Token == .env RAG_API_TOKEN (ngrok URL 은 공개라 필수).

실행(전역 VLibras PYTHONPATH 비우기):
  $env:PYTHONPATH=""; .venv\\Scripts\\python.exe -s scripts\\rag_api.py
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

import rag_answer        # 같은 scripts/ (sys.path[0]=scripts; answer_eval.py 와 동일 패턴)
import slack_format

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
API_TOKEN = os.environ.get("RAG_API_TOKEN", "")

app = FastAPI(title="BMS RAG API", version="1")


class AnswerRequest(BaseModel):
    query: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/answer")
def post_answer(req: AnswerRequest, x_api_token: str = Header(default="")) -> dict:
    if not API_TOKEN or x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Token")
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="query is empty")
    res = rag_answer.answer(query)
    res["slack_text"] = slack_format.format_slack(res)
    return res


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pytest tests\test_rag_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 전체 테스트 + 회귀 게이트**

Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pytest tests\ -v`
Expected: PASS (6 passed)

답변 엔진 불변 확인(선택, OpenAI 비용 발생):
Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\answer_eval.py`
Expected: PASS — 12/12 (rag_answer 무수정이므로 그대로)

- [ ] **Step 6: Commit**

```bash
git add scripts/rag_api.py tests/test_rag_api.py
git commit -m "feat(T7): rag_api FastAPI wrapper (POST /answer + token auth + /health)"
```

---

## Task 4: 로컬 기동 + ngrok 터널 + curl 스모크

**Files:** 없음(수동 검증). 사전: Task 5의 ngrok 설치 완료.

- [ ] **Step 1: FastAPI 로컬 기동(터미널 A, 켜둔 채로)**

Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_api.py`
Expected: `Uvicorn running on http://0.0.0.0:8000`

- [ ] **Step 2: 헬스체크(터미널 B)**

Run: `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`

- [ ] **Step 3: 토큰 없이 401 확인**

Run: `curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/answer -H "Content-Type: application/json" -d '{\"query\":\"필터 언제 갈아요?\"}'`
Expected: `401`

- [ ] **Step 4: grounded 질문(토큰 포함) — `<TOKEN>`은 `.env`의 RAG_API_TOKEN 값**

Run: `curl -X POST http://localhost:8000/answer -H "Content-Type: application/json" -H "X-API-Token: <TOKEN>" -d '{\"query\":\"냉매가 새는 것 같아요\"}'`
Expected: JSON에 `"answer_type":"grounded"` + `"slack_text"`에 `🔎 *요약*` 포함

- [ ] **Step 5: no_basis 질문 확인**

Run: `curl -X POST http://localhost:8000/answer -H "Content-Type: application/json" -H "X-API-Token: <TOKEN>" -d '{\"query\":\"오늘 점심 메뉴 추천해줘\"}'`
Expected: `"answer_type":"no_basis"` + slack_text가 `⚠️`로 시작

- [ ] **Step 6: ngrok 터널 + 공개 URL 헬스체크(터미널 C)** — ngrok 셋업은 Task 5

Run: `ngrok http 8000`
Expected: `Forwarding https://<고정도메인>.ngrok-free.app -> http://localhost:8000`
브라우저/curl로 `https://<도메인>/health` → `{"status":"ok"}` 확인. 이 공개 URL을 Task 7에 사용.

---

## Task 5: ngrok 셋업 (사용자 직접 — 가이드)

**코드 아님. 외부 도구.** 아래는 가이드라인이며 실제 화면을 보며 함께 진행한다.

- [ ] **Step 1: 계정 + 설치** — https://ngrok.com 가입(무료) → 플랫폼별 설치(Windows: `winget install ngrok` 또는 다운로드).
- [ ] **Step 2: authtoken 등록** — 대시보드의 authtoken 복사 → `ngrok config add-authtoken <TOKEN>`.
- [ ] **Step 3: 고정 도메인 확보(무료 1개)** — ngrok 대시보드 → Domains → 무료 정적 도메인 1개 생성(예: `<이름>.ngrok-free.app`). 재시작해도 URL 고정.
- [ ] **Step 4: 터널 기동** — `ngrok http --domain=<이름>.ngrok-free.app 8000`. 이 도메인이 Activepieces가 호출할 공개 URL.

---

## Task 6: Slack 앱 셋업 (사용자 직접 — 가이드)

**코드 아님. 계정·권한.** 함께 진행.

- [ ] **Step 1: 앱 생성** — https://api.slack.com/apps → Create New App → From scratch → 이름(예: BMS봇) + 대상 워크스페이스 선택.
- [ ] **Step 2: Bot Token Scopes 추가** — OAuth & Permissions → Scopes → Bot Token Scopes에 **`app_mentions:read`**, **`chat:write`** 추가.
- [ ] **Step 3: 워크스페이스 설치** — Install to Workspace → 승인 → **Bot User OAuth Token(`xoxb-...`)** 복사(Task 7에서 Activepieces Slack 연결에 사용).
- [ ] **Step 4: 봇을 채널에 초대** — 테스트할 Slack 채널에서 `/invite @BMS봇`.
- [ ] **Step 5: 이벤트 구독** — Event Subscriptions는 **Activepieces Slack 트리거가 처리**(Task 7). Activepieces가 Slack 연결을 OAuth로 잡고 멘션 이벤트를 수신한다(별도 Request URL 수동 등록 불필요할 수 있음 — Activepieces UI 안내를 따른다).

---

## Task 7: Activepieces flow 구성 (사용자 직접 — 가이드)

**코드 아님. 노코드 조립.** 함께 진행. 목표 flow: `Slack 멘션 트리거 → HTTP 요청(rag_api) → Slack 스레드 회신`.

- [ ] **Step 1: 계정 + flow 생성** — https://cloud.activepieces.com 가입 → New Flow.
- [ ] **Step 2: 트리거 = Slack** — Slack piece → 트리거 `New Mention`(또는 `New Message` + 멘션 조건) → Slack 연결(Task 6의 OAuth/봇 토큰). 트리거 출력에서 `text`(메시지 본문), `channel`, `ts`(메시지 타임스탬프) 필드 확인.
- [ ] **Step 3: 액션1 = HTTP 요청** — Core/HTTP piece:
  - Method: `POST`
  - URL: `https://<ngrok 고정도메인>/answer`
  - Headers: `Content-Type: application/json`, `X-API-Token: <.env RAG_API_TOKEN 값>`
  - Body(JSON): `{ "query": "{{trigger.text 에서 봇 멘션 제거}}" }` — 멘션 토큰 `<@BOTID>` 제거. Activepieces Text Helper(replace) 또는 Code piece로 정규식 `<@[A-Z0-9]+>` 제거 후 trim.
- [ ] **Step 4: 액션2 = Slack 회신** — Slack piece → `Send Message to Channel`(또는 reply):
  - Channel: `{{trigger.channel}}`
  - Thread ts: `{{trigger.ts}}` (원 메시지 스레드에 회신)
  - Text: `{{step_HTTP.body.slack_text}}` (FastAPI가 만든 포맷 텍스트 그대로)
- [ ] **Step 5: HTTP 실패 처리** — HTTP 스텝에 "Continue on failure" + 분기: 실패 시 Slack에 "지금 답변 엔진에 닿지 못했어요. 잠시 후 다시 시도해 주세요" 회신(thread_ts 동일).
- [ ] **Step 6: 게시(Publish)** — flow 활성화.

---

## Task 8: E2E 검증 (수동)

**Files:** 없음. 사전: rag_api 기동 + ngrok 터널 + Activepieces flow 게시.

- [ ] **Step 1: grounded** — Slack 채널에서 `@BMS봇 냉매가 새는 것 같아요` → 30초 내 스레드에 `🔎 요약 + 원인 후보 + 점검 + 출처(E-3002)` 회신 확인.
- [ ] **Step 2: no_basis** — `@BMS봇 오늘 점심 메뉴 추천해줘` → `⚠️ 충분한 근거를 찾지 못했습니다 + 일반 확인 항목` 회신 확인(환각 없음).
- [ ] **Step 3: 제어지시 차단** — `@BMS봇 냉매가 새는데 압축기를 어떻게 멈추나요?` → 회신에 기동/정지 등 **운전 제어 지시가 없는지** 확인(가드 작동, no_basis 또는 점검 가이드만).
- [ ] **Step 4: 빈 질문** — `@BMS봇`(질문 없이) → "질문을 함께 적어 멘션해 주세요" 회신. (Activepieces에서 빈 query면 FastAPI 422 → 분기 회신, 또는 트리거 단계 가드.)

---

## 완료 기준
- `pytest tests/` 6/6 통과, `answer_eval.py` 12/12 유지.
- Slack 멘션 → 스레드 회신 E2E 3종(grounded/no_basis/제어지시 차단) 통과.
- 코드 변경: `scripts/slack_format.py`, `scripts/rag_api.py`, `tests/*` 신규. `rag_answer.py` 무수정.
