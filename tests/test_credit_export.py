# credit_export 단위 테스트 — PDF·네트워크 없이 도는 것만
import json
import math

import pytest

from credit_export.corp_codes import CorpCodeResolver, parse_corp_code_xml
from credit_export.export import (
    _clean, build_financials, build_link, build_ratios, dedupe_reports, filter_evaluations,
    filter_links,
)
from credit_export.matching import match_customers, match_one, normalize_company_name
from credit_export.scoring import cap_grade, grade_for, industry_code, score_report
from credit_export.supabase_rest import PAGE, SupabaseRest


# ===== 매칭 =====

COMPANIES = {c: normalize_company_name(c) for c in
             ["주식회사 지오영", "백제약품주식회사", "알보젠코리아 주식회사"]}


@pytest.mark.parametrize("name", ["(주)지오영", "지오영㈜", "주식회사 지오영", "지오영 (주)"])
def test_법인격_표기가_달라도_정확일치(name):
    assert match_one(name, COMPANIES) == ("주식회사 지오영", "정확일치", 1.0)


def test_지점_표기는_유사():
    company, kind, score = match_one("지오영 부산지점", COMPANIES)
    assert (company, kind) == ("주식회사 지오영", "유사")
    assert score >= 0.9


@pytest.mark.parametrize("name", ["지오영약국", "백제약국", "지오영의원", "백제약품약국"])
def test_약국_의원은_이름이_비슷해도_붙이지_않는다(name):
    assert match_one(name, COMPANIES) is None


# 2026-09-26 통합 테스트에서 '지오영경동물류센터' 가 지오영에 붙었다(지오영경동은 별개 법인).
# 회사명 뒤 '아무 글자 + 센터' 를 지점으로 보던 규칙을 '지역 + 지점 표기' 로 좁혔다.
@pytest.mark.parametrize("name", ["지오영경동물류센터", "(주)지오영경동", "지오영경동센터",
                                  "지오영 경동지점", "지오영케어", "아주약품상사"])
def test_다른_법인으로_보이는_이름은_붙이지_않는다(name):
    companies = {**COMPANIES, "아주약품주식회사": "아주약품"}
    assert match_one(name, companies) is None


@pytest.mark.parametrize("name", ["지오영 부산지점", "지오영(부산)", "지오영경기남부지점",
                                  "지오영 영등포물류센터", "지오영본사", "지오영2"])
def test_지역_지점_표기는_유사로_붙인다(name):
    assert match_one(name, COMPANIES)[:2] == ("주식회사 지오영", "유사")


def test_앞글자가_다르면_유사도가_높아도_붙이지_않는다():
    assert match_one("대한알보젠코리아", COMPANIES) is None


def test_match_customers_는_매칭된_거래처만_돌려준다():
    customers = [{"org_code": "1100", "code": "A1", "name": "(주)지오영"},
                 {"org_code": "1100", "code": "A2", "name": "행복약국"}]
    out = match_customers(customers, list(COMPANIES))
    assert [c["code"] for c in out] == ["A1"]


# ===== DART 고유번호 =====

def test_corp_map_이_최우선():
    r = CorpCodeResolver({"주식회사 지오영": "00123456"},
                         [{"corp_code": "99999999", "corp_name": "지오영"}])
    assert r.resolve("주식회사 지오영") == ("00123456", "corp-map")


def test_supabase_에_있는_회사를_재사용():
    r = CorpCodeResolver({}, [{"corp_code": "00111111", "corp_name": "(주)지오영"}])
    assert r.resolve("주식회사 지오영") == ("00111111", "supabase")


def test_같은_이름이_둘이면_지어내지_않고_보류():
    dart = [{"corp_code": "00000001", "corp_name": "지오영"},
            {"corp_code": "00000002", "corp_name": "(주)지오영"}]
    code, why = CorpCodeResolver({}, [], dart).resolve("주식회사 지오영")
    assert code is None and "2곳" in why


def test_corp_map_이_Supabase_기존_번호와_다르면_경고():
    r = CorpCodeResolver({"주식회사 지오영": "00000001"},
                         [{"corp_code": "00111111", "corp_name": "(주)지오영"}])
    assert r.resolve("주식회사 지오영") == ("00000001", "corp-map")
    assert r.conflicts == [("주식회사 지오영", "00000001", ["00111111"])]


def test_못_찾으면_보류():
    code, _ = CorpCodeResolver().resolve("없는회사")
    assert code is None


