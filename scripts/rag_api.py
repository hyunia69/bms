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
    try:
        res = rag_answer.answer(query)
    except SystemExit as e:  # rag_answer 가 env 누락 시 sys.exit → uvicorn 워커 사망 방지
        raise HTTPException(status_code=503, detail="RAG engine not configured (missing env vars)") from e
    res["slack_text"] = slack_format.format_slack(res)
    return res


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
