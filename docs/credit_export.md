# 감사보고서 폴더 → 매출채권 대시보드 연동 (`credit_export`)

감사보고서 PDF 를 폴더에 넣고 한 번 실행하면, 파싱·검증·평가·거래처 매칭을 거쳐 매출채권
대시보드(ar-dashboard)의 Supabase 테이블에 올린다. 대시보드의 **기업신용평가** 메뉴
(`components/CompanyCreditView.tsx`)가 이 데이터를 그대로 읽는다 — 대시보드 쪽 코드 변경은 없다.

```
감사보고서 폴더 ─▶ disclosure_parser  (텍스트 레이어 표 추출 · 회계 항등식 검증)
                ─▶ scoring           (5축 스코어카드 → 점수 · AAA~D)
                ─▶ corp_codes        (DART 고유번호 확인 — 지어내지 않는다)
                ─▶ matching          (회사명 ↔ 거래처명)
                ─▶ supabase_rest     (dart_companies → dart_evaluations → dart_partner_links)
                                        │
ar-dashboard (Cloudflare) ◀── anon key + RLS 로 읽기 ─┘   기업신용평가 · 신용리스크 탭
```

이 구조는 ar-dashboard `supabase/migrations/0008_dart_evaluation.sql` 의 설계(파이썬 도구가
service_role 키로 쓰고, 대시보드는 읽기만)를 그대로 따른다. 기존 dart-analyzer 와 같은 테이블을
쓰므로 서로의 데이터를 덮지 않도록 보호 규칙을 둔다(아래).

## 1. 준비

```bash
pip install -r requirements.txt
```

`.env` (이 PC 에만 둔다 — **service_role 키는 RLS 를 우회하므로 절대 커밋하지 않는다**)

```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
OPENDART_API_KEY=...          # 선택. 없으면 --corp-map 또는 Supabase 기존 회사로만 고유번호를 찾는다
```

## 2. 실행

```bash
# ① 미리보기 (DB 에 쓰지 않음) — export_preview.json 과 요약 출력
python -m credit_export.export --folder ./audit_reports --org 1100 --org 1200 --org 1300

# ② 확인 후 실제 반영
python -m credit_export.export --folder ./audit_reports --org 1100 --org 1200 --org 1300 --upload
```

| 옵션 | 뜻 |
|---|---|
| `--folder` | 감사보고서 PDF 폴더 (필수) |
| `--org` | 거래처를 맞출 영업조직. 여러 번 줄 수 있다 |
| `--corp-map corp_map.csv` | `name,corp_code` — 회사명 또는 파일명별 DART 고유번호 지정 (최우선) |
| `--customers customers.csv` | `org_code,code,name` — Supabase 대신 CSV 로 거래처 목록 (미리보기용) |
| `--upload` | 실제 반영 |
| `--overwrite` | 다른 원본 파일로 만든 같은 결산의 평가를 교체 |
| `--overwrite-links` | 다른 기업으로 이미 매칭된 거래처를 교체 (수동 매칭은 여전히 보호) |

미리보기 출력 예(데모 거래처 CSV, 고유번호는 가짜):

```
감사보고서 3건 평가 · 파싱 실패 0건 · 고유번호 미확인 1건
  주식회사 지오영         2025-12-31  A     70.2  검증 14/14  (00000001, corp-map)
      ⚠ 감사시간 39% 감소 (1,831h → 1,115h)
  알보젠코리아 주식회사      2025-12-31  AA    84.5  검증 14/14  (00000002, corp-map)
  아주약품주식회사         2026-03-31  BBB   67.5  검증 17/17  (00000003, corp-map)
      ⚠ 평가 불가 범주 제외: 성장성
      ⚠ 전기 회계기간이 28일로 당기(365일)와 달라 성장률 등 기간 비교가 불가합니다.
  ? 백제약품주식회사 (…): DART 고유번호를 찾지 못함 — OPENDART_API_KEY 또는 --corp-map 필요

거래처 매칭 5건 (유사 1건은 대시보드에서 '확인 필요')
  1100 A0001      (주)지오영               → 00000001 [정확일치 1.0]
  1100 A0002      지오영 부산지점             → 00000001 [유사 0.95]
  …
```

## 3. 단계별 규칙

### 파싱·검증
- 표지에서 회사명·회계기간을, 재무제표에서 매출액·자산총계를 못 찾으면 그 파일은 건너뛴다.
- **회계 항등식이 하나라도 틀리면 등급을 내지 않는다**(`total_score`·`credit_grade` = null).
  대시보드에서는 '미평가'로 보이고, 원인은 `ratios.감사.추출검증` · `ratios.감사.경고` 에 남는다.

