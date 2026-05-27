---
title: T7 flow3 2단계 — RAG 가시화 학습 플로우
date: 2026-05-27
status: 승인됨 (구현 계획 대기)
stage: 2단계 (RAG 내부 가시화 — 학습용 별도 플로우)
---

# T7 flow3 2단계 — RAG 가시화 학습 플로우

## 목적
결정원장 **결정5**("RAG를 블랙박스로 만들지 않는다 — 임베딩→벡터검색→LLM을 보이는 단계로 유지")의 학습 가시화 달성.
Activepieces 캔버스에서 `임베딩 → match_documents → LLM` 단계를 각각의 노드로 펼쳐, 운전원 질의가
RAG 내부를 어떻게 흐르는지(임베딩 벡터·검색 청크·유사도·LLM 답변)를 **눈으로 관찰**한다.
1단계 "와" 데모(실제 Slack 봇)에 이은, RAG 이해를 위한 학습 단계.

## 핵심 설계 결정 (브레인스토밍 2026-05-27)
세 갈림길을 좁힌 결과 — 각 결정의 *왜*:

1. **별도 학습 플로우** (가시화 범위). 펼친 노드는 **실제 봇 경로가 아니다.** 실제 봇(flow3 1단계)·
   `rag_answer.py`·`answer_eval`은 한 줄도 손대지 않는다.
   - *왜*: 결정5(가시화, 2026-05-20)와 D4 가드(`rag_answer.py` 단일 함수 내장, 2026-05-22)의 시간차 충돌
     ("펼치면 가드 손실 또는 JS 재구현·위험, 함수 쓰면 가시화 손실")을 **정면으로 회피**. 별도 플로우로 두면
     가드는 `rag_answer.py`에만 남아 `answer_eval` 12/12·무수정 보장이 그대로 유지된다.
2. **수동 실행 + 캔버스 관찰** (실행 방식). Manual 트리거로 질문 입력 → Run → 각 노드 클릭해 입·출력 확인.
   - *왜*: 실제 봇 Slack 멘션 트리거와 물리적으로 분리(동시 응답 충돌 없음). 학습 목적엔 raw 중간 데이터를
     캔버스에서 보는 것이 핵심이라 가장 단순하고 직결. Slack 불필요.
3. **HTTP 노드로 통일** (노드 구현). 세 단계 모두 Activepieces HTTP 노드로 OpenAI·Supabase REST 직접 호출.
   - *왜*: `rag_answer.py`의 `retrieve()`·`generate()`가 하는 REST 호출과 1:1 대응 → "코드가 하는 일"을
     그대로 보는 학습 효과 최고. `dimensions=1536`·`match_count`·`filter`를 명시 제어해 **차원 불일치 위험 0**.
     네이티브 피스는 출력을 정제해 raw 벡터·페이로드가 덜 보이고, 임베딩 차원/RPC 지원이 버전별 불확실.
     결정원장의 "httpx로 PostgREST 직접 호출" 철학과도 일치.

## 아키텍처 (노드 그래프 ↔ `rag_answer.py` 대응)
```
[1. Manual 트리거]  query 입력  (예: "냉매가 새는 것 같아요")
       │  query
       ▼
[2. HTTP 임베딩]    POST api.openai.com/v1/embeddings              ↔ retrieve() 임베딩부
       │  → embedding[1536]
       ▼
[3. HTTP 검색]      POST {SUPABASE}/rest/v1/rpc/match_documents    ↔ retrieve() 검색부
       │  → chunks[] {content, metadata, similarity}
       ▼
[4. Code 조립]      청크 배열 → LLM 프롬프트 텍스트                ↔ _build_user_msg()
       │  → user_message
       ▼
[5. HTTP LLM]       POST api.openai.com/v1/chat/completions        ↔ generate() (가드·스키마 제외)
       │  → answer 텍스트
       ▼
[관찰 종료]  각 노드 클릭 → 입·출력 확인 (벡터 차원 / 검색 유사도 / LLM 답변)
```

## 노드별 명세
> 정확한 헤더/표현식 문법·SYSTEM 조정 전문·JS 전문은 **구현 계획(plan) 단계**에서 확정. 아래는 설계 골격.

| 노드 | 종류 | 핵심 설정 (골격) | 출력 참조 | `rag_answer.py` 대응 |
|---|---|---|---|---|
| 1 트리거 | Manual | 입력 필드 `query` (문자열) | `{{trigger.query}}` | CLI `argv` |
| 2 임베딩 | HTTP POST | `https://api.openai.com/v1/embeddings`<br>body `{model:"text-embedding-3-large", dimensions:1536, input:[query]}` | `{{step_2.body.data[0].embedding}}` (1536 float) | `retrieve()` 임베딩 |
| 3 검색 | HTTP POST | `{SUPABASE_URL}/rest/v1/rpc/match_documents`<br>body `{query_embedding:[…], match_count:5, filter:{}}` | `{{step_3.body}}` (청크 배열) | `retrieve()` RPC |
| 4 조립 | Code (JS) | 청크 배열 + query → `--- chunk_id=N \| source=… \| section=… \| similarity=… ---\n{content}` 텍스트 결합 | `{{step_4.user_message}}` | `_build_user_msg()` |
| 5 LLM | HTTP POST | `https://api.openai.com/v1/chat/completions`<br>body `{model:"gpt-4o", temperature:0, messages:[SYSTEM, user_message]}` | `{{step_5.body.choices[0].message.content}}` | `generate()` |

