# stock-monitor
주식 모니터링 대시보드

## 감사보고서 파싱 · 기업신용평가 연동

- `disclosure_parser.py` — DART 감사보고서 PDF → 재무제표·감사의견·재무비율 (OCR 없이 텍스트 레이어)
- `parsing_accuracy.py` — 파싱 정확도 검증 (좌표 기반 독립 추출 · OCR 대조 · 스캔 PDF 대비 2단계 OCR)
- `credit_export/` — 감사보고서 폴더 → 평가 → 거래처 매칭 → 매출채권 대시보드 Supabase 적재

문서: `docs/dart_pdf_analysis.md` (PDF 구조 분석) · `docs/parsing_accuracy.md` (파싱 방법·정확도) ·
`docs/credit_export.md` (대시보드 연동 사용법) ·
`docs/verification_log.md` (검증 → 개선 기록)

이어서 작업할 때: `HANDOFF.md`(현재 상태·다음 할 일) → `AGENTS.md`(작업 규칙). Claude Code 는 `CLAUDE.md` 가 `AGENTS.md` 를 자동으로 불러오고 `HANDOFF.md` 부터 읽게 안내한다.