def test_corpCode_xml_파싱():
    xml = ("<result><list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>"
           "<stock_code>005930</stock_code></list><list><corp_code>01234567</corp_code>"
           "<corp_name>지오영</corp_name><stock_code> </stock_code></list></result>").encode()
    assert parse_corp_code_xml(xml) == [
        {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930"},
        {"corp_code": "01234567", "corp_name": "지오영", "stock_code": None},
    ]


# ===== 평가 =====

def _report(**meta_over):
    """지오영 수치를 본뜬 최소 파싱 결과"""
    y = lambda cur, prev: {"당기": cur, "전기": prev}
    std = {
        "revenue": y(3_484_874, 3_206_947), "cost_of_sales": y(3_309_341, 3_042_967),
        "gross_profit": y(175_533, 163_980), "operating_income": y(72_316, 62_185),
        "net_income": y(57_262, 47_658), "total_assets": y(1_504_839, 1_410_128),
        "total_liabilities": y(1_118_524, 1_028_959), "total_equity": y(386_314, 381_169),
        "current_assets": y(1_138_313, 1_044_891), "current_liabilities": y(998_419, 957_580),
        "short_term_borrowings": y(122_425, 156_957), "long_term_borrowings": y(79_733, 36_191),
        "receivables": y(725_429, 747_661), "inventories": y(275_956, 263_252),
        "payables": y(644_629, 616_800), "cfo": y(160_915, -33_666), "capex": y(5_092, 12_096),
        "interest_paid": y(12_290, 8_418),
    }
    meta = {"opinion": "적정", "going_concern_uncertainty": False,
            "periods": {"당기": {"days": 365, "end": "2025-12-31"},
                        "전기": {"days": 366, "end": "2024-12-31"}},
            "audit_hours": {"당기": 1115, "전기": 1831}}
    meta.update(meta_over)
    return {"standard": std, "meta": meta, "validation": [{"ok": True}], "warnings": []}


def test_등급_구간():
    assert [grade_for(s) for s in (95, 85, 72, 60, 59.9, 0)] == ["AAA", "AA", "A", "BBB", "BB", "C"]
    assert cap_grade("AA", "CCC") == "CCC"
    assert cap_grade("CC", "CCC") == "CC"


def test_정상_보고서는_5개_범주_모두_점수():
    s = score_report(_report())
    assert all(v["score"] is not None for v in s["category_scores"].values())
    assert s["credit_grade"] == grade_for(s["total_score"])
    assert any("감사시간 39% 감소" in f for f in s["flags"])


def test_도매업_기준을_쓰면_부채비율_점수가_오른다():
    base = score_report(_report())
    wholesale = score_report(_report(), induty_code="46441")
    debt = lambda s: next(m["점수"] for m in s["metrics"] if m["지표"] == "부채비율(%)")
    assert debt(wholesale) > debt(base)


def test_업종코드가_없으면_보고서_주석의_업종을_쓴다():
    r = _report(business={"industry": "도매", "purpose": "의약품 도ㆍ소매업을 목적으로"})
    assert industry_code(r) == ("46", "보고서 주석의 사업 목적 → 도매")
    assert industry_code(r, "21210")[0] == "21210"          # DART 업종코드가 우선
    wholesale = score_report(r)
    assert any("도매업 기준 적용" in f for f in wholesale["flags"])
    assert wholesale["total_score"] > score_report(_report())["total_score"]


def test_감사의견_부적정은_D():
    assert score_report(_report(opinion="부적정"))["credit_grade"] == "D"


def test_계속기업_불확실성은_CCC_이하():
    s = score_report(_report(going_concern_uncertainty=True))
    assert s["credit_grade"] in ("CCC", "CC", "C", "D")


def test_자본잠식이면_부채비율은_최하점_ROE_는_비운다():
    """경동사(2025): 자본총계 -42억 → 부채비율 -2,560% 가 만점, ROE +95% 로 계산되던 문제(2026-09-27)"""
    r = _report()
    r["standard"]["total_equity"] = {"당기": -4_237, "전기": -208}
    r["standard"]["net_income"] = {"당기": -4_030, "전기": -4_320}
    s = score_report(r)
    debt = next(m for m in s["metrics"] if m["지표"] == "부채비율(%)")
    assert debt["값"] == float("inf") and debt["점수"] == 0.0
    assert s["values"]["ROE(%)"] is None
    assert "완전자본잠식 → CCC 이하" in s["flags"]
    assert s["credit_grade"] in ("CCC", "CC", "C", "D")
    ratios = build_ratios(r, s)
    assert ratios["재무구조"]["부채비율(%)"] == "자본잠식"
    json.dumps(ratios)


def test_추출_검증_실패면_등급을_내지_않는다():
    r = _report()
    r["validation"] = [{"ok": True}, {"ok": False}]
    s = score_report(r)
    assert s["credit_grade"] is None and s["total_score"] is None


def test_전기가_짧으면_성장성_제외():
    r = _report(periods={"당기": {"days": 365, "end": "2026-03-31"},
                         "전기": {"days": 28, "end": "2025-03-31"}})
    s = score_report(r)
    assert s["category_scores"]["성장성"]["score"] is None
    assert s["total_score"] is not None


# ===== 행 만들기 =====

def test_짧은_전기는_재무상태표만_싣는다():
    r = _report(periods={"당기": {"days": 365, "end": "2026-03-31"},
                         "전기": {"days": 28, "end": "2025-03-31"}})
    fin = build_financials(r)
    assert "매출액" in fin["2026-03-31"]
    assert "매출액" not in fin["2025-03-31"] and "자산총계" in fin["2025-03-31"]


def test_inf_는_JSON_에_실을_수_있게_바꾼다():
    assert _clean(float("inf"), "차입금상환기간(년)") == "상환불가(영업CF≤0)"
    assert _clean(float("inf"), "부채비율(%)") == "자본잠식"
    assert _clean(float("inf")) == "산출불가"
    assert _clean(math.nan) is None
    json.dumps(_clean(float("inf")))


def _link(code, corp):
    return build_link({"org_code": "1100", "code": code, "name": code,
                       "match_type": "정확일치", "score": 1.0}, corp)


def test_기존_매칭_보호():
    rows = [_link("A1", "X"), _link("A2", "X"), _link("A3", "X"), _link("A4", "X"), _link("A5", "X")]
    existing = {
        ("1100", "A2"): {"status": "no_match", "match_type": None, "corp_code": None},
        ("1100", "A3"): {"status": "matched", "match_type": "수동", "corp_code": "Y"},
        ("1100", "A4"): {"status": "matched", "match_type": "유사", "corp_code": "Y"},
        ("1100", "A5"): {"status": "matched", "match_type": "정확일치", "corp_code": "X"},
    }
    keep, _ = filter_links(rows, existing, overwrite=False)
    assert [r["customer_code"] for r in keep] == ["A1", "A2"]      # 새 거래처 + no_match 갱신
    keep, _ = filter_links(rows, existing, overwrite=True)
    assert [r["customer_code"] for r in keep] == ["A1", "A2", "A4"]  # 수동은 끝까지 보호


def _r(file, consolidated=False, report_date="2026-03-23", end="2025-12-31"):
    return ({"file": file, "meta": {"period_end": end, "consolidated": consolidated,
                                    "report_date": report_date}}, "X", "corp-map")


def test_폴더_안_같은_결산_중복은_하나만_남긴다():
    # 한 번의 upsert 에 같은 키가 두 번 들어가면 PostgreSQL 이 요청 전체를 거절한다
    keep, dropped = dedupe_reports([_r("a (1).pdf"), _r("a.pdf"), _r("a - 복사본.pdf")])
    # 동점이면 원본 이름을 남긴다 — 사본 이름이 source_file 로 남으면 나중에 갱신이 막힌다
    assert [k[0]["file"] for k in keep] == ["a.pdf"]
    assert sorted(d[0] for d in dropped) == ["a (1).pdf", "a - 복사본.pdf"]


def test_별도와_연결이_둘_다_있으면_별도():
    keep, dropped = dedupe_reports([_r("연결.pdf", consolidated=True), _r("별도.pdf")])
    assert keep[0][0]["file"] == "별도.pdf"
    assert dropped == [("연결.pdf", "별도.pdf", "연결 — 별도 감사보고서를 씀")]


def test_같은_결산이면_감사보고서일이_늦은_것():
    keep, _ = dedupe_reports([_r("old.pdf", report_date="2026-03-01"), _r("new.pdf", report_date="2026-04-10")])
    assert keep[0][0]["file"] == "new.pdf"


def test_결산일이_다르면_둘_다_남긴다():
    keep, dropped = dedupe_reports([_r("24.pdf", end="2024-12-31"), _r("25.pdf")])
    assert len(keep) == 2 and dropped == []


def test_다른_원본의_같은_결산_평가는_덮지_않는다():
    rows = [{"corp_code": "X", "period_end": "2025-12-31", "source_file": "mine.pdf"}]
    assert filter_evaluations(rows, {("X", "2025-12-31"): "dart.pdf"}, False)[0] == []
    assert filter_evaluations(rows, {("X", "2025-12-31"): "mine.pdf"}, False)[0] == rows
    assert filter_evaluations(rows, {("X", "2025-12-31"): "dart.pdf"}, True)[0] == rows


# ===== Supabase REST =====

class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, ""

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def get(self, url, headers, params, timeout):
        self.calls.append(("GET", url, dict(params)))
        return FakeResponse(self.pages.pop(0))

    def post(self, url, headers, params, json, timeout):
        self.calls.append(("POST", url, dict(params), headers["Prefer"], json))
        return FakeResponse(None, 201)


def test_select_all_은_커서로_끝까지_읽는다():
    first = [{"code": f"C{i:04d}"} for i in range(PAGE)]
    s = FakeSession([first, [{"code": "Z"}]])
    rows = SupabaseRest("https://x.supabase.co", "k", s).select_all(
        "customers", "code", order="code", filters={"org_code": "eq.1100"})
    assert len(rows) == PAGE + 1
    assert s.calls[1][2]["code"] == f"gt.C{PAGE - 1:04d}"
    assert s.calls[1][2]["org_code"] == "eq.1100"


def test_upsert_는_충돌_키와_해결_방식을_보낸다():
    s = FakeSession([])
    SupabaseRest("https://x.supabase.co/", "k", s).upsert(
        "dart_evaluations", [{"a": 1}], on_conflict="corp_code,period_end")
    _, url, params, prefer, body = s.calls[0]
    assert url == "https://x.supabase.co/rest/v1/dart_evaluations"
    assert params == {"on_conflict": "corp_code,period_end"}
    assert prefer.startswith("resolution=merge-duplicates")
    assert body == [{"a": 1}]
