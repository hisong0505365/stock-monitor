"""
병원/약국 조회 클라이언트
- HiraClient: 건강보험심사평가원 공공데이터 API (인증키 필요)
- DemoClient: 인증키 없이 화면을 확인하기 위한 데모 데이터
"""
import xml.etree.ElementTree as ET
from urllib.parse import unquote

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from demo_data import DEMO_HOSPITALS, DEMO_PHARMACIES
from geo_utils import within_radius
from models import Hospital, Pharmacy

HOSPITAL_URL = "https://apis.data.go.kr/B551182/hospInfoServicev2/getHospBasisList"
PHARMACY_URL = "https://apis.data.go.kr/B551182/pharmacyInfoService/getParmacyBasisList"

PAGE_SIZE = 100
MAX_HOSPITALS = 300
MAX_PHARMACIES = 2000

# 화면에 보여줄 시/도 → 주소 앞부분
REGIONS = {
    "서울": ("서울",),
    "부산": ("부산",),
    "대구": ("대구",),
    "인천": ("인천",),
    "광주": ("광주",),
    "대전": ("대전",),
    "울산": ("울산",),
    "세종": ("세종",),
    "경기": ("경기",),
    "강원": ("강원",),
    "충북": ("충청북도", "충북"),
    "충남": ("충청남도", "충남"),
    "전북": ("전라북도", "전북"),
    "전남": ("전라남도", "전남"),
    "경북": ("경상북도", "경북"),
    "경남": ("경상남도", "경남"),
    "제주": ("제주",),
}

AUTH_ERROR_MESSAGES = {
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR":
        "등록되지 않은 인증키입니다. 공공데이터포털의 일반 인증키를 넣었는지, "
        "해당 API 활용신청이 승인됐는지 확인하세요. (승인 직후에는 키가 동작하기까지 시간이 걸릴 수 있습니다)",
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR":
        "오늘 API 호출 한도를 초과했습니다. 내일 다시 시도하세요.",
    "SERVICE_ACCESS_DENIED_ERROR":
        "이 API를 사용할 권한이 없습니다. 공공데이터포털에서 활용신청 상태를 확인하세요.",
}


class ApiError(Exception):
    pass


# ===== 응답 파싱 =====
def parse_response(content):
    """XML 응답을 검사해 정상일 때 루트 요소를 돌려준다"""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        snippet = content[:200].decode("utf-8", "replace") if isinstance(content, bytes) else content[:200]
        raise ApiError(f"API 응답을 해석할 수 없습니다: {snippet}")

    # 공공데이터포털 게이트웨이 오류 (인증키, 호출 한도 등)
    if root.tag == "OpenAPI_ServiceResponse":
        reason = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "알 수 없는 오류"
        raise ApiError(AUTH_ERROR_MESSAGES.get(reason, f"API 오류: {reason}"))

    code = root.findtext("header/resultCode")
    if code != "00":
        raise ApiError(f"API 오류({code}): {root.findtext('header/resultMsg')}")
    return root


def parse_body(root):
    """(item 요소 목록, 전체 건수)"""
    items = root.findall("body/items/item")
    total_text = root.findtext("body/totalCount")
    total = int(total_text) if total_text and total_text.isdigit() else len(items)
    return items, total


def _text(item, *tags):
    for tag in tags:
        value = item.findtext(tag)
        if value and value.strip():
            return value.strip()
    return ""


def _coords(item):
    """심평원 응답은 XPos = 경도, YPos = 위도. (lat, lon) 순서로 돌려준다"""
    try:
        lon = float(_text(item, "XPos", "xPos"))
        lat = float(_text(item, "YPos", "yPos"))
    except ValueError:
        return None
    if lat == 0 or lon == 0:
        return None
    return lat, lon


def parse_hospital(item):
    coords = _coords(item)
    if coords is None:
        return None
    name = _text(item, "yadmNm")
    address = _text(item, "addr")
    return Hospital(
        id=_text(item, "ykiho") or f"{name}|{address}",
        name=name,
        kind=_text(item, "clCdNm"),
        address=address,
        tel=_text(item, "telno"),
        lat=coords[0],
        lon=coords[1],
    )


def parse_pharmacy(item):
    coords = _coords(item)
    if coords is None:
        return None
    name = _text(item, "yadmNm")
    address = _text(item, "addr")
    return Pharmacy(
        id=_text(item, "ykiho") or f"{name}|{address}",
        name=name,
        address=address,
        tel=_text(item, "telno"),
        lat=coords[0],
        lon=coords[1],
    )


def filter_by_region(hospitals, region):
    if not region:
        return list(hospitals)
    prefixes = REGIONS[region]
    return [h for h in hospitals if h.address.startswith(prefixes)]


# ===== 클라이언트 =====
class HiraClient:
    def __init__(self, service_key, session=None, timeout=10):
        # Encoding 키(%2B 등 포함)를 넣어도 이중 인코딩되지 않도록 Decoding 키로 되돌린다
        self.service_key = unquote(service_key) if "%" in service_key else service_key
        self.session = session or requests.Session()
        self.timeout = timeout

    def search_hospitals(self, name, region=None):
        hospitals = self._fetch_all(HOSPITAL_URL, {"yadmNm": name}, parse_hospital, MAX_HOSPITALS)
        return filter_by_region(hospitals, region)

    def find_pharmacies(self, lat, lon, radius_m):
        params = {"xPos": lon, "yPos": lat, "radius": radius_m}
        pharmacies = self._fetch_all(PHARMACY_URL, params, parse_pharmacy, MAX_PHARMACIES)
        # API가 준 거리 대신 같은 기준(하버사인)으로 다시 계산해 반경 필터 + 거리순 정렬
        return within_radius(lat, lon, pharmacies, radius_m)

    def _fetch_all(self, url, params, parse_item, max_items):
        results = []
        page = 1
        while True:
            root = parse_response(self._request(url, {**params, "pageNo": page, "numOfRows": PAGE_SIZE}))
            items, total = parse_body(root)
            results.extend(x for x in map(parse_item, items) if x is not None)
            if not items or page * PAGE_SIZE >= min(total, max_items):
                return results
            page += 1

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(1),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        reraise=True,
    )
    def _get(self, url, params):
        return self.session.get(url, params={"serviceKey": self.service_key, **params}, timeout=self.timeout)

    def _request(self, url, params):
        try:
            response = self._get(url, params)
        except requests.RequestException as e:
            raise ApiError(f"API 서버에 연결할 수 없습니다: {e}")
        if response.status_code in (401, 403):
            raise ApiError(AUTH_ERROR_MESSAGES["SERVICE_KEY_IS_NOT_REGISTERED_ERROR"])
        if response.status_code != 200:
            raise ApiError(f"API 서버 오류 (HTTP {response.status_code})")
        return response.content


class DemoClient:
    """인증키가 없을 때 쓰는 데모 데이터 클라이언트 (실제 약국 정보 아님)"""

    def search_hospitals(self, name, region=None):
        keyword = name.replace(" ", "")
        found = [h for h in DEMO_HOSPITALS if keyword in h.name.replace(" ", "")]
        return filter_by_region(found, region)

    def find_pharmacies(self, lat, lon, radius_m):
        return within_radius(lat, lon, DEMO_PHARMACIES, radius_m)


def make_client(service_key):
    return HiraClient(service_key) if service_key else DemoClient()
