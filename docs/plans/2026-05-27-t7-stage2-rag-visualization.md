# T7 flow3 2단계 — RAG 가시화 학습 플로우 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 단, 이 plan은 **코드 산출물이 없다.** 대부분 Activepieces UI 수동 배선이라 사용자와 화면을 보며 진행한다(1단계 Task 5–7 패턴). subagent로 자동 실행되지 않는다.

**Goal:** Activepieces에 별도 학습 플로우(`임베딩 → match_documents → LLM`)를 배선해, 운전원 질의가 RAG 내부를 흐르는 과정을 캔버스에서 노드별로 관찰한다. 실제 봇·`rag_answer.py`·`answer_eval` 무손상.

**Architecture:** Webhook 트리거(query 입력) + HTTP 노드 3개(OpenAI 임베딩 · Supabase `match_documents` · OpenAI chat) + Code 노드 1개(검색 결과→프롬프트 조립). 각 노드는 `rag_answer.py`의 REST 호출과 1:1 대응. gate/가드/재생성/structured-output은 **의도적으로 제외**(실제 봇 몫 = 학습 경계). 실행은 Activepieces 편집기의 step별 "Test" 기능으로 수동 진행하며 각 노드 출력을 본다.

**Tech Stack:** Activepieces 클라우드(Webhook 트리거 · HTTP piece · Code piece). OpenAI REST(`/v1/embeddings`, `/v1/chat/completions`). Supabase PostgREST(`/rest/v1/rpc/match_documents`). 코드 변경 없음.

**준비물(전 Task 공통, `.env`에서 확인):**
- `OPENAI_API_KEY` — 노드 2·5
- `SUPABASE_URL` — 노드 3 (예: `https://<ref>.supabase.co`)
- `SUPABASE_SERVICE_ROLE_KEY` — 노드 3 (RLS상 anon 차단이므로 service_role 필요). **Activepieces Connection/Secret에 저장하고 참조** — 노드에 평문 입력 금지.

**Activepieces 표현식 노트:** 노드 간 값 전달은 Activepieces **데이터 선택기**로 이전 step의 필드를 삽입한다(아래 `{{…}}`는 그 결과 형태). step 이름은 표현식 식별자로 쓰이므로 영문(`embedding`/`search`/`assemble`/`llm`)으로 둔다.

---

## File Structure

이 plan은 **레포 코드 파일을 만들지 않는다.** 산출물은 Activepieces 플로우(클라우드) + 이 가이드 문서.

| 산출물 | 위치 | 역할 |
|---|---|---|
| 가시화 플로우 (5노드) | Activepieces 클라우드 (신규 flow) | 학습 관찰용. 실제 봇 flow와 별개 |
| 참조 코드 (불변) | `scripts/rag_answer.py` | 노드 ↔ 함수 대응의 SoT. **읽기만, 수정 금지** |
| 이 가이드 | `docs/plans/2026-05-27-t7-stage2-rag-visualization.md` | 배선 명세 |

**노드 ↔ `rag_answer.py` 대응:**
| 노드 | `rag_answer.py` |
|---|---|
| 2 임베딩 | `retrieve()` 임베딩부 ([rag_answer.py:124](../../scripts/rag_answer.py)) |
| 3 검색 | `retrieve()` RPC부 ([rag_answer.py:126](../../scripts/rag_answer.py)) |
| 4 조립 | `_build_user_msg()` ([rag_answer.py:154](../../scripts/rag_answer.py)) |
| 5 LLM | `generate()` ([rag_answer.py:173](../../scripts/rag_answer.py)) — 단 `response_format=Answer`·가드 제외 |

---

## Task 1: 사전 준비 (시크릿 + 검색함수 확인 + flow 생성)

**코드 아님. 계정·값 확인.** 함께 진행.

- [ ] **Step 1: `.env`에서 세 값 확인** — `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`가 채워져 있는지 확인. 1단계 봇이 동작했으므로 이미 존재.

- [ ] **Step 2: `match_documents` 존재·시그니처 확인(읽기 전용)**

이 플로우가 호출할 RPC가 T1에서 생성돼 있는지 확인. Supabase SQL Editor에서:
```sql
select proname, pg_get_function_arguments(oid)
from pg_proc where proname = 'match_documents';
```
Expected: 인자 `query_embedding vector, match_count int, filter jsonb`(또는 유사). `rag_answer.retrieve()`가 보내는 `{query_embedding, match_count, filter}`와 일치 확인.

