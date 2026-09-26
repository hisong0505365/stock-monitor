# credit_export/corp_codes.py
# 감사보고서 회사 → DART 고유번호(corp_code)
#
# dart_companies / dart_evaluations 의 키가 corp_code(DART 고유번호 8자리)인데 감사보고서
# PDF 에는 이 번호가 없다. 다음 순서로 찾고, 못 찾으면 올리지 않는다(번호를 지어내면
# dart-analyzer 가 넣은 같은 회사와 둘로 갈라진다).
#   1) --corp-map CSV (회사명 또는 파일명, corp_code) — 사람이 정한 값이 최우선
#   2) Supabase dart_companies 에 이미 있는 회사 (dart-analyzer 가 넣어 둔 것)
#   3) OpenDART 고유번호 목록(corpCode.xml, OPENDART_API_KEY 필요) — 이름이 하나로만 맞을 때

import csv
import io
import xml.etree.ElementTree as ET
import zipfile

import requests

from credit_export.matching import normalize_company_name

OPENDART = "https://opendart.fss.or.kr/api"


def load_corp_map(path):
    """CSV: name,corp_code (name 은 회사명 또는 PDF 파일명)"""
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name, code = (row.get("name") or "").strip(), (row.get("corp_code") or "").strip()
            if name and code:
                out[name] = code.zfill(8)
    return out


def parse_corp_code_xml(xml_bytes):
    """CORPCODE.xml → [{corp_code, corp_name, stock_code}]"""
    root = ET.fromstring(xml_bytes)
    return [{
        "corp_code": (item.findtext("corp_code") or "").strip(),
        "corp_name": (item.findtext("corp_name") or "").strip(),
        "stock_code": (item.findtext("stock_code") or "").strip() or None,
    } for item in root.iter("list")]


def download_corp_codes(api_key, session=None):
    s = session or requests.Session()
    res = s.get(f"{OPENDART}/corpCode.xml", params={"crtfc_key": api_key}, timeout=60)
    res.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        return parse_corp_code_xml(z.read(z.namelist()[0]))


def fetch_company(api_key, corp_code, session=None):
    """OpenDART 기업개황 → dart_companies 컬럼에 맞춘 dict (실패 시 None)"""
    s = session or requests.Session()
    res = s.get(f"{OPENDART}/company.json",
                params={"crtfc_key": api_key, "corp_code": corp_code}, timeout=30)
    if res.status_code != 200:
        return None
    data = res.json()
    if data.get("status") != "000":
        return None
    return {k: (data.get(k) or None) for k in (
        "corp_name", "bizr_no", "stock_code", "corp_cls", "induty_code", "est_dt",
        "ceo_nm", "adres")}


class CorpCodeResolver:
    def __init__(self, corp_map=None, existing_companies=None, dart_list=None):
        self.corp_map = corp_map or {}
        # 정규화 이름 → [corp_code]  (같은 이름이 둘 이상이면 모호)
        self.existing = self._index(existing_companies or [])
        self.dart = self._index(dart_list or [])

    @staticmethod
    def _index(rows):
        idx = {}
        for r in rows:
            idx.setdefault(normalize_company_name(r["corp_name"]), []).append(r["corp_code"])
        return idx

    def resolve(self, company_name, file_name=None):
        """→ (corp_code, 출처) 또는 (None, 사유)"""
        for key in (file_name, company_name):
            if key and key in self.corp_map:
                return self.corp_map[key], "corp-map"
        norm = normalize_company_name(company_name)
        for source, idx in (("supabase", self.existing), ("opendart", self.dart)):
            codes = sorted(set(idx.get(norm, [])))
            if len(codes) == 1:
                return codes[0], source
            if len(codes) > 1:
                return None, f"{source} 에 같은 이름 {len(codes)}곳 — --corp-map 으로 지정 필요"
        return None, "DART 고유번호를 찾지 못함 — OPENDART_API_KEY 또는 --corp-map 필요"