### DART 고유번호 (`corp_codes.py`)
`dart_companies`·`dart_evaluations` 의 키는 DART 고유번호인데 감사보고서에는 없다.
① `--corp-map` → ② Supabase 에 이미 있는 회사(dart-analyzer 가 넣은 것) → ③ OpenDART 고유번호 목록
순으로 찾고, **같은 이름이 둘 이상이거나 못 찾으면 올리지 않는다**. 번호를 지어내면 같은 회사가
둘로 갈라진다. OpenDART 에서 찾은 새 회사는 기업개황(업종·사업자번호·대표자·주소)도 채운다.

### 평가 (`scoring.py`) — ⚠️ 초안 스코어카드
0008 에 적힌 5축을 따른다. 기준값·가중치는 설계 예시이며 부도·연체 이력으로 검증한 모형이 아니다.

| 범주 (가중치) | 지표 (양호 → 위험) |
|---|---|
| 성장성 (15) | 매출성장률 10% → −10%, 총자산증가율 10% → −10% |
| 수익성 (25) | 영업이익률 10% → 0%, ROA 8% → 0% |
| 재무구조 (25) | 부채비율 100% → 400%, 유동비율 150% → 80%, 차입금의존도 10% → 50% |
| 부채상환능력 (25) | 이자보상배율 5배 → 1배, 차입금상환기간(차입금/영업CF) 2년 → 8년 |
| 활동성 (10) | 매출채권회전일수 60 → 180일, 재고자산회전일수 60 → 180일 |

- 업종 보정: KSIC `46`(도매)은 부채비율 250 → 600%, 영업이익률 3 → 0% 등 완화(매입채무가 큰 저마진 구조).
  업종 코드는 `dart_companies.induty_code` 또는 OpenDART 기업개황에서 가져온다.
- 등급: AAA ≥ 90 · AA ≥ 80 · A ≥ 70 · BBB ≥ 60 · BB ≥ 50 · B ≥ 40 · CCC ≥ 30 · CC ≥ 20 · C
- 결격: 감사의견 부적정·의견거절 → D, 한정 → BB 이하, 계속기업 불확실성·완전자본잠식 → CCC 이하
- 전기가 1년이 아니면(신설·분할) 성장성 범주를 빼고 나머지로 가중 평균한다.

### 거래처 매칭 (`matching.py`)
- **정확일치**: 법인격(`주식회사` `(주)` `㈜` …)·공백·기호를 뺀 이름이 같다.
- **유사**: 회사명 뒤에 지점·사업부 표기만 붙었거나(`지오영 부산지점`), 앞 두 글자가 같고 유사도 ≥ 0.9.
  대시보드는 유사 매칭을 "매칭 확인 필요"로 표시한다.
- 약국·의원·병원 등으로 끝나는 거래처는 정확일치만 인정한다(`지오영약국` ≠ `지오영`).

### 기존 데이터 보호
| 테이블 | 규칙 |
|---|---|
| dart_evaluations | 같은 (고유번호, 결산일)에 **다른 원본 파일**의 평가가 있으면 건너뜀. 같은 파일을 다시 올리면 갱신 |
| dart_partner_links | 이미 matched → 건너뜀 · no_match → 갱신(보고서로 새로 찾았으므로) · **수동 → 어떤 옵션으로도 안 건드림** |
| dart_companies | 기존 회사는 최신 보고서 이름·날짜만 갱신 |

## 4. 대시보드가 읽는 모양

| 컬럼 | 모양 | 대시보드 |
|---|---|---|
| `category_scores` | `{"수익성": {"score": 61.3, "max": 100, "weight": 25}, …}` | 범주별 점수 막대 |
| `ratios` | `{"재무구조": {"부채비율(%)": 102.99, …}, …, "감사": {"감사의견": "적정", "경고": "…"}}` | 재무비율 표(범주별 묶음) |
| `financials` | `{"2025-03-31": {"자산총계": …}, "2026-03-31": {"매출액": …, "영업이익": …}}` (원) | 재무 추이 막대·표 |

전기가 1년이 아니면 `financials` 의 전기에는 재무상태표 항목만 싣는다 — 28일치 매출을 연간 매출
옆에 두면 대시보드가 '+1,268%' 를 그린다.

## 5. 테스트

```bash
python -m pytest tests/test_credit_export.py        # 매칭·고유번호·평가·보호 규칙·REST (PDF 불필요)
AUDIT_PDF_DIR=/경로 python -m pytest tests/test_parsing_accuracy.py   # 실제 PDF 정확도
```
