# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

BMS 공조(HVAC) RAG 지능형 모니터링 POC. 상세는 아래 문서로 — 이 파일은 **인덱스 + Rule**만 담는다.

## 문서 인덱스 (작업 전 필독 순서)
- **[HANDOFF.md](HANDOFF.md)** — 현재 구현 현황표 + 실행법 + 다음 단계. **여기부터 읽고, 마일스톤마다 갱신**.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — 설계 "어떻게/왜", 5층 구조, 데이터모델(4테이블), 결정 원장(CEO 11 + Eng 7), 안전 가드.
- [README.md](README.md) — 진입점, 빠른 시작, 저장소 구조.
- [docs/BMS_RAG_POC_PRD.md](docs/BMS_RAG_POC_PRD.md) — 제품 요구/범위/성공기준.
- [docs/plans/](docs/plans/) · [docs/specs/](docs/specs/) — 기능별 구현계획·설계 spec(날짜별).
- [TODOS.md](TODOS.md) — 의도적 연기 항목(P2/P3).

## 소스 인덱스
- `scripts/rag_index.py` — 문서 청킹(`##` 섹션)→임베딩→Supabase 적재 + 시나리오 검증.
- `scripts/rag_eval.py` — 검색 eval(recall@3·threshold 스윕·모델 분리 판정).
- `scripts/rag_answer.py` — **답변 파이프라인 + 사후 가드 5종(핵심).** CLI·API·eval 공용 `answer()`.
- `scripts/answer_eval.py` — 답변 eval(가드 불변식 회귀, 12케이스).
- `scripts/rag_api.py` — FastAPI 래퍼(`POST /answer`+토큰, `GET /health`). `rag_answer`·`slack_format` import만.
- `scripts/slack_format.py` — 답변 dict→Slack 마크다운(순수 함수).
- `scripts/validate_catalog.py` — `fault_catalog` ↔ `raw_logs` 스키마 계약 드리프트 검증.
- `scripts/rag_smoke.py` · `rag_chunked.py` — 초기 검색 감각 데모(통문서 vs 청크 비교).
- `catalog/fault_catalog.yaml` — 고장 시그니처 SoT(시뮬레이터 T6 + 감지기 T8 공유).
- `eval/retrieval_eval.yaml`(14) · `eval/answer_eval.yaml`(12) — eval 케이스.
- `tests/` — pytest(`test_slack_format` 3 + `test_rag_api` 5). `conftest.py`가 `scripts/`를 sys.path에 추가.

## 명령 (Windows PowerShell)
```powershell
# 의존성
$env:PYTHONPATH=""; .venv\Scripts\python.exe -m pip install -r requirements.txt
# 인덱싱 / 검색·답변 eval / 카탈로그 검증
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_index.py
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_eval.py        # 검색
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\answer_eval.py     # 답변(OpenAI 비용)
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\validate_catalog.py
# 테스트(전체 / 단일)
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pytest tests\
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pytest tests\test_rag_api.py::test_health
# API 서버(Slack 봇 백엔드)
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_api.py         # uvicorn :8000
```
빌드·린트 단계 없음(스크립트 + pytest 기반).

## Rules (엄수)
1. **Python 실행**: 항상 `$env:PYTHONPATH=""` + `-s`. 전역 PYTHONPATH가 VLibras를 가리켜 venv 의존성을 건너뛴다.
2. **`rag_answer.py` 무수정**: flow3/API는 import만. 변경하면 answer_eval 12/12 불변 보장이 깨진다. 회귀 게이트 = `pytest` 8 + 필요 시 `answer_eval` 12.
3. **시크릿**: `.env`만(공개 repo, 커밋 금지). 공개되는 건 `.env.example`. push 전 `git diff --cached --name-only` 확인. **`git add -A` 금지** — 의도한 파일만 add.
4. **커밋**: 신원은 repo-local `hyunia69@gmail.com`(전역 회사메일 쓰지 말 것). 커밋·push는 사용자가 요청할 때만.
5. **스키마 변경**: Supabase **마이그레이션 파일**로(대시보드 클릭 금지). seed·eval·threshold config도 버전관리.
6. **Supabase 접근**: 스코프 MCP(`mcp__supabase__*`)가 삭제된 엉뚱한 프로젝트를 가리킨다 → **관리(비스코프) 서버에 `project_id` 명시**(실제 ref는 `.env`의 `SUPABASE_URL`).
7. **한글 HTTP 테스트**: httpx `json=` 또는 UTF-8 파일(`curl -d @file`). 명령줄 한글/큰따옴표는 깨진다.
8. **임베딩**: `text-embedding-3-large` @ **1536d 고정**. 모델 교체 시 차원 유지 → DB 마이그레이션 없이 재인덱싱만.
9. **상태 추적**: 마일스톤마다 `HANDOFF.md` 구현 현황표 갱신 + 커밋(= 로컬 checkpoint의 git판).
10. **언어**: 문서·주석·커밋 메시지·응답 한국어.
