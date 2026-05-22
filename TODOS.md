# BMS RAG POC — TODOS

CEO 리뷰(2026-05-21, HOLD SCOPE)에서 연기된 항목. 빌드 중/후 재검토.
설계문서: `~/.gstack/projects/bms/admin-unknown-design-20260520-155903.md` (CEO 리뷰 결정 원장 참조)

## P2

### #22 실패 주입 테스트 (failure injection)
- **What**: RPC 0건 · OpenAI timeout · Slack 전송 실패 · LLM JSON 깨짐 · 중복 이벤트를 일부러 주입해 rescue 경로를 능동 검증.
- **Why**: 학습 목표가 "생태계 이해"면 성공경로보다 실패경로가 더 중요. Section 2 에러맵이 *설계만* 됐고 검증은 안 됨 (CEO 리뷰의 유일한 DONE_WITH_CONCERNS).
- **Pros**: 관리형 조립의 실제 실패 거동 학습. 데모 중 외부 API 흔들려도 안 무너짐.
- **Cons**: 기본 플로우 동작 후라야 의미. 시간 듦.
- **Effort**: 사람 ~반나절 / CC ~20분. **Priority**: P2.
- **Depends on**: 3개 플로우 기본 동작.

### #25 비RAG baseline 비교
- **What**: 규칙감지 + 에러코드/증상 매핑표 + LLM요약 버전을 만들어 RAG 버전과 검색·답변 품질 비교 (codex #25/#17).
- **Why**: RAG가 단순 룩업을 못 이기면 벡터DB/RAG는 장식. "RAG가 가치 있다"를 *증명*하는 학습 핵심 질문.
- **Pros**: 과복잡 여부 판단 가능. 학습 가치 최고.
- **Cons**: 별도 트랙 = 진짜 스코프 확장.
- **Effort**: 사람 ~1~2일 / CC ~30~45분. **Priority**: P2.
- **Depends on**: RAG 코어 + eval 세트(결정6).

### 자격증명 하드닝 — 제한 역할 + SECURITY DEFINER RPC (eng 리뷰 D2)
- **What**: Activepieces가 service_role 대신 제한 Postgres 역할(또는 anon+RLS 정책)로 들어오고, match_documents·쓰기를 SECURITY DEFINER RPC로 감싸 최소권한화.
- **Why**: eng 리뷰 D2에서 POC 속도 위해 service_role 직접 사용을 택함 → AP 클라우드(제3자 SaaS)가 RLS 우회 마스터키 보유. 결정 #3(최소권한)의 진짜 구현이 미뤄짐.
- **Pros**: 마스터키가 제3자 SaaS 밖. 결정 #3 실현. "관리형 조립의 자격증명 토폴로지"가 학습 2단계로 연결.
- **Cons**: 역할·GRANT·SECURITY DEFINER 설정 한 겹. 기본 플로우 동작 후라야 의미.
- **임시 가드레일(빌드 중)**: throwaway Supabase 프로젝트 + 끝나면 service_role 키 회전/삭제로 폭발반경 제한.
- **Effort**: 사람 ~2시간 / CC ~15분. **Priority**: P2.
- **Depends on**: 3개 플로우 기본 동작. 1차 마이그레이션은 RLS on으로 이미 깔린 상태(그 위에 역할+RPC 권한만 추가).

## P3

- **이벤트 기반 알림**: 폴링(1~5분) 대신 실시간 트리거. 현 SLA 문구가 폴링 지연을 흡수 중. (codex #3)
- **풀 4-way 데이터모델**: incident_events / notifications 별도 테이블 분리. 현 incidents + analysis_results로 충분. (codex #12)
- **Nice-to-Have (PRD)**: 일간/주간 보고서 이메일, Notion 동기화, 임베딩 공간 시각화, 에너지 효율 이상 감지(에러 없는 전력 급증).
- **HNSW 인덱스**: 문서 수천+ 시 벡터검색 인덱스(현 수십 개는 풀스캔 OK).
- **RAG DRY 추출**: 3번째 RAG 소비 플로우 생기면 공유 검토. 현재는 가시화 우선 중복 유지(결정5).
- **Activepieces 자체호스팅**: stage-2 학습 과제(현 클라우드 전제, 플로우3 Slack 이벤트 수신 때문).
