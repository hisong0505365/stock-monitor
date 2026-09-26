import pytest

import api_client
from api_client import (
    PHARMACY_URL, ApiError, DemoClient, HiraClient, filter_by_region, parse_body,
    parse_hospital, parse_response,
)
from geo_utils import haversine_m, offset_point
from models import Hospital

SNUH = (37.5796, 126.9990)


def xml_response(items, total=None, code="00", msg="NORMAL SERVICE."):
    """심평원 API 응답 형식의 XML"""
    body = "".join(
        "<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in item.items()) + "</item>"
        for item in items
    )
    total = len(items) if total is None else total
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<response><header><resultCode>{code}</resultCode><resultMsg>{msg}</resultMsg></header>"
        f"<body><items>{body}</items><numOfRows>100</numOfRows><pageNo>1</pageNo>"
        f"<totalCount>{total}</totalCount></body></response>"
    ).encode("utf-8")


def pharmacy_item(name, lat, lon):
    return {"yadmNm": name, "addr": "서울특별시 종로구", "telno": "02-000-0000",
            "XPos": lon, "YPos": lat, "ykiho": f"id-{name}"}


class FakeResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


# ===== 응답 파싱 =====
def test_parse_hospital_reads_xpos_as_longitude_and_ypos_as_latitude():
    root = parse_response(xml_response([{
        "yadmNm": "서울대학교병원", "clCdNm": "상급종합", "addr": "서울특별시 종로구 대학로 101",
        "telno": "1588-5700", "XPos": "126.9990", "YPos": "37.5796", "ykiho": "abc",
    }]))
    items, total = parse_body(root)
    hospital = parse_hospital(items[0])

    assert total == 1
    assert hospital == Hospital("abc", "서울대학교병원", "상급종합", "서울특별시 종로구 대학로 101",
                                "1588-5700", lat=37.5796, lon=126.9990)


def test_items_without_coordinates_are_skipped():
    root = parse_response(xml_response([{"yadmNm": "좌표없음", "addr": "서울"}]))
    items, _ = parse_body(root)
    assert parse_hospital(items[0]) is None


def test_gateway_auth_error_raises_friendly_message():
    content = (
        "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
        "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
        "<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    ).encode()
    with pytest.raises(ApiError, match="등록되지 않은 인증키"):
        parse_response(content)


def test_non_ok_result_code_raises():
    with pytest.raises(ApiError, match="API 오류\\(99\\)"):
        parse_response(xml_response([], code="99", msg="INVALID REQUEST"))


def test_non_xml_response_raises():
    with pytest.raises(ApiError, match="해석할 수 없습니다"):
        parse_response(b"Unauthorized")


# ===== HiraClient =====
def test_encoding_key_is_converted_to_decoding_key():
    assert HiraClient("abc%2Bdef%3D%3D", session=FakeSession()).service_key == "abc+def=="
    assert HiraClient("abc+def==", session=FakeSession()).service_key == "abc+def=="


def test_find_pharmacies_sends_lon_as_xpos_and_returns_sorted_within_radius():
    near = offset_point(*SNUH, 0, 100)
    middle = offset_point(*SNUH, 300, 0)
    outside = offset_point(*SNUH, 0, 700)   # API가 반경 밖 약국을 섞어 줘도 걸러야 함
    session = FakeSession(FakeResponse(xml_response([
        pharmacy_item("중간약국", *middle),
        pharmacy_item("반경밖약국", *outside),
        pharmacy_item("가까운약국", *near),
    ])))

    result = HiraClient("key", session=session).find_pharmacies(*SNUH, 500)

    url, params = session.calls[0]
    assert url == PHARMACY_URL
    assert params["xPos"] == SNUH[1] and params["yPos"] == SNUH[0] and params["radius"] == 500
    assert params["serviceKey"] == "key"
    assert [p.name for p in result] == ["가까운약국", "중간약국"]
    assert result[0].distance_m == pytest.approx(haversine_m(*SNUH, *near))


def test_fetch_follows_pages_until_total_count(monkeypatch):
    monkeypatch.setattr(api_client, "PAGE_SIZE", 2)
    spots = [offset_point(*SNUH, 50 * i, 0) for i in range(1, 4)]
    session = FakeSession(
        FakeResponse(xml_response([pharmacy_item("약국1", *spots[0]), pharmacy_item("약국2", *spots[1])], total=3)),
        FakeResponse(xml_response([pharmacy_item("약국3", *spots[2])], total=3)),
    )

    result = HiraClient("key", session=session).find_pharmacies(*SNUH, 500)

    assert [params["pageNo"] for _, params in session.calls] == [1, 2]
    assert [p.name for p in result] == ["약국1", "약국2", "약국3"]


def test_http_401_raises_auth_error():
    session = FakeSession(FakeResponse(b"Unauthorized", status_code=401))
    with pytest.raises(ApiError, match="인증키"):
        HiraClient("key", session=session).search_hospitals("서울대학교병원")


def test_search_hospitals_filters_by_region():
    session = FakeSession(FakeResponse(xml_response([
        {"yadmNm": "한양대학교병원", "clCdNm": "상급종합", "addr": "서울특별시 성동구",
         "XPos": "127.04", "YPos": "37.56", "ykiho": "seoul"},
        {"yadmNm": "한양대학교구리병원", "clCdNm": "종합병원", "addr": "경기도 구리시",
         "XPos": "127.13", "YPos": "37.60", "ykiho": "guri"},
    ])))

    result = HiraClient("key", session=session).search_hospitals("한양대학교", region="경기")

    assert session.calls[0][1]["yadmNm"] == "한양대학교"
    assert [h.id for h in result] == ["guri"]


def test_filter_by_region_handles_full_province_names():
    h = Hospital("x", "충북대학교병원", "상급종합", "충청북도 청주시 서원구", "", 36.62, 127.46)
    assert filter_by_region([h], "충북") == [h]
    assert filter_by_region([h], "충남") == []
    assert filter_by_region([h], None) == [h]


# ===== DemoClient =====
def test_demo_search_ignores_spaces_and_filters_region():
    client = DemoClient()
    assert {h.name for h in client.search_hospitals("서울대학교 병원")} == {"서울대학교병원"}
    assert {h.name for h in client.search_hospitals("서울대학교")} == {"서울대학교병원", "서울대학교치과병원"}
    assert client.search_hospitals("대학교병원", region="부산")[0].name == "부산대학교병원"


def test_demo_pharmacies_are_within_radius_and_sorted():
    result = DemoClient().find_pharmacies(*SNUH, 500)
    distances = [p.distance_m for p in result]
    assert result and all(d <= 500 for d in distances)
    assert distances == sorted(distances)
