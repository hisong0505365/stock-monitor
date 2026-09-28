# 감사보고서 양식 차이 규칙 — PDF 없이 도는 회귀 테스트
#
# 2026-09-27 새 감사보고서 5건(티제이팜·복산나이스·인천약품·동원약품·경동사)을 정답표와 대조해
# 찾은 양식 차이. 실제 보고서에 적힌 문구를 그대로 쓴다.
import pytest

from disclosure_parser import CAPEX_PATTERN, _cover_company, compute_ratios, normalize_account


@pytest.mark.parametrize("raw, name", [
    ("매출채권(주석5,7)", "매출채권"),
    ("단기차입금(주석7,17,19)", "단기차입금"),
    ("장기차입금(주석3과6)", "장기차입금"),          # 인천약품
    ("매출채권(주5,7)", "매출채권"),                  # 경동사
    ("Ⅱ.이익잉여금(결손금)(주17)", "이익잉여금(결손금)"),
    ("1. 현금및현금성자산 (주석 4)", "현금및현금성자산"),
    ("유형자산(주석5와6)", "유형자산"),                # 인천약품 — 예전에는 그대로 남음
    ("매도가능증권(주석3,4와6)", "매도가능증권"),
    ("현금및현금성자산 ( 주 석 3)", "현금및현금성자산"),  # OCR 은 글자마다 띄어 낸다
    ("유형자산(주석6.18,19)", "유형자산"),              # OCR 이 쉼표를 '.' 으로 읽음
])
def test_계정명_뒤_주석_참조를_지운다(raw, name):
    assert normalize_account(raw)[0] == name


def test_주석_번호가_없는_괄호는_남긴다():
    assert normalize_account("이익잉여금(결손금)")[0] == "이익잉여금(결손금)"


@pytest.mark.parametrize("lines, company", [
    # 티제이팜: 제목이 회사명보다 먼저 온다 — 예전에는 '재 무 제 표 에 대 한' 을 회사명으로 읽었다
    (["재 무 제 표 에 대 한", "감   사   보   고   서", "주식회사 티제이팜", "제 21 기",
      "2025년 01월 01일부터", "대 주 회 계 법 인"], "주식회사 티제이팜"),
    (["주식회사 인천약품", "재 무 제 표 에 대 한", "감   사   보   고   서", "정동회계법인"],
     "주식회사 인천약품"),
    (["알보젠코리아", "재 무 제 표 에 대 한", "감   사   보   고   서"], "알보젠코리아"),
])
def test_표지_회사명(lines, company):
    assert _cover_company(lines) == company


@pytest.mark.parametrize("account", [
    "유형자산의취득", "토지의취득", "건물의취득", "차량운반구의취득", "비품의취득", "집기비품의취득",
    "시설장치의취득", "건설중인자산의증가", "건설중인자산의취득",
    "기타의유형자산의증가",          # 복산나이스
    "기타의유형자산의취득",          # 인천약품
])
def test_CAPEX_에_넣는_현금흐름표_계정(account):
    assert CAPEX_PATTERN.match(account)


@pytest.mark.parametrize("account", [
    "기타무형자산의증가", "무형자산의취득", "유형자산의처분", "차량운반구의처분",
    "기타유동자산의감소(증가)", "단기투자자산의증가", "유형자산처분이익",
])
def test_CAPEX_에_넣지_않는_계정(account):
    assert not CAPEX_PATTERN.match(account)


def test_자본잠식이면_부채비율은_무한대_ROE_는_계산하지_않는다():
    """경동사(2025) 실제 수치 — 예전에는 부채비율 -2,560.57%, ROE +95.1% 로 나왔다"""
    y = lambda cur, prev: {"당기": cur, "전기": prev}
    std = {"total_liabilities": y(108_501_226_904, 111_039_175_469),
           "total_equity": y(-4_237_379_696, -207_818_462),
           "total_assets": y(104_263_847_208, 110_831_357_007),
           "net_income": y(-4_029_561_234, -4_319_733_953)}
    r = compute_ratios(std)
    assert r["부채비율(%)"] == float("inf")
    assert r["ROE(%)"] is None
    assert r["ROA(%)"] == -3.86
