# credit_export/matching.py
# 감사보고서 회사명 ↔ 대시보드 거래처명(customers.name) 매칭
#
# 감사보고서에는 사업자번호가 없어 상호로만 맞춘다. 대시보드 거래처는 대부분 약국·의원이라
# '지오영약국' 이 '지오영' 에 붙는 식의 오매칭을 가장 조심한다.
#   정확일치 — 법인격·공백·기호를 뺀 이름이 같다
#   유사     — (1) 회사명 뒤에 '지역 + 지점 표기'만 붙었다 ('지오영 부산지점', '백제약품(주)대구지점')
#              (2) 글자 유사도 ≥ 0.9 이고 앞 두 글자가 같다
#   약국·의원·병원 등으로 끝나는 거래처는 정확일치만 인정한다.
# 대시보드는 '유사' 를 "매칭 확인 필요" 로 표시한다.
#
# 2026-09-26 통합 테스트에서 '지오영경동물류센터' 가 지오영에 붙었다 — 지오영경동은 지오영
# 차입금 주석에 대여자로 나오는 별개 법인이다. 회사명 뒤 '아무 글자 + 센터' 를 지점으로 보던
# 규칙을 '지역명 + 지점 표기' 로 좁혔다. 정당한 지점을 가끔 놓치는 편(수동 매칭으로 보완)이
# 남의 신용등급을 붙이는 편보다 안전하다.

import re
from difflib import SequenceMatcher

LEGAL_FORMS = [
    "주식회사", "유한회사", "유한책임회사", "합자회사", "합명회사",
    "재단법인", "사단법인", "의료법인", "학교법인", "농업회사법인",
    "(주)", "㈜", "(유)", "(재)", "(사)", "(의)", "(합)",
]
LEGAL_FORMS_EN = re.compile(r"(co\.?,?\s*ltd\.?|corp(oration)?\.?|inc\.?|ltd\.?|limited)",
                            re.IGNORECASE)

# 광역시·도, 시, 서울 자치구, 권역 — 지점 이름 앞에 오는 지역
REGIONS = (
    "서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|"
    "수원|성남|의정부|안양|부천|광명|평택|동두천|안산|고양|과천|구리|남양주|오산|시흥|군포|의왕|"
    "하남|용인|파주|이천|안성|김포|화성|양주|포천|여주|춘천|원주|강릉|동해|태백|속초|삼척|청주|"
    "충주|제천|천안|공주|보령|아산|서산|논산|계룡|당진|전주|군산|익산|정읍|남원|김제|목포|여수|"
    "순천|나주|광양|포항|경주|김천|안동|구미|영주|영천|상주|문경|경산|창원|마산|진주|통영|사천|"
    "김해|밀양|거제|양산|서귀포|강남|강동|강북|강서|관악|광진|구로|금천|노원|도봉|동대문|동작|"
    "마포|서대문|서초|성동|성북|송파|양천|영등포|용산|은평|종로|중구|중랑|"
    "수도권|영남|호남|충청|동부|서부|남부|북부|중부"
)
BRANCH_WORDS = "본사|본점|지점|지사|영업소|영업점|출장소|사무소|사업소|물류센터|센터|공장"
BRANCH_SUFFIX = re.compile(
    rf"^(\(?({REGIONS})+\)?({BRANCH_WORDS})?|({BRANCH_WORDS})|\(?\d+\)?)$")
HEALTHCARE_SUFFIX = re.compile(r"(약국|의원|병원|치과|한의원|요양원|보건소|약방)$")

MATCH_EXACT = "정확일치"
MATCH_SIMILAR = "유사"
SIMILARITY_MIN = 0.9


def normalize_company_name(name):
    """'(주)지오영', '주식회사 지오영', '지오영㈜' → '지오영'"""
    if not isinstance(name, str):
        return ""
    s = name
    for form in LEGAL_FORMS:
        s = s.replace(form, "")
    s = LEGAL_FORMS_EN.sub("", s)
    s = re.sub(r"[\s\.\,\-·ㆍ\[\]]", "", s)
    s = re.sub(r"\(\)", "", s)
    return s.lower()


def match_one(customer_name, companies):
    """거래처 1곳 → (회사 키, 방식, 유사도) 또는 None

    companies: {회사 키: 정규화 이름}
    """
    key = normalize_company_name(customer_name)
    if not key:
        return None
    for company, norm in companies.items():
        if norm and norm == key:
            return company, MATCH_EXACT, 1.0
    if HEALTHCARE_SUFFIX.search(key):
        return None

    best = None
    for company, norm in companies.items():
        if len(norm) < 2:
            continue
        if key.startswith(norm) and BRANCH_SUFFIX.match(key[len(norm):]):
            score = 0.95
        elif key[:2] == norm[:2]:
            score = SequenceMatcher(None, key, norm).ratio()
            if score < SIMILARITY_MIN:
                continue
        else:
            continue
        if best is None or score > best[2]:
            best = (company, MATCH_SIMILAR, round(score, 3))
    return best


def match_customers(customers, company_names):
    """customers: [{org_code, code, name}] → [{org_code, code, name, company, match_type, score}]"""
    companies = {c: normalize_company_name(c) for c in company_names}
    out = []
    for c in customers:
        hit = match_one(c["name"], companies)
        if hit:
            company, match_type, score = hit
            out.append({**c, "company": company, "match_type": match_type, "score": score})
    return out