- [ ] **Step 3: Activepieces 계정 + 새 flow** — https://cloud.activepieces.com 로그인(1단계에서 생성됨) → New Flow → 이름 `RAG 가시화 (학습용)`. **1단계 Slack 봇 flow와 별개로 생성**(실제 봇 무영향).

- [ ] **Step 4: 시크릿을 Connection/Secret으로 등록** — Activepieces에서 OpenAI 키, Supabase service_role 키를 직접 노드에 타이핑하지 말고 Connections(또는 flow 변수/Secret)로 등록해 참조한다. UI 경로는 화면을 보며 진행. (service_role은 RLS 우회 강력 키 — 평문 노출 방지가 보안 핵심.)

---

## Task 2: Webhook 트리거 (query 입력)

**목표:** 질문을 `{"query": "..."}` JSON으로 받아 플로우를 시작. 실제 봇 Slack 멘션 트리거와 무관(충돌 없음).

- [ ] **Step 1: 트리거 = Webhook(Catch Webhook)** — 트리거 검색에서 `Webhook`(Core) 선택. Activepieces가 고유 Webhook URL을 발급. (spec의 'Manual 트리거' = 이 Webhook을 자동 호출 없이 편집기 **Test**로 수동 실행하는 것 — '수동'은 트리거 종류가 아니라 운영 방식이다.)

- [ ] **Step 2: 샘플 데이터 등록** — 트리거 Test 단계에서 샘플 페이로드 입력(또는 한 번 실제 POST):
```json
{ "query": "냉매가 새는 것 같아요" }
```
이후 노드들이 `{{trigger.body.query}}`로 질문을 참조한다. (수동 실행 시 이 샘플을 바꿔 다른 질문 관찰.)

- [ ] **관찰 포인트:** 트리거 출력에 `body.query`가 보이는지 확인. 이게 파이프라인의 입력(= `rag_answer.answer(query)`의 `query`).

---

## Task 3: 노드 2 — HTTP 임베딩 (OpenAI)

**대응:** `rag_answer.retrieve()`의 `client.embeddings.create(model=…, dimensions=1536, input=[query])`.

- [ ] **Step 1: 액션 추가 = HTTP(Core)** — 이름 `embedding`.

- [ ] **Step 2: 설정 입력**
  - Method: `POST`
  - URL: `https://api.openai.com/v1/embeddings`
  - Headers:
    - `Authorization: Bearer <OPENAI_API_KEY 참조>`
    - `Content-Type: application/json`
  - Body (JSON):
```json
{
  "model": "text-embedding-3-large",
  "dimensions": 1536,
  "input": ["{{trigger.body.query}}"]
}
```

- [ ] **Step 3: Test step 실행** — 200 응답 확인.

- [ ] **관찰 포인트:** 응답 `data[0].embedding`이 **숫자 1536개 배열**인지 확인(차원 고정의 실증). 다음 노드 참조 경로 = `{{step_embedding.body.data[0].embedding}}`. ⚠️ `dimensions`를 빼면 3072가 나와 노드 3에서 차원 불일치로 실패한다 — 이 한 줄이 가드 5종만큼 중요한 계약(임베딩 컨벤션).

---

## Task 4: 노드 3 — HTTP 검색 (Supabase match_documents)

**대응:** `rag_answer.retrieve()`의 `http.post(f"{rest}/rpc/match_documents", json={query_embedding, match_count, filter})`.

- [ ] **Step 1: 액션 추가 = HTTP(Core)** — 이름 `search`.

- [ ] **Step 2: 설정 입력**
  - Method: `POST`
  - URL: `<SUPABASE_URL 참조>/rest/v1/rpc/match_documents`  (예: `https://<ref>.supabase.co/rest/v1/rpc/match_documents`)
  - Headers:
    - `apikey: <SUPABASE_SERVICE_ROLE_KEY 참조>`
    - `Authorization: Bearer <SUPABASE_SERVICE_ROLE_KEY 참조>`
    - `Content-Type: application/json`
  - Body (JSON):
