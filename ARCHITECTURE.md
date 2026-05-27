# ARCHITECTURE — BMS 공조 RAG 지능형 모니터링 POC

> 설계의 **"어떻게 / 왜"** 를 git에 담는 단일 원장. 최초 설계 `/office-hours`(2026-05-20),
> 결정 확정 `/plan-ceo-review`(2026-05-21, HOLD SCOPE) · `/plan-eng-review`(2026-05-22).
> 원래 그 산출물은 로컬(`~/.gstack/projects/bms/`)에만 있어 clone에 안 따라왔다 → 이 문서로 통합.
> 제품 요구 = [docs/BMS_RAG_POC_PRD.md](docs/BMS_RAG_POC_PRD.md) · 현재 구현 상태 = [HANDOFF.md](HANDOFF.md).
> (아래는 **as-built** 기준. 설계 당시 가정과 다른 부분은 §7·§9에 사유와 함께 표기.)

## 1. 목적 — 두 겹의 목표
- **주(主): 학습** — RAG·자동화·벡터DB 생태계가 어떻게 연결되는지 이해. 현재 학습 단계 = "전체 생태계 이해"라,
  RAG 내부를 손으로 구현하기보다 **완성된 서비스/모듈을 조립**한다(접근 C′).
- **부(副): POC 기술검증** — 그래도 "RAG로 HVAC 모니터링이 실제로 된다"를 입증하는 수준까지 도달한다.

## 2. 접근 C′ — 생태계 우선 조립
Activepieces(오케스트레이션) + Supabase(저장·벡터) + 관리형 임베딩/LLM. 직접 작성 코드는 **시뮬레이터 하나로 최소화**.
**핵심 규율: RAG를 블랙박스로 만들지 않는다** — 임베딩 → 벡터검색 → LLM 을 보이는 단계로 유지.
대안 A(from-scratch)·B(LangChain 등 프레임워크)는 학습 2단계로 보류. 한 조각이 막히면 그 조각만 A/B로 바꿔 끼운다.

## 3. 5층 아키텍처 + 오케스트레이션
```
[1.생성]  시뮬레이터(Python, 메타데이터+상관고장) ──직접 insert──▶ raw_logs        ※ T6 미구현
[2.저장]  Supabase Postgres + pgvector (RLS on, service_role 서버측 only)
            raw_logs / incidents / analysis_results / rag_documents(vector 1536)
[3.감지]  규칙·임계·트렌드(RAG 없음) → 이상 → incidents 상태머신(dedup)            ※ T8 미구현
[4.설명]  RAG: 임베딩 → match_documents → LLM + 사후 가드(인용 필수·제어지시 0)     ※ T3~T5 구현 완료
[5.전달]  Slack 알림(push, 시나리오 A) ※flow1 / Slack Q&A(pull, 시나리오 B) ※flow3 구현 완료
```
- **감지층과 설명층은 분리.** RAG는 *감지*하지 않고 *설명*한다(가장 중요한 구조적 결정). 감지는 규칙/임계/트렌드.
- **시뮬레이터는 Activepieces 밖.** 자체 스케줄로 `raw_logs`에 직접 insert(별도 서버 불필요).

## 4. 3개 플로우
- **flow1 — 감지·알림** (Schedule 1~5분): 최근 `raw_logs` → 감지(임계·트렌드) → [이상] 하이브리드 검색 → LLM 원인·조치 → `analysis_results` 저장 → 수준 높으면 Slack. SLA "감지 후 1분"은 *이 플로우 1회 실행 완료* 기준. **(미구현)**
- **flow2 — 주기 요약·트렌드** (Schedule 1시간): incidents 기반 집계 + 이동평균 이탈. **(미구현)**
- **flow3 — Slack Q&A** (Slack 멘션 트리거): 질문 임베딩 → `match_documents` → LLM 답변 → 스레드 회신. **전제: Activepieces 클라우드**(자체호스팅 노트북은 Slack 이벤트 수신 불가). **(구현 완료 — 실제 Slack E2E 확인)**

