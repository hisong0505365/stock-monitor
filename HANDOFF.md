# 인수인계 — 감사보고서 파싱 · 기업신용평가

> 다른 세션·다른 PC 에서 이어받을 때 **이 문서를 먼저 전부 읽을 것.**
> 작성: 2026-09-28 (클라우드 세션 → 로컬 PC 이관) · 갱신: 2026-09-28 (PR #2 main 병합).
> 규칙은 `AGENTS.md`, 수치 근거는 `docs/`.

## 1. 무엇을 만들고 있나

사용자 목표: "전자공시시스템의 감사보고서·사업보고서·반기·분기보고서를 파싱해서 기업평가 프로그램을
만들고, **매출채권 대시보드(ar-dashboard)에 기업신용평가 메뉴**를 붙인다 — 폴더에 감사보고서를 넣으면
폴더의 기업과 회사 거래처를 매칭해 신용평가 자료를 시각화."

```
감사보고서 PDF 폴더 (로컬 PC, audit_reports\)
  → stock-monitor  disclosure_parser.py   PDF → 재무제표 · 감사의견 · 업종 · 비율 · 항등식 검증
  → stock-monitor  credit_export/          5축 스코어카드 · DART 고유번호 · 거래처 이름 매칭
  → Supabase 0008 테이블 (dart_companies · dart_evaluations · dart_partner_links, service_role upsert)
  → ar-dashboard   기업신용평가 탭          anon key + RLS 로 읽기만 (관리자 전용 초안)
```

## 2. 지금 상태 (2026-09-28)

### stock-monitor — **main 에 병합 완료** (PR #2, 2026-09-28, 병합 커밋 `6c73a93`)

| 커밋 | 내용 |
|---|---|
| 1차 | PDF 구조 분석, 파서, 정확도 검증기, 정답표 4건 |
| 2차 | `credit_export` 대시보드 연동 + 실제 PostgreSQL 적재 검증으로 10건 수정 |
| 3차 `513cc31` | 감사보고서 5건 추가 검증, OCR 개선, 자본잠식 비율 수정 |
| `de015a8` | 로컬 PC 이관용 안내(`AGENTS.md` · `CLAUDE.md` · `HANDOFF.md` · `requirements-dev.txt`) |
| `04add7d` · `034b99e` | 먼저 병합된 PR #1(`pharmacy_finder/`)을 받아 합침 — 충돌 없음, `AGENTS.md` 에 구성 추가 |

- main 에는 PR #1 로 들어온 **병원 근처 약국 찾기 앱(`pharmacy_finder/`)** 도 있다. 별도 앱이고 규칙은
  `pharmacy_finder/CLAUDE.md`, 테스트는 그 폴더에서(`python -m pytest`, 32개).
- 감사보고서 테스트 143개 통과(PDF·DB·Tesseract 모두 있을 때, 병합 직전 main 과 합친 상태로 확인).
  없으면 111 통과 / 32 건너뜀.
- **로컬 PC(`C:\dev\stock-monitor`)에서도 확인**(2026-09-28): 138 통과 / 2 건너뜀 — psycopg 가 없어
  DB 통합 테스트, Tesseract 가 없어 OCR 테스트가 건너뜀. 나머지(정답표·구조 포함)는 모두 통과.
- 정답표 9개사 240값 일치, 구조 2,681칸 일치, 회계 항등식 129개 통과.
- OCR 숫자 2,681 / 2,681 (텍스트 레이어 없이 열 배치까지 OCR 로 찾는 조건 포함), 계정명 84.8%.

9개사 평가(초안 스코어카드):

| 회사 | 결산 | 업종(주석) | 점수 | 등급 | 비고 |
|---|---|---|---|---|---|
| 동원약품 | 2025-12 | 도매 | 91.6 | AAA | |
| 지오영 | 2025-12 | 도매 | 87.2 | AA | |
| 알보젠코리아 | 2025-12 | 제조 | 84.5 | AA | |
| 복산나이스 | 2025-12 | 도매 | 81.7 | AA | |
| 인천약품 | 2025-12 | 도매 | 77.7 | A | |
| 아주약품 | 2026-03 | 제조 | 67.5 | BBB | 전기 28일(물적분할) → 성장성 제외 |
| 백제약품 | 2025-12 | 도매 | 64.8 | BBB | |
| 티제이팜 | 2025-12 | 도매 | 64.7 | BBB | |
| 경동사 | 2025-12 | 도매 | 18.8 | C | 완전자본잠식(자본 −42억) |

### ar-dashboard — 브랜치 `claude/company-credit-menu` (main 미병합, **push = 배포라 main 은 손대지 않음**)

| 커밋 | 내용 |
|---|---|
| `82b60c5` | 기업신용평가 메뉴 초안 — `UNDER_DEVELOPMENT` 의 `companyCredit` (관리자 전용) |
| `5d35ac9` | credit_export 출력 모양 호환 테스트 |
| `7a373c4` | jsonb 키 순서 복원, 감사 정보를 헤더로 (실제 DB 적재 검증 반영) |

- 기능 문서: ar-dashboard `docs/credit/README.md`. DB 마이그레이션 변경 없음(0008 그대로 읽음).
- `lib/credit/__tests__/model.test.ts` 35개.
- ar-dashboard 의 `PROJECT_STATUS.md`·`HANDOFF.md` 에는 아직 이 작업이 적혀 있지 않다 —
  로컬 main 의 미push 커밋과 충돌하지 않게 일부러 건드리지 않았다. 병합할 때 함께 갱신할 것.

## 3. 다음 할 일 (우선순위 순)

1. ~~PR #2 검토 · 병합~~ — 2026-09-28 완료.
2. **ar-dashboard 기능 브랜치 로컬 확인** → `npm test` · `npm run dev` 로 화면 확인 → main 병합·배포는
   사용자 결정.
3. **실제 Supabase 에 첫 적재.** 클라우드 세션에서는 Supabase 키가 없어 연결하지 않았고, DART·OpenDART 는
   네트워크 정책으로 막혀(403) 못 불렀다 — ar-dashboard 마이그레이션을 적용한 로컬 PostgreSQL 로만 검증했다.
   - `.env` 에 `SUPABASE_URL` · `SUPABASE_SERVICE_ROLE_KEY` (+ 선택 `OPENDART_API_KEY`)
   - 9개사의 **실제 DART 고유번호**가 필요하다(테스트는 가짜 번호 `001000xx` 사용).
     OpenDART 키가 없으면 `--corp-map corp_map.csv` (`name,corp_code`).
   - 미리보기 → 결과 확인 → `--upload`. 명령은 `docs/credit_export.md` §2.
4. 스코어카드 기준값 검증 — 부도·연체 이력(ar-dashboard 채권 연령 데이터)과 대조해야 한다.
5. 아직 안 해 본 양식: 연결재무제표 · 사업보고서 · 반기·분기 검토보고서.
6. 실제 종이 스캔 PDF 가 생기면 OCR 재측정(`python parsing_accuracy.py 파일.pdf --ocr`).
   지금 수치는 DART PDF 를 깨끗하게 렌더링한 이미지 기준이다.
7. 주석 구조화(차입금 명세 · 특수관계자 · 우발부채).

## 4. 함정 (모르면 다시 틀리는 것)

| 함정 | 내용 | 어디서 |
|---|---|---|
| OCR 하지 말 것 | DART PDF 는 텍스트 레이어가 있다. OCR 은 오히려 그럴듯한 오답(`3↔8`)을 만든다 | `docs/parsing_accuracy.md` |
| 같은 이름 계정 | 알보젠 `차입부채` 가 유동·비유동에 둘 다 → `구간:계정` 으로 매핑 | 파서 `BS_SECTIONS` |
| CAPEX 표기 | `취득`/`증가`, `건설중인자산`, `기타의유형자산` — 회사마다 다름 | `CAPEX_PATTERN` |
| 주석 참조 | `(주석17)` `(주석3과6)` `(주석3,4와6)` `(주7)` | `NOTE_REF` |
| 계속기업 판정 | '중요한 불확실성' 은 **모든** 보고서의 표준 문단에 있다 → 단락 제목·결론 문장으로만 | `audit_findings` |
| 자본잠식 | 부채비율이 음수가 되어 만점이 됐었다(경동사) | `compute_ratios` |
| 비슷한 이름 | `지오영경동` 은 지오영이 아닌 별개 법인 → 지역+지점 표기만 '유사' | `credit_export/matching.py` |
| jsonb 키 순서 | PostgreSQL jsonb 는 키 순서를 보존 안 함 → 대시보드가 고정 순서로 정렬 | ar-dashboard `lib/credit/model.ts` |
| RLS | anon 키로 조회하면 에러 없이 **0행** — '데이터 없음'으로 착각하기 쉽다 | ar-dashboard `CLAUDE.md` |
| Tesseract 병렬 | OpenMP 스레드 경합으로 수십 배 느려짐 → `OMP_THREAD_LIMIT=1` (코드에 고정) | `parsing_accuracy._TESS_ENV` |
| OCR 표 선 제거 | 픽셀 합 기준이면 정렬된 숫자 `1` 획이 지워진다 → 연속 길이 기준 | `_remove_table_lines` |

전체 이력은 `docs/verification_log.md` (1~3차).

## 5. 로컬(Windows) 환경

새 작업은 **main 에서 새 브랜치**를 만들어 PR 로 올린다. 병합된 브랜치
(`claude/pdf-ocr-parsing-disclosure-zo7zya`)에 이어 커밋하지 않는다. 저장소에 CI 는 없다 — PR 전에 로컬에서
테스트를 돌린다.

```powershell
cd C:\dev\stock-monitor
git switch main; git pull
py -3.11 -m venv .venv; .\.venv\Scripts\Activate.ps1      # Python 3.11 이상 (numpy 2.4)
pip install -r requirements.txt -r requirements-dev.txt
$env:AUDIT_PDF_DIR="audit_reports"; python -m pytest tests
```

- **Tesseract(OCR 할 때만):** UB Mannheim 빌드 설치 시 *Additional language data → Korean* 선택,
  설치 폴더(`C:\Program Files\Tesseract-OCR`)를 PATH 에 추가. 수치는 Tesseract 5.3.4(Ubuntu 패키지 데이터)
  기준이라 다른 빌드에선 조금 다를 수 있다 → `RUN_OCR_TESTS=1` 테스트로 확인.
- **DB 통합 테스트:** `tests/setup_test_db.sh` 는 Linux 용(PostgreSQL 16, `su postgres`) → WSL 에서 돌린다.
  또 이 테스트는 심볼릭 링크를 만들어 Windows 네이티브에선 개발자 모드가 필요하다.
- 감사보고서 PDF 는 `audit_reports\` (파일명은 `{정답표 접두어}_{회사}.pdf`, 테스트가 접두어로 찾는다).
