# credit_export — 감사보고서 폴더 → 매출채권 대시보드(ar-dashboard) Supabase 연동
#
#   감사보고서 PDF 폴더
#     → disclosure_parser (텍스트 레이어 표 추출 + 회계 항등식 검증)
#     → scoring (5축 스코어카드 → 등급)
#     → corp_codes (DART 고유번호 확인)
#     → matching (회사명 ↔ 거래처명)
#     → supabase_rest (0008 테이블 3개 upsert)
#
# 실행: python -m credit_export.export --help