```json
{
  "query_embedding": "{{step_embedding.body.data[0].embedding}}",
  "match_count": 5,
  "filter": {}
}
```
> `query_embedding`은 **숫자 배열**이 그대로 들어가야 한다. Body가 JSON 모드인지 확인 — 텍스트 모드면 배열이 문자열로 직렬화돼 RPC가 거부한다. 표현식이 배열로 평가되지 않으면 노드 2 출력 경로를 재확인.

- [ ] **Step 3: Test step 실행** — 200 + 청크 배열 응답 확인.

- [ ] **관찰 포인트:** 응답이 청크 배열 `[{content, metadata:{source,title,section}, similarity}, …]`(최대 5개). `similarity` 내림차순. 이게 "의미 검색"의 결과 — 키워드 매칭이 아니라 임베딩 거리순. 다음 노드 참조 = `{{step_search.body}}`.

---

## Task 5: 노드 4 — Code 조립 (검색 결과 → LLM 프롬프트)

**대응:** `rag_answer._build_user_msg(query, chunks, violations=None)`. chunk_id = 검색 반환 순서 인덱스.

- [ ] **Step 1: 액션 추가 = Code(Core)** — 이름 `assemble`.

- [ ] **Step 2: 입력(inputs) 두 개 정의** — Code piece UI의 입력 항목에:
  - `query` = `{{trigger.body.query}}`
  - `chunks` = `{{step_search.body}}`

- [ ] **Step 3: 코드 입력(JS 전문 — 그대로 붙여넣기)**
```javascript
export const code = async (inputs) => {
  const query = inputs.query || '';
  const chunks = Array.isArray(inputs.chunks) ? inputs.chunks : [];
  const lines = [`[질문]\n${query}\n`, '[근거 문서]'];
  chunks.forEach((h, i) => {
    const md = h.metadata || {};
    const sim = (typeof h.similarity === 'number' ? h.similarity : 0).toFixed(3);
    lines.push(
      `--- chunk_id=${i} | source=${md.source || '?'} | section=${md.section || '?'} | similarity=${sim} ---\n${h.content || ''}`
    );
  });
  return { user_message: lines.join('\n') };
};
```

- [ ] **Step 4: Test step 실행** — `user_message` 문자열 출력 확인.

- [ ] **관찰 포인트:** 출력 `user_message`가 `[질문]…[근거 문서] --- chunk_id=0 | source=… ---` 형태인지 확인. 이게 LLM에 실제로 들어가는 맥락 — "검색된 청크가 어떻게 프롬프트로 변신하는가"가 보인다. `rag_answer._build_user_msg`가 코드 안에서 하던 일과 동일. 다음 참조 = `{{step_assemble.user_message}}`.

---

## Task 6: 노드 5 — HTTP LLM (OpenAI chat)

**대응:** `rag_answer.generate()`. 단 학습 가시화라 `response_format`(structured output)·가드·재생성은 **제외** — 자연어 답변.

- [ ] **Step 1: 액션 추가 = HTTP(Core)** — 이름 `llm`.

- [ ] **Step 2: 설정 입력**
  - Method: `POST`
  - URL: `https://api.openai.com/v1/chat/completions`
  - Headers:
    - `Authorization: Bearer <OPENAI_API_KEY 참조>`
    - `Content-Type: application/json`
  - Body (JSON):
```json
{
  "model": "gpt-4o",
  "temperature": 0,
  "messages": [
    { "role": "system", "content": "당신은 공장 빌딩 HVAC(공조) 모니터링 보조자다. 아래 '근거 문서'만을 사용해 한국어로 답한다.\n\n규칙(엄수):\n- 근거 문서에 없는 사실을 지어내지 않는다. 모든 주장은 근거 문서에 기반해야 한다.\n- 답변에 근거가 된 청크 번호(chunk_id)를 함께 밝힌다. 제공된 번호만 사용한다.\n- 원인 후보는 최대 3개, 가능성 높은 순으로 제시한다.\n- 절대 기기 작동(제어) 지시를 하지 않는다: 기동/정지/켜기/끄기/밸브 개폐/설정값(설정온도·압력) 변경/주파수·인버터·rpm 조정/차단기·전원 조작/리셋 등 금지. 너는 '점검·확인' 가이드만 제시한다(예: \"필터 차압을 점검하세요\", \"냉매 압력 추세를 확인하세요\"). 정비 행위 설명은 가능하나 운전 제어 지시는 금지.\n- 근거 문서가 질문과 무관하거나 부족하면 '제공된 문서에서 충분한 근거를 찾지 못했다'고 밝히고 원인 추정 없이 일반 확인 항목만 제시한다." },
    { "role": "user", "content": "{{step_assemble.user_message}}" }
  ]
}
```
> SYSTEM은 `rag_answer.SYSTEM`([rag_answer.py:81](../../scripts/rag_answer.py)) 기반. 차이는 단 하나 — 실제 봇은 structured-output(`answer_type`/`citations` JSON 필드)을 강제하지만, 학습 노드는 자연어 답변이라 마지막 두 규칙만 자연어로 풀어 썼다. **환각 금지·제어지시 금지·원인 최대 3개**는 동일.