- **노드 2 → 3 전달**: 임베딩 벡터(1536 배열)를 검색 body의 `query_embedding`으로. HTTP body는 JSON 모드여야 배열이 직렬화됨.
- **노드 4 (Code)**: `chunk_id`는 검색 반환 순서 인덱스(`rag_answer`와 동일 안정 번호). `_build_user_msg()`의 violations 없는 버전.
- **노드 5 SYSTEM**: `rag_answer.SYSTEM`([rag_answer.py:81](../../scripts/rag_answer.py)) 재사용. 단 자연어 답변용이라
  structured-output 전제 문구(`answer_type`/`citations` 필드)만 자연어로 조정, 나머지 규칙(**환각 금지·제어지시 금지·근거 인용**)은 동일.

## 명시적 제외 (= 학습 경계, 의도된 설계)
가시화 플로우는 **happy path만** 보인다. 아래는 **펼치지 않고 실제 봇(`rag_answer.py`)에만 둔다** — 이 경계 자체가 학습 포인트("가시화 플로우는 흐름을 보고, 안전 검증은 실제 봇이 한다"):
- **threshold gate 분기** (`gate()`: strict→widen→none) — 가시화는 검색 Top-K를 그대로 LLM에 전달.
- **사후 가드 5종** (`guard()`: 가짜인용·인용100%·제어지시·원인후보≤N·no_basis 일관성).
- **위반 시 1회 재생성 루프**.
- **structured-output 스키마 강제** (`chat.completions.parse` + `Answer` 모델) — 노드 5는 자연어 답변.

## 인증·시크릿 (보안 주의)
- 노드 2·5 = `OPENAI_API_KEY`. 노드 3 = Supabase 키.
- `match_documents`는 RLS상 anon 차단(결정원장 보안 규칙)이라 **service_role 키** 필요.
- service_role은 RLS 우회 강력 키 → Activepieces 클라우드 SaaS 저장은 트레이드오프. 학습 플로우라 수용하되
  **Activepieces Connection/Secret으로만**(노드 평문 금지). 장기적으론 제한 RPC/별도 키(phase2 결정3) 연결.

## 검증 (가시화가 "진짜 같은 RAG"임을 증명)
- 동일 질문("냉매가 새는 것 같아요")을 `rag_answer.py` CLI와 이 플로우에 각각 투입 → 노드 3이 반환한 청크의 유사도가
  CLI "출처"에 표시된 **동일 청크의 유사도와 일치**(겹치는 청크 기준)하는지 확인 → 같은 임베딩·같은 검색임을 실증.
  노드 2 출력이 1536차원인지도 확인.
- LLM 출력은 `temperature=0`이라 거의 재현되나 스키마/가드 차이로 완전 동일은 아님 — 관찰용이라 수용.

## 산출물 & 분담 (1단계와 동일 패턴)
- **담당(코드/구성)**: 각 노드 정확한 설정 명세(URL·헤더·body 템플릿·노드 간 참조 표현식) + 노드 4 JS 전문 +
  SYSTEM 자연어 조정문 + 대응표·경계 설명 + 검증 절차 → **배선 가이드 문서**(plan 산출물).
- **사용자 직접(Activepieces UI)**: 플로우 생성·노드 추가·배선·Connection 키 등록·Run 실행·캔버스 관찰.

## 스코프 (명시적 제외)
- 실제 봇 경로 변경 ❌ — flow3 1단계·`rag_answer.py`·`answer_eval` 무손상.
- gate/guard/재생성/structured-output 가시화 ❌ — 위 "명시적 제외" 참조(실제 봇 몫).
- Slack 연동 ❌ — 수동 실행·캔버스 관찰만.

## 성공 기준
- Activepieces에서 질문 입력 → Run → 노드 2~5가 순차 실행되고, **각 노드 클릭 시 입·출력이 보인다**
  (임베딩 1536 벡터 / 검색 청크+유사도 / 조립 프롬프트 / LLM 답변).
- 노드 3 검색 결과의 유사도가 `rag_answer.py` CLI "출처"의 동일 청크 유사도와 **일치**(겹치는 청크 기준 → 같은 RAG 검색임을 실증).
- 실제 봇·`answer_eval` 12/12 무영향(코드 미변경이므로 자동 유지).