## 5. 기술 스택 (as-built)
| 역할 | 선택 | 비고 |
|---|---|---|
| 오케스트레이션 | Activepieces 클라우드 | flow3의 하드 전제(Slack 이벤트 수신) |
| 저장·벡터 | Supabase Postgres + pgvector | 로그+분석+벡터 단일 DB, `match_documents` RPC |
| 임베딩 | OpenAI **`text-embedding-3-large` @ 1536d** | 설계는 small이었으나 T4에서 한글 변별력 부족 확인 → large 교체(§7) |
| LLM | **GPT-4o** (`chat.completions.parse` 구조화 출력) | `LLM_MODEL` env로 교체 가능 |
| API 다리 | FastAPI + uvicorn + ngrok 터널 | flow3 1단계 임시 인프라(2단계서 대체) |
| 시뮬레이터 | Python 독립 스크립트 | 상관 고장 주입, `raw_logs` 직접 insert (미구현) |
| Slack | Activepieces Slack piece | 멘션 트리거 + 스레드 회신 |
| 코드↔DB | httpx로 PostgREST 직접 호출 | supabase-py의 무거운 의존 체인 회피 |

## 6. 데이터 모델 (as-built — Supabase 검증)
전 테이블 **RLS on**, 정책 0개(= service_role 서버측 only). 마이그레이션 2건으로 버전관리.
- **`rag_documents`**: id, content(text), **metadata(jsonb)**=source/title/section/code/doc_type, **embedding(vector(1536))**, created_at. *현재 37행*(7문서×섹션청크). 설계의 개별 컬럼(title/doc_type 등) 대신 metadata jsonb로 단순화.
- **`raw_logs`**: id, collected_at, device_id, device_type, zone, status, error_code, **센서 9종**(temp_supply/return/outdoor, humidity, pressure, airflow, current, power, runtime_hours), message. *현재 0행(T6 후 적재)*.
- **`incidents`**: id, **fingerprint**, status(`open`/`escalated`/`resolved` CHECK), level, opened_at/escalated_at/resolved_at/last_alerted_at. 상태머신 + dedup(D5). *0행*.
- **`analysis_results`**: id, **incident_id → incidents.id (FK)**, period_start/end, device_summary(jsonb), anomalies(jsonb), ai_analysis, recommendations, alert_sent, alert_level. *0행*.
- 인덱스: D5 `incidents` 부분 유니크(fingerprint WHERE status in open/escalated → UPSERT 멱등), D7 `raw_logs(device_id, collected_at)` 복합.
- `match_documents(query_embedding, match_count, filter)` RPC = 코사인 Top-K 반환. **threshold 필터링은 앱(`rag_answer.gate()`)에서 strict→widen 2단계로** 적용(RPC는 컷오프 안 함).

## 7. RAG 설계 결정
- **청킹**: 문서를 `## ` 섹션 단위로 분할, 각 청크가 문서 제목 동반. (통문서 임베딩에선 냉매누출이 distractor에 밀렸으나 섹션 청킹 후 1위 역전.)
- **임베딩 모델 = large @1536**: small은 긍정/부정 분리 실패(gap −0.028, off-domain이 관련 문서보다 높게 뜸) → large는 분리 성립(gap +0.001). **차원 1536 고정**이라 모델 교체해도 DB 마이그레이션 없이 재인덱싱만.
- **threshold = strict 0.34 / widen 0.30**: 빌드 초기 설계값(후반 튜닝 아님, CEO T1). 분리 마진이 얇아(≈0.0006) 단일 컷오프로 완전 분리 불가 → **답변 가드(§8)가 2차 방어선**.
- **하이브리드 검색**(설계): 알려진 에러코드는 직접 조회 + 의미검색 Top-K 보강. (현재 flow3는 의미검색만, 코드 직접조회는 flow1에서.)

## 8. 안전 설계 — 사후 가드 (eng D4)
LLM 출력을 **신뢰하지 않고 검증**한다. `rag_answer.py`가 GPT-4o 구조화 출력 뒤 5종 가드를 돌린다:
1. **가짜 인용 0** — 존재하지 않는 chunk_id 인용 차단
2. **인용 100%** — grounded면 출처·근거 청크 필수
3. **제어지시 0** — 기동/정지/밸브·설정값 변경 등 *운전 작동 명령* 정규식 차단, '점검·확인' 가이드만 허용(운전원 안전)
4. **원인 후보 ≤ N**(기본 3)
5. **no_basis 일관성** — 근거없음인데 원인·인용이 있으면 위반

