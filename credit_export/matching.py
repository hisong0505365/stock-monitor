# credit_export/matching.py
# 감사보고서 회사명 ↔ 대시보드 거래처명(customers.name) 매칭
#
# 감사보고서에는 사업자번호가 없어 상호로만 맞춘다. 대시보드 거래처는 대부분 약국·의원이라
# '지오영약국' 이 '지오영' 에 붙는 식의 오매칭을 가장 조심한다.
#   정확일치 — 법인격·공백·기호를 뺀 이름이 같다
#   유사     — (1) 회사명 뒤에 지점·사업부 표기만 붙었다 ('지오영 부산지점')
#              (2) 글자 유사도 ≥ 0.9 이고 앞 두 글자가 같다
#   약국·의원·병원 등으로 끝나는 거래처는 정확일치만 인정한다.
# 대시보드는 '유사' 를 "매칭 확인 필요" 로 표시한다.

import re
from difflib import SequenceMatcher

LEGAL_FORMS = [
    "주식회사", "유한회사", "유한책임회사", "합자회사", "합명회사",
    "재단법인", "사단법인", "의료법인", "학교법인", "농업회사법인",
    "(주)", "㈜", "(유)", "(재)", "(사)", "(의)", "(합)",
]
LEGAL_FORMS_EN = re.compile(r"(co\.?,?\s*ltd\.?|corp(oration)?\.?|inc\.?|ltd\.?|limited)",
                            re.IGNORECASE)
BRANCH_SUFFIX = re.compile(
    r"^(\(?[가-힣A-Za-z0-9]{0,8}\)?)?(본사|본점|지점|지사|영업소|영업점|사업부|사업소|"
    r"센터|물류센터|출장소|공장|\d+)$")
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
