# 감사의견 · 계속기업 불확실성 판정 — 실제 감사보고서 본문을 바꿔 가며 검증
#
# 고정 데이터는 지오영 감사보고서(적정) 본문이다. 여기에 한정·부적정·의견거절 단락 제목과
# 감사기준서 570 의 '계속기업 관련 중요한 불확실성' 단락을 넣은 변형을 만들어, 표준 문단
# (모든 보고서에 들어가는 "…중요한 불확실성이 존재하는지 여부…")에는 걸리지 않고 실제
# 해당 단락에만 걸리는지 확인한다.
from pathlib import Path

import pytest

from disclosure_parser import audit_findings, business_profile, squash

BASE = squash((Path(__file__).parent / "fixtures" / "audit_text_geoyoung.txt").read_text("utf-8"))
FAIR = "중요성의관점에서공정하게표시하고있습니다"

GOING_CONCERN_PARAGRAPH = squash(
    "계속기업 관련 중요한 불확실성 "
    "재무제표에 대한 주석 2에 주의를 기울여야 할 필요가 있습니다. 재무제표에 대한 주석 2는 "
    "회사가 당기 중 순손실이 발생하였고 보고기간말 현재 유동부채가 유동자산을 초과하고 있음을 "
    "나타내고 있습니다. 이러한 사건이나 상황은 계속기업으로서의 존속능력에 대하여 유의적 의문을 "
    "제기할 만한 중요한 불확실성이 존재함을 나타냅니다. 우리의 의견은 이 사항으로부터 영향을 "
    "받지 아니합니다.")


def _variant(heading, sentence=None):
    text = BASE.replace("감사의견근거", f"{heading}근거", 1).replace("감사의견", heading, 1)
    return text.replace(FAIR, sentence, 1) if sentence else text


def test_실제_적정_보고서():
    f = audit_findings(BASE)
    assert f["opinion"] == "적정"
    assert f["going_concern_uncertainty"] is False    # 표준 문단에는 걸리지 않는다
    assert f["has_emphasis_of_matter"] is False


@pytest.mark.parametrize("heading, sentence, expected", [
    ("한정의견", "한정의견근거단락에기술된사항이미치는영향을제외하고는," + FAIR, "한정"),
    ("부적정의견", "중요성의관점에서공정하게표시하고있지않습니다", "부적정"),
    ("의견거절", "재무제표에대하여의견을표명하지않습니다", "의견거절"),
])
def test_의견_단락_제목으로_판정(heading, sentence, expected):
    assert audit_findings(_variant(heading, sentence))["opinion"] == expected


def test_단락_제목이_없는_옛_양식은_의견_문장으로_판정():
    old = BASE.replace("감사의견", "", 2)
    assert audit_findings(old)["opinion"] == "적정"
    assert audit_findings(old.replace(FAIR, "영향을제외하고는," + FAIR))["opinion"] == "한정"


def test_계속기업_불확실성_단락():
    text = BASE.replace("재무제표에대한경영진과지배기구의책임",
                        GOING_CONCERN_PARAGRAPH + "재무제표에대한경영진과지배기구의책임", 1)
    f = audit_findings(text)
    assert f["going_concern_uncertainty"] is True
    assert f["opinion"] == "적정"          # 의견은 변형되지 않는다


def test_옛_강조사항_문구의_계속기업_의문():
    text = BASE + squash("강조사항 회사는 당기 중 순손실이 발생하였으며, 이러한 상황은 "
                         "계속기업으로서의 존속능력에 중대한 의문을 제기하고 있습니다.")
    f = audit_findings(text)
    assert f["going_concern_uncertainty"] is True and f["has_emphasis_of_matter"] is True


@pytest.mark.parametrize("intro, industry", [
    ("1. 일반 사항 주식회사 지오영(이하 '당사')은 의약품 도ㆍ소매업을 목적으로 2002년 설립되었으며.", "도매"),
    ("1. 일반사항 백제약품 주식회사는 의약품판매업을 주 사 업목적으로 영위하고 있으며, 23개 지점을", "도매"),
    ("1. 회사의 개요 알보젠코리아는 의약품의 연구개발, 제조 및 판매를 목적으로 설립되었으며.", "제조"),
    ("1-3. 주요 사업내용 의약품의 제조가공 및 판매업과 수출입업 등을 목적사업으로 하고", "제조"),
    # 도매업체가 '제조업체' 를 언급해도 사업 목적 문장 밖이면 도매
    ("1. 일반사항 당사는 의약품 도매업을 영위하고 있습니다. 당사는 국내 제조업체로부터 매입합니다.", "도매"),
    ("1. 일반사항 당사는 1990년에 설립되었습니다.", None),
])
def test_사업_목적_문장으로_업종_판정(intro, industry):
    assert business_profile(intro)["industry"] == industry
