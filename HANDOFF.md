# HANDOFF — 현재 상태 & 재개 가이드

> git에 따라오는 **살아있는 상태 문서**. 로컬 `~/.gstack/` checkpoint(clone에 안 따라옴)의 git판.
> **매 마일스톤에 아래 "구현 현황" 표를 갱신하고 커밋**하면, 이 파일의 git 로그가 곧 진척 이력이 된다.
> 설계 근거 = [ARCHITECTURE.md](ARCHITECTURE.md) · 제품 요구 = [docs/BMS_RAG_POC_PRD.md](docs/BMS_RAG_POC_PRD.md).

**Last updated:** 2026-05-27 · **Branch:** main

## 현재 상태
Phase-1의 **"pull"(운전원 질의 = 시나리오 B)** 경로가 코드부터 실제 Slack 왕복까지 완료. RAG 코어(스키마·인덱싱·검색 eval·답변 가드)와 Slack Q&A 봇(flow3)이 동작한다. 남은 Phase-1은 **"push"(자동 감지·알림 = 시나리오 A·C)** = 로그 시뮬레이터(T6) + 감지·알림(T8) + 주기 요약(T9). `rag_answer.py`는 처음부터 무수정 유지.

## 구현 현황 (설계 범위 대비)
빌드 순서 기준. 상태는 커밋·eval·테스트 **증거로** 뒷받침한다(느낌 아님).

| 작업 | 내용 | 상태 | 근거 |
|---|---|---|---|
| T1 | Supabase 스키마(4테이블 + `match_documents` + RLS + D5/D7 인덱스 + FK) | ✅ 완료 | 마이그레이션 2건 |
| T2 | 고장 카탈로그 SoT(`catalog/fault_catalog.yaml`) | ✅ 완료 | `validate_catalog.py` 통과 |
| T3 | RAG 인덱싱(7문서 → 37청크) | ✅ 완료 | `rag_index.py`, rag_documents 37행 |
| T4 | 검색 eval(threshold·임베딩 모델 확정) | ✅ 완료 | `rag_eval.py` recall 100% |
| T5 | 답변 가드 5종 | ✅ 완료 | `answer_eval.py` 12/12 |
| T7 | flow3 Slack Q&A 봇 | ✅ 완료 | `pytest` 8/8 + 실제 Slack E2E |
| T6 | 로그 시뮬레이터(상관 고장 → raw_logs) | ⬜ 미착수 | raw_logs 0행 |
| T8 | flow1 감지·알림(시나리오 A) | ⬜ 미착수 | incidents 0행 |
| T9 | flow2 주기 요약·트렌드 | ⬜ 미착수 | analysis_results 0행 |
| T10/T11 | phase2(완전 상태머신·비용캡·메타데이터·자격증명 하드닝) | ⏸ 연기 | 설계상 의도된 phase2 |

**Phase-1 진척: 6/9** (T1–T5, T7).

## 설계 성공기준 체크
- ✅ 키워드 없이 의미 검색 Top-3 (T4, recall 100%)
- ✅ Slack 자연어 질문 → 답변 30초 이내 (T7)
- ✅ 검증 시나리오 검색: "냉매 누출 / 필터 교체 / 급기온도·계절운전" (T3·T4)
- ⬜ 시뮬레이터가 현실적 상관 고장 로그 생성 (T6)
- ⬜ 에러 시 Slack 원인분석 알림 (T8 / flow1)
- ⬜ 복합 패턴(시나리오 C): 다기기 상관 → 근본 원인 추론 (T8 감지 필요)

## 실행 방법
> ⚠️ Python 실행 전 항상 `$env:PYTHONPATH=""`(전역 VLibras 회피) + `-s`. 한글 HTTP 테스트는 httpx `json=` 또는 UTF-8 파일로(명령줄 한글/큰따옴표 깨짐).

```powershell
# 0. .env 준비 (.env.example 복사 → 키 채우기: OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, RAG_API_TOKEN)
# 1. 인덱싱(최초/문서 변경 시)
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_index.py
# 2. 게이트(현황 자동 probe)
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_eval.py        # 검색 recall/threshold
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\answer_eval.py     # 답변 가드 12/12 (OpenAI 비용 발생)
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\validate_catalog.py
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pytest tests\           # 8 passed
# 3. API 서버(Slack 봇 백엔드)
$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_api.py         # uvicorn :8000
```
- **Slack 봇 유지**: 봇 백엔드 = 로컬 FastAPI(:8000) + ngrok 터널. 둘 다 떠 있어야 응답한다(세션 종료 시 백그라운드 서버는 내려갈 수 있음 → 일반 터미널/서비스로 상주).
- ngrok 고정도메인·토큰 등 실제 값은 로컬 `.env` + 비공개 노트에만(공개 repo에 미기재).

## 핵심 불변 규율
- **`rag_answer.py` 무수정** — flow3·API는 import만. answer_eval 12/12가 수학적으로 유지된다. 회귀 게이트 = `pytest` 8 + 필요 시 `answer_eval` 12.
- 스키마 변경은 **마이그레이션 파일**로(대시보드 클릭 금지). seed·eval·threshold도 버전관리.

## 다음 단계 (3 후보)
1. **T7 2단계 — Activepieces 3노드 가시화**: flow의 단일 HTTP 노드를 임베딩 → `match_documents` → LLM → 가드로 펼쳐 RAG 내부 가시화(결정5). 가드가 단일 함수 내장이라 가시화/재구현 설계 필요.
2. **T6 → T8 자동 감지(flow1, 시나리오 A)**: 시뮬레이터(상관 고장 → raw_logs) → 센서 추세 감지기 → incidents → 자동 Slack 알림. SoT = `fault_catalog.yaml`(준비됨). 신규 코드량 가장 큼.
3. **보류 TODOS**: #22 실패 주입 테스트, #25 비RAG baseline 비교, 자격증명 하드닝.

## 로컬 전용 히스토리 (참고)
세션별 상세 결정·learnings는 `~/.gstack/projects/bms/`(checkpoints·timeline·learnings)에 있으나 **이 머신 로컬 전용**. 핵심은 ARCHITECTURE.md(결정)·이 문서(상태)로 git에 끌어왔다.