- [ ] **Step 3: Test step 실행** — 200 + 답변 확인.

- [ ] **관찰 포인트:** 응답 `choices[0].message.content`가 근거 문서 기반 한국어 답변인지, **제어 지시(기동/정지 등)가 없는지** 확인. 단 여기엔 가드가 없다 — LLM이 규칙을 어겨도 막아줄 사후 검증이 없음을 직접 본다(실제 봇은 `guard()`가 2차 방어). 이 대비가 "왜 가드가 별도로 필요한가"의 학습 포인트.

---

## Task 7: 실행 + 검증 (가시화가 "같은 RAG"임을 실증)

**사전:** 노드 2~5 각 Test 통과.

- [ ] **Step 1: 전체 흐름 수동 실행** — 트리거 샘플 `{"query":"냉매가 새는 것 같아요"}`로 노드 2→3→4→5 순차 Test. 각 노드 클릭해 입·출력 확인(임베딩 1536 → 청크+유사도 → 프롬프트 → 답변).

- [ ] **Step 2: `rag_answer.py` CLI로 대조 기준 생성**

Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s scripts\rag_answer.py "냉매가 새는 것 같아요"`
Expected: `answer_type: grounded` + "출처"에 청크별 유사도 표시(예: `E-3002… (유사도 0.4xx)`).

- [ ] **Step 3: 유사도 대조** — Activepieces 노드 3 응답의 청크 중, CLI "출처"에도 나온 **동일 청크(source/section 같은 것)의 `similarity`가 일치**하는지 비교. 일치하면 같은 임베딩·같은 검색을 한다는 실증(차원·모델·RPC가 코드와 동일). 불일치 시: 노드 2 `dimensions:1536` 누락 또는 `model` 오타 의심.

- [ ] **Step 4: no_basis 감각 확인(선택)** — 트리거 query를 `"오늘 점심 메뉴 추천해줘"`로 바꿔 실행 → 노드 3 검색 청크의 `similarity`가 낮게(무관 문서) 나오는지 관찰. 실제 봇은 여기서 `gate()`가 threshold로 잘라 `no_basis` 처리하지만, 학습 플로우는 gate가 없어 낮은 유사도 청크도 그대로 LLM에 전달됨 → "threshold gate가 왜 필요한가"가 보인다.

- [ ] **Step 5: 무영향 확인** — 코드 변경이 없으므로 회귀 게이트는 자동 유지. 불안하면:
  Run: `$env:PYTHONPATH=""; .venv\Scripts\python.exe -s -m pytest tests\`
  Expected: 8 passed (rag_answer·rag_api 불변).

---

## 완료 기준
- Activepieces 학습 flow에서 query 투입 → 노드 2~5 순차 Test 성공, **각 노드 입·출력이 캔버스에서 관찰**됨(임베딩 1536 / 검색 청크+유사도 / 조립 프롬프트 / LLM 답변).
- 노드 3 검색 유사도가 `rag_answer.py` CLI "출처"의 동일 청크 유사도와 **일치**(같은 RAG 실증).
- 학습 경계 관찰됨: 가드 없음(노드 5)·gate 없음(no_basis 케이스)을 실제 봇과 대비해 이해.
- 코드 변경 0 — `rag_answer.py`·`answer_eval` 12/12·`pytest` 8/8 무손상(자동).
- `HANDOFF.md` 구현 현황표에 "T7 2단계 가시화" 행 추가(마일스톤 갱신, Rule 9).
