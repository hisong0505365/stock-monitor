@AGENTS.md

# CLAUDE.md — stock-monitor (Claude Code 전용 안내)

> 🔴 작업 규칙·도메인 규칙의 원본은 `AGENTS.md` 다(위 `@AGENTS.md` 로 자동 로드된다).
> 규칙을 여기 복사하지 말 것. 이 파일에는 **Claude Code 에서만 쓰는 것**만 적는다.

## 읽는 순서

1. `HANDOFF.md` — 지금까지 한 일 · 현재 상태 · 다음 할 일 · 함정
2. `AGENTS.md` — 작업 규칙·도메인 규칙
3. 손대는 부분의 문서: `docs/parsing_accuracy.md`(파싱·OCR) · `docs/credit_export.md`(대시보드 연동) ·
   `docs/verification_log.md`(검증 → 개선 기록)

## Claude Code 에서만 쓰는 것

- 로컬 위치(권장): `C:\dev\stock-monitor` — ar-dashboard(`C:\dev\ar-dashboard`)와 나란히, OneDrive 밖.
- 감사보고서 PDF 는 `audit_reports\` 에 둔다(커밋 안 됨). 테스트는 `AUDIT_PDF_DIR=audit_reports`.
- Windows PowerShell 에서 환경 변수: `$env:AUDIT_PDF_DIR="audit_reports"; python -m pytest tests`
- Tesseract 는 PATH 에 있어야 한다(`tesseract --list-langs` 에 `kor` 가 보여야 함).
- 커밋 메시지 끝에 `Co-Authored-By: Claude ...` 를 붙인다(세션 지침).
- 작업 브랜치 `claude/pdf-ocr-parsing-disclosure-zo7zya` = PR #2. push 하면 PR 이 갱신된다.
