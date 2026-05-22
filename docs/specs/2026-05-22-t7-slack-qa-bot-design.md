---
title: T7 flow3 — Slack 자연어 Q&A 봇
date: 2026-05-22
status: 승인됨 (구현 계획 대기)
stage: 1단계 (안전한 작동 봇)
---

# T7 flow3 — Slack 자연어 Q&A 봇 (1단계)

## 목적
PRD 기능 6 / 시나리오 B. 운전원이 Slack에서 `@봇` 멘션으로 자연어 질문 →
BMS RAG 답변 엔진(T5 `rag_answer`)이 기술 문서 기반 답변을 **스레드로 회신**.
빌드 순서상 첫 "와" 데모.

## 핵심 설계 결정 (이력)
- **C 단계적** (D5): 1단계 = `rag_answer` 재사용한 안전한 작동 봇(가드·eval 유지).
  2단계 = Activepieces 3노드 가시화(결정5)는 이 토대 위에서 별도 진행.
  - 충돌 배경: 설계 원장 **결정5**(Activepieces에서 임베딩→검색→LLM 3노드 가시화)는
    2026-05-20, **T5 가드**(D4)는 2026-05-22. 가드가 `rag_answer.py` 단일 함수에 내장돼
    "펼치면 가드 손실(또는 TS 재구현·위험), 함수 쓰면 3노드 가시화 손실"의 충돌 발생.
- **A ngrok** (D6): 1단계 인프라 = ngrok 터널 + 로컬 FastAPI. 2단계에서 대체될
  임시 다리라 최소 노력 채택(클라우드 배포는 임시 인프라에 과투자).

## 아키텍처 (1단계)
```
[Slack 멘션 @봇 "질문"]
  → [Activepieces 클라우드: Slack 멘션 트리거]
  → [Activepieces: HTTP POST → ngrok 공개 URL]
  → [로컬 FastAPI: rag_answer.answer(query)]   # 가드·eval 그대로, 수정 없음
  → [Activepieces: dict → Slack 마크다운 → 원 메시지 스레드 회신]
```
**2단계 확장 경로:** 가운데 `[HTTP POST]` 노드를 `[임베딩]→[match_documents]→[LLM]→[가드]`로
펼쳐 결정5 가시화 달성. 1단계 FastAPI는 그때 "가드 검증" 엔드포인트로 축소(또는 유지).

## 컴포넌트
### 1. FastAPI 래퍼 (`scripts/rag_api.py`, 신규)
- `POST /answer` — 본문 `{"query": str}`, 응답 = `rag_answer.answer(query)` dict 그대로.
- 인증: 헤더의 공유 토큰(`.env`의 `RAG_API_TOKEN`)과 비교, 불일치 시 401.
- `GET /health` → 200.
- `rag_answer`는 import만 — **한 줄도 수정 없음**. uvicorn 로컬 실행(포트 8000).
- 실행 함정 유지: `$env:PYTHONPATH=""` + `-s`(전역 VLibras PYTHONPATH 회피), .env 로드.

### 2. Slack 앱
- 권한(scopes): `app_mentions:read`(멘션 이벤트 수신), `chat:write`(스레드 회신).
- Event Subscription URL은 Activepieces가 제공/흡수(결정5) — 노트북 공개 URL 불필요.

### 3. Activepieces flow (3스텝)
- **트리거**: Slack `app_mention` (또는 new message + 멘션 필터).
- **액션1 HTTP**: 멘션 텍스트에서 봇 ID 제거 후 질문 추출 → `POST {ngrok}/answer` + 토큰 헤더.
- **액션2 Slack**: `chat.postMessage`, `thread_ts` = 원 메시지 ts(스레드 회신), 본문 = 포맷된 마크다운.

### 4. ngrok
- 로컬 8000 → 공개 HTTPS. 무료 고정 도메인 1개 사용(재시작 시 URL 고정).

## 데이터 흐름
멘션 이벤트 → Activepieces 질문 추출 → `POST /answer {query}` + 토큰 →
FastAPI `answer()` → dict → Activepieces 마크다운 렌더 → 스레드 회신.

## Slack 메시지 포맷
**grounded:**
```
🔎 *요약*: {summary}

*원인 후보*
1. [{confidence}] {cause}
2. ...

*점검 체크리스트*
• {check}
• ...

*출처*
• {source} / {section} (유사도 {similarity:.2f}) ※POC 생성 문서
```
**no_basis:**
```
⚠️ 제공된 기술 문서에서 이 질문에 대한 충분한 근거를 찾지 못했습니다.

*확인해 보세요*
• {check}
• ...
```
제어지시는 `rag_answer` 가드가 차단하므로 Slack엔 점검 가이드만 노출(안전 보장).

## 에러 처리 & 보안
- **Slack 3초 ack / 중복 트리거**: Activepieces가 트리거 즉시 ack, 답변은 비동기 스레드 회신.
  (Activepieces 비동기 동작 셋업 시 확인.)
- **rag_answer 다운/타임아웃(30초+)**: HTTP 실패 → "지금 답변 엔진에 닿지 못했어요.
  잠시 후 다시 시도해 주세요" 스레드 회신.
- **인증 실패**: 토큰 불일치 → FastAPI 401 (ngrok URL은 공개라 필수).
- **빈 질문**(멘션만): "질문을 함께 적어 멘션해 주세요" 회신.

## 테스트
- **FastAPI 단위**: 로컬 `curl`로 grounded("냉매가 새는 것 같아요") / no_basis("오늘 점심 메뉴
  추천해줘") / control_bait("압축기를 어떻게 멈추나요") → dict 검증, 401(토큰 없음), 빈 query 처리.
- **회귀 게이트**: `answer_eval.py` 12/12 — 답변 엔진(`rag_answer`) 불변이므로 자동 유지.
- **Slack E2E(수동)**: 워크스페이스 멘션 → 스레드 회신 확인. 검증 시나리오 3종.

## 셋업 분담
- **사용자 직접**(계정·권한, 각 단계 가이드 제공): Slack 앱 생성 + 워크스페이스 설치 + 봇 토큰,
  Activepieces 클라우드 계정, ngrok 계정 + authtoken.
- **코드/구성**(담당): `scripts/rag_api.py`, Slack 메시지 포맷터, Activepieces flow 구성안 + 배선 가이드.

## 스코프 (1단계 명시적 제외)
- 기기 상태 결합 ❌ — `raw_logs` 빔(T6 미구현). 문서 기반 답변만. T6/T8 후 추가.
- 대화 맥락 유지 ❌ — 스레드 히스토리 미참조, 단발 Q&A.
- 2단계(Activepieces 3노드 가시화, 결정5) — 별도 spec.

## 성공 기준
- Slack에서 `@봇` 멘션 + 질문 → 30초 이내 스레드에 grounded/no_basis 답변.
- 검증 시나리오 3종 통과(냉매 누출 = grounded, 점심 = no_basis, 제어지시 = 가드 차단).
- `answer_eval.py` 12/12 유지.
