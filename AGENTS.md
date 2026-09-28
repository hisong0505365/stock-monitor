# AGENTS.md — stock-monitor (감사보고서 파싱 · 기업신용평가)

> 작업 규칙의 **원본**. 도구 공통(Claude Code · Gemini CLI 등) — 규칙은 여기에만 적는다.
> `CLAUDE.md` 는 이 파일을 불러오고 Claude 전용 내용만 더한다(ar-dashboard 와 같은 구성).

## 저장소 구성

| 영역 | 파일 | 상태 |
|---|---|---|
| 주식 모니터링 앱(기존) | `app.py` · `stock_analyzer.py` · `data_collector.py` · `chart_maker.py` | 이번 작업에서 손대지 않음 |
| 병원 근처 약국 찾기(별도 앱) | `pharmacy_finder/` | 자체 규칙은 `pharmacy_finder/CLAUDE.md` — 테스트도 그 폴더에서 `python -m pytest` |
| 감사보고서 파서 | `disclosure_parser.py` | DART 감사보고서 PDF → 재무제표·감사의견·업종·재무비율 |
| 정확도 검증 · OCR | `parsing_accuracy.py` | 좌표 기반 독립 추출기, OCR(2단계 · 스캔 조건) |
| 대시보드 연동 | `credit_export/` | 폴더 → 평가 → 거래처 매칭 → ar-dashboard Supabase 0008 테이블 |
| 문서 | `docs/` | 방법·정확도·사용법·검증 기록 |

## 작업 규칙

1. **공개 저장소다.** ar-dashboard(비공개) 코드를 복사해 넣지 않는다. 감사보고서 PDF(`audit_reports/`),
   `.env`, `export_preview.json` 은 커밋하지 않는다(`.gitignore`).
2. **Supabase service_role 키는 `.env` 에만.** RLS 를 우회하는 키다. 코드·문서·로그에 값을 적지 않는다.
3. **운영 Supabase 에 테스트하지 않는다.** DB 통합 테스트는 로컬 PostgreSQL(`tests/setup_test_db.sh`)로.
   `credit_export --upload` 는 미리보기(`--upload` 없이) 결과를 사용자가 확인한 뒤에만.
4. **틀린 등급은 등급 없음보다 위험하다.**
   - 회계 항등식 검증이 하나라도 실패하면 등급을 내지 않는다(`score_report`).
   - DART 고유번호를 지어내지 않는다(corp-map > Supabase 기존 > OpenDART, 못 찾으면 보류).
   - 거래처 이름 매칭은 확실한 것만(정확일치, 지역+지점 표기 '유사'). 약국·의원은 정확일치만.
5. **새 양식에서 틀린 것을 찾으면:** 고치고 → 회귀 테스트 → `docs/verification_log.md` 에 한 줄.
   의미 매핑 오류(숫자는 맞는데 계정이 틀림)는 정답표로만 잡힌다 — 새 회사 보고서가 오면
   `tests/fixtures/audit_ground_truth.json` 에 핵심 14개 항목을 추가한다(페이지 이미지를 눈으로 읽어서).
6. **텍스트 레이어가 있으면 OCR 을 쓰지 않는다.** OCR 은 스캔 페이지 대비용이고, OCR 숫자도
   항등식을 통과해야 쓴다.
7. **정확도·효과는 재서 말한다.** 튜닝에 쓴 문서와 검증 문서를 나눠 재고, 결과는
   `docs/parsing_accuracy.md` 에 적는다. 시험했지만 버린 방법도 이유와 함께 남긴다.
8. 사용자에게는 **한국어**로 답한다.

## 도메인 규칙 (코드만 봐서는 모르는 것)

- 스코어카드(`credit_export/scoring.py`)는 **초안**이다 — 기준값·가중치는 부도·연체 이력으로 검증한
  모형이 아니다. 5축: 성장성 15 · 수익성 25 · 재무구조 25 · 부채상환능력 25 · 활동성 10.
- 의약품 도매(KSIC 46)는 매입채무가 커서 기본 기준이면 구조적으로 깎인다 → 업종 기준 덮어쓰기.
  업종코드가 없으면 감사보고서 주석 1 의 사업 목적 문장으로 판정한다.
- 결격: 부적정·의견거절 → D, 한정 → BB 이하, 계속기업 불확실성 → CCC 이하, 완전자본잠식 → CCC 이하.
  자본잠식이면 부채비율은 무한대(`자본잠식`, 0점), ROE 는 계산하지 않는다.
- 전기가 1년이 아니면(신설·분할) 성장률을 계산하지 않는다(아주약품 전기 28일).
- 같은 (고유번호, 결산일) 보고서가 여럿이면 별도 > 연결 > 늦은 감사보고서일 > 원본 파일명.

## 검증 명령

```bash
python -m pytest tests                                         # PDF·DB 없이 (나머지는 건너뜀)
AUDIT_PDF_DIR=audit_reports python -m pytest tests             # + 실제 PDF 정답표·구조
RUN_OCR_TESTS=1 AUDIT_PDF_DIR=audit_reports python -m pytest tests/test_ocr_rules.py   # + Tesseract (약 1분)
TEST_PG_DSN="host=/tmp port=54330 user=postgres dbname=ar" AUDIT_PDF_DIR=audit_reports \
  python -m pytest tests/test_export_integration.py            # + 로컬 PostgreSQL (Linux/WSL)
```