위반 시 **1회 재생성 → 그래도 위반이면 "근거없음"으로 강등**. 매칭 0건이면 LLM 호출 없이 근거없음(환각 0).
모든 grounded 답변에 **출처 인용**(제목+섹션+유사도+스니펫, CEO#8).

## 9. 핵심 결정 원장
### CEO 리뷰 (2026-05-21, HOLD SCOPE — 6기능/3플로우 유지, 방탄화)
| # | 결정 |
|---|---|
| 1 | 시뮬·감지·문서 = 하이브리드(시나리오-먼저 보장 생성 + 독립 임계규칙 + blind eval 케이스) |
| 2 | 빈 검색 → threshold 넓혀 재검색 → 0건이면 **"근거없음" 별도 응답 타입** + 체크리스트만. 제어지시·가짜인용 금지 |
| 3 | DB 보안 = RLS on + anon 정책 없음 + service_role 서버측만. AP 쓰기는 제한 RPC로(→ phase2) |
| 4 | 알림 dedup = incidents 상태머신(OPEN/ESCALATED/RESOLVED), 재알림 억제 |
| 5 | RAG 로직은 flow1·3 양쪽 다 3노드로 가시화 유지(의도된 DRY 예외 = 학습 가시화) |
| 6 | RAG 검증 = 반복 eval 세트(검색 Top-K + answer-level 가드 회귀) |
| 7 | 스키마 = 마이그레이션 파일(대시보드 클릭 금지). seed·eval·threshold도 버전관리 |
| 8 | 모든 grounded 답변에 출처(제목+청크+유사도+스니펫), 실제 매뉴얼 vs 생성 문서 구분 |
| T1 | corpus engineering + RAG강제 케이스 중심 eval + threshold를 빌드 초기 설계값으로 |
| T2 | incidents 상태 테이블 신설, analysis_results는 incident_id로 연결 |

### Eng 리뷰 (2026-05-22, FULL_REVIEW — 빌드 실행 기준)
| # | 결정 |
|---|---|
| D1 | 스키마 먼저, 거동 단계화(전 테이블 1차 마이그레이션, production 하드닝 phase2) |
| D2 | DB 자격증명 = service_role 직접(POC 속도). 가드레일 = throwaway 프로젝트 + 키 회전. 제한역할은 phase2 |
| D3 | 시뮬↔감지 = 단일 고장 카탈로그 SoT. 감지기는 센서패턴 매칭(주입로그 안 읽음 → 순환 eval 방지) |
| D4 | 출력 가드 = 구조화 출력 + 사후 검증기(§8), 위반 시 재생성→근거없음 |
| D5 | incident 멱등 = 부분 유니크 인덱스 + UPSERT(겹친 폴 중복 OPEN 방지) |
| D6 | 부정 eval = 노이즈→오탐 0 + 매칭없음→근거없음(환각 0) |
| D7 | 성능 = `raw_logs(device_id, collected_at)` 복합 인덱스 |

**Pass bar**: 검색=보장 시나리오 4개 Top-3 / answer=제어지시·가짜인용 0 + 인용 100% + 원인 ≤N / 부정=오탐 0 + 매칭없음→근거없음 100%.

## 10. 범위 — phase1 / phase2 / 보류
- **Phase 1**(빌드 순서): T1 스키마 → T2 카탈로그 → T3 인덱싱 → T4 검색 eval → T5 답변 가드 → **T7 flow3(와 순간)** → T6 시뮬 → T8 flow1 → T9 flow2.
- **Phase 2**(연기, 미삭제): 완전 incidents 상태머신 전이, 비용·쿼터·latency 상한(#23), 풍부한 BMS 메타데이터(#20), 제한역할+SECURITY DEFINER RPC 자격증명 하드닝(D2).
- **보류(TODOS.md)**: #22 실패 주입 테스트, #25 비RAG baseline 비교, 이벤트 기반 알림, Nice-to-Have(보고서·Notion·시각화·에너지 이상), HNSW 인덱스, AP 자체호스팅.
