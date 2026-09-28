# 감사보고서 파싱 정확도 — 실제 PDF 가 있어야 도는 검증
#
# PDF 는 저장소에 넣지 않았다. AUDIT_PDF_DIR 에 감사보고서를 두고 돌린다 — 정답표
# (tests/fixtures/audit_ground_truth.json)에 있는 9개사 중 폴더에 있는 회사만 검사한다.
# 파일명은 정답표의 files 접두어로 찾는다(없으면 회사명으로 찾는다).
import glob
import json
import os
from pathlib import Path

import pytest

from disclosure_parser import parse_audit_report
from parsing_accuracy import evaluate

GT = json.loads((Path(__file__).parent / "fixtures" / "audit_ground_truth.json").read_text("utf-8"))
PDF_DIR = os.environ.get("AUDIT_PDF_DIR", "")


def _pdf(company):
    for pattern in (GT["files"][company] + "*.pdf", f"*{company}*.pdf"):
        hits = glob.glob(os.path.join(PDF_DIR, pattern))
        if hits:
            return hits[0]
    return None


# 회사별로 건너뛴다 — 처음 받은 4건만 있는 환경에서도 그 4건은 검사한다
COMPANIES = [pytest.param(c, marks=pytest.mark.skipif(
    not PDF_DIR or not _pdf(c), reason=f"AUDIT_PDF_DIR 에 {c} 감사보고서가 없습니다"))
    for c in GT["files"]]


@pytest.mark.parametrize("company", COMPANIES)
def test_표준계정이_사람이_읽은_정답과_일치(company):
    std = parse_audit_report(_pdf(company))["standard"]
    wrong = [(key, p, v, std.get(key, {}).get(p))
             for key, periods in GT["values"][company].items()
             for p, v in periods.items() if std.get(key, {}).get(p) != v]
    assert wrong == []


@pytest.mark.parametrize("company", COMPANIES)
def test_회계_항등식이_모두_성립(company):
    checks = parse_audit_report(_pdf(company))["validation"]
    assert checks and all(c["ok"] for c in checks)


@pytest.mark.parametrize("company", COMPANIES)
def test_표선_방식과_좌표_방식이_모든_칸에서_일치(company):
    for stype, entry in evaluate(_pdf(company))["statements"].items():
        c = entry["parser_vs_coordinates"]
        assert c["missing"] == [] and c["extra"] == [], stype
