# BMS 공조 RAG 지능형 모니터링 POC

공장 빌딩 HVAC(공조) 시스템의 기기 로그와 기술 문서를 **RAG**(검색 증강 생성)로 연결해,
이상 **감지 → 원인 분석 → 조치 가이드**까지 자동화가 가능한지 검증하는 POC.

> **목표 두 겹** — 주: RAG·자동화·벡터DB *생태계* 이해(완성 모듈 조립, 접근 C′) / 부: "RAG로 HVAC 모니터링이 된다"는 기술 검증.

## 무엇을 하나
- **의미 검색**: "냉매가 새는 것 같아요" 같은 평범한 한국어 → 키워드 매칭 없이 `E-3002`(냉매 누출) 문서를 찾아 LLM이 원인·조치를 설명.
- **안전한 답변**: 근거 문서가 없으면 "근거없음"으로 정직하게, 운전 *제어 지시*(기동/정지/밸브 등)는 절대 안 함 — 점검·확인 가이드만.
- **Slack Q&A 봇**(동작 중): Slack에서 `@봇` 멘션 → Activepieces → 로컬 RAG API → 스레드 회신.

## 문서 지도
| 문서 | 내용 |
|---|---|
| [docs/BMS_RAG_POC_PRD.md](docs/BMS_RAG_POC_PRD.md) | **왜/무엇** — 제품 요구, 범위, 성공 기준 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | **어떻게/왜** — 시스템 설계, 데이터 모델, 결정 원장(CEO·Eng 리뷰) |
| [HANDOFF.md](HANDOFF.md) | **지금** — 구현 현황표, 실행법, 다음 단계 (매 마일스톤 갱신) |
| [docs/plans/](docs/plans/) · [docs/specs/](docs/specs/) | 기능 단위 구현 계획·설계 spec (날짜별) |
| [TODOS.md](TODOS.md) | 의도적으로 연기한 항목(P2/P3) |

처음 받았다면 **ARCHITECTURE.md → HANDOFF.md** 순으로 읽으면 설계 의도와 현재 위치가 잡힙니다.

## 빠른 시작
```powershell
# 1. 의존성
python -m venv .venv
$env:PYTHONPATH=""; .venv\Scripts\python.exe -m pip install -r requirements.txt
# 2. 설정: .env.example → .env 복사 후 키 입력
#    OPENAI_API_KEY / SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / RAG_API_TOKEN
# 3. RAG 인덱싱 (문서 → 청크 → 임베딩 → Supabase 적재 + 시나리오 검증)
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_index.py
# 4. 답변 1회 (CLI)
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_answer.py "냉매가 새는 것 같아요"
# 5. API 서버 (Slack 봇 백엔드) + 테스트
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_api.py     # uvicorn :8000
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pytest tests\
```
> ⚠️ Python 실행 전 항상 `$env:PYTHONPATH=""`(전역 PYTHONPATH 충돌 회피) + `-s`. 자세한 게이트·함정은 [HANDOFF.md](HANDOFF.md).

## 기술 스택
Python 3 · Supabase Postgres + pgvector · OpenAI `text-embedding-3-large`(1536d) + GPT-4o(구조화 출력) ·
FastAPI + uvicorn · Pydantic · httpx(PostgREST) · PyYAML(eval·카탈로그) · Activepieces(클라우드) · Slack · ngrok.

## 저장소 구조
```
scripts/      RAG 파이프라인 — rag_index(인덱싱) · rag_eval(검색 eval) · rag_answer(답변+가드)
              answer_eval(답변 eval) · rag_api(FastAPI) · slack_format · validate_catalog
docs/         PRD · rag_sources(기술문서 7종) · plans · specs
catalog/      fault_catalog.yaml — 고장 시그니처 SoT(시뮬레이터+감지기 공유)
eval/         retrieval_eval.yaml(검색 14케이스) · answer_eval.yaml(답변 12케이스)
tests/        pytest (slack_format · rag_api)
```

## 상태
Phase-1의 RAG 코어 + Slack Q&A(pull)는 완료, 자동 감지·알림(push)은 진행 예정.
정확한 현황은 [HANDOFF.md](HANDOFF.md)의 구현 현황표 참조.

---
*POC · 비상업 학습 프로젝트. 시크릿은 `.env`로 분리(커밋 금지), `.env.example`만 공개.*
