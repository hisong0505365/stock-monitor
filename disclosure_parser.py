# disclosure_parser.py
# DART 감사보고서 PDF → 재무제표 구조화 + 검증 + 기본 재무비율
#
# DART가 생성한 PDF(iText)는 텍스트 레이어와 표 선(ruling line)이 있으므로
# OCR 없이 PyMuPDF의 표 인식으로 행/열을 복원한다.
# OCR은 텍스트 레이어가 없는 페이지(서명 스캔본 등)에만 필요하다.

import json
import re
import sys

import pymupdf

# find_tables() 호출 시 stdout에 찍히는 pymupdf_layout 권장 문구 끄기 (JSON 출력 보호)
pymupdf.no_recommend_layout()

# ===== 재무제표 제목 =====

STATEMENT_TITLES = {
    "재무상태표": "BS",
    "연결재무상태표": "BS",
    "대차대조표": "BS",
    "포괄손익계산서": "IS",
    "연결포괄손익계산서": "IS",
    "손익계산서": "IS",
    "연결손익계산서": "IS",
    "자본변동표": "CE",
    "연결자본변동표": "CE",
    "현금흐름표": "CF",
    "연결현금흐름표": "CF",
}

# ===== 표준 계정 매핑 (정규화된 계정명 → 표준 키) =====
# 회사마다 계정명이 다르므로 동의어를 순서대로 시도한다.

STANDARD_ACCOUNTS = {
    "BS": {
        "current_assets": ["유동자산"],
        "cash": ["현금및현금성자산"],
        "receivables": ["매출채권및기타채권", "매출채권"],
        "inventories": ["재고자산"],
        "non_current_assets": ["비유동자산"],
        "total_assets": ["자산총계"],
        "current_liabilities": ["유동부채"],
        "payables": ["매입채무및기타채무", "매입채무"],
        # '구간:계정' — 같은 이름이 유동/비유동에 모두 있는 계정(알보젠 '차입부채')은 구간으로 가른다
        "short_term_borrowings": ["단기차입금", "유동부채:차입부채", "유동부채:차입금"],
        "current_portion_ltd": ["유동성장기차입금", "유동성장기부채", "유동성사채"],
        "long_term_borrowings": ["장기차입금", "비유동부채:차입부채", "비유동부채:차입금"],
        "bonds": ["사채", "비유동부채:사채"],
        "current_lease_liabilities": ["유동리스부채"],
        "non_current_lease_liabilities": ["비유동리스부채"],
        "non_current_liabilities": ["비유동부채"],
        "total_liabilities": ["부채총계"],
        "total_equity": ["자본총계"],
        "total_liabilities_and_equity": ["부채및자본총계", "부채와자본총계"],
    },
    "IS": {
        "revenue": ["매출액", "매출", "영업수익", "수익(매출액)"],
        "cost_of_sales": ["매출원가", "영업비용"],
        "gross_profit": ["매출총이익", "매출총이익(손실)"],
        "sga": ["판매비와관리비", "판매비및관리비"],
        "operating_income": ["영업이익", "영업이익(손실)", "영업손실"],
        "interest_expense": ["이자비용"],
        "pretax_income": ["법인세비용차감전순이익", "법인세차감전이익",
                          "법인세비용차감전순이익(손실)", "법인세차감전순이익"],
        "income_tax": ["법인세비용", "법인세비용(수익)"],
        "net_income": ["당기순이익", "당기순이익(손실)", "당기순손실"],
    },
    "CF": {
        "cfo": ["영업활동으로인한현금흐름", "영업활동현금흐름"],
        "cfi": ["투자활동으로인한현금흐름", "투자활동현금흐름"],
        "cff": ["재무활동으로인한현금흐름", "재무활동현금흐름"],
        "interest_paid": ["이자의지급", "이자비용의지급", "이자지급"],
        "dividends_paid": ["배당금의지급", "배당금지급"],
        "cash_end": ["기말의현금및현금성자산", "기말현금및현금성자산",
                     "기말의현금", "기말현금"],
    },
}

# 비용 계정: 문서마다 양수/괄호(음수) 표기가 섞여 있으므로 절대값으로 통일
EXPENSE_KEYS = {"cost_of_sales", "sga", "interest_expense", "interest_paid",
                "dividends_paid"}

# 유형자산 취득(CAPEX): 백제약품처럼 토지/건물/비품 취득으로 쪼개진 경우 합산
# 백제약품은 '건설중인자산의 증가'로 적는다 — '취득'만 보면 설비투자가 빠진다
CAPEX_PATTERN = re.compile(
    r"^(유형자산|토지|건물|구축물|기계장치|차량운반구|비품|공구와기구|"
    r"건설중인자산|시설장치|집기비품|공기구비품)의?(취득|증가)$")

# 재무상태표 구간 표시 행 — 같은 이름의 계정을 유동/비유동으로 가를 때 쓴다
BS_SECTIONS = {"자산", "유동자산", "비유동자산", "부채", "유동부채", "비유동부채", "자본"}

# ===== 문자열 정규화 =====

ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ"
HANGUL_ENUM = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허"

PREFIX_PATTERNS = [
    # 로마숫자: 유니코드(Ⅰ, ⅩⅠ) 및 라틴 대문자(I, IV, VII, X)
    (1, re.compile(rf"^([{ROMAN}]+|[IVX]+)\s*\.\s*")),
    (2, re.compile(r"^\(\d+\)\s*")),
    (3, re.compile(r"^\d+\s*\.\s*")),
    (4, re.compile(rf"^[{HANGUL_ENUM}]\s*\.\s*")),
    (4, re.compile(r"^[①-⑳]\s*")),
]

NOTE_REF = re.compile(r"\(주석[\d,\s]*\)")


def normalize_account(raw):
    """계정명 정규화. 반환: (정규화 이름, 계층 레벨 또는 None)"""
    if raw is None:
        return "", None
    s = raw.replace("\n", "").strip()
    level = None
    for lv, pat in PREFIX_PATTERNS:
        m = pat.match(s)
        if m:
            level = lv
            s = s[m.end():]
            break
    s = NOTE_REF.sub("", s)
    s = re.sub(r"\s+", "", s)
    return s, level


def parse_amount(cell):
    """'1,234' → 1234, '(1,234)' → -1234, '-' → 0, '' → None"""
    if cell is None:
        return None
    s = cell.replace("\n", "").replace(" ", "").strip()
    if s == "":
        return None
    if s in ("-", "－", "—"):
        return 0
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.startswith("△") or s.startswith("-"):
        neg, s = True, s[1:]
    s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    v = float(s) if "." in s else int(s)
    return -v if neg else v


def squash(text):
    """공백/줄바꿈 제거 (제목 비교, 키워드 검색용)"""
    return re.sub(r"\s+", "", text or "")


# ===== 표 헤더 해석 =====

def _period_label(header):
    h = squash(header)
    if "기초" in h:
        return "전기초" if "(전)" in h else "당기초"
    if "(당)" in h:
        return "당기"
    if "(전)" in h:
        return "전기"
    if "(전전)" in h:
        return "전전기"
    return h


def build_column_map(header_row):
    """헤더 행 → {열 인덱스: 기간 라벨}, 주석 열 인덱스

    알보젠/아주약품/백제약품처럼 한 기간이 (세부, 합계) 2개 열로 나뉜 경우
    헤더에 None이 이어지므로 앞 기간 라벨을 그대로 이어받는다.
    """
    col_map, note_col, current = {}, None, None
    for i, cell in enumerate(header_row):
        if i == 0:
            continue
        h = squash(cell) if cell else ""
        if h == "주석":
            note_col, current = i, None
            continue
        if cell is None:
            if current is not None:
                col_map[i] = current
            continue
        current = _period_label(cell)
        col_map[i] = current
    return col_map, note_col


def _is_header(row):
    return row and squash(row[0]) in ("과목", "구분")


# ===== 페이지 → 재무제표 표 수집 =====

def _page_title(page):
    for line in page.get_text().split("\n"):
        t = squash(line)
        if t:
            return t
    return ""


def extract_statements(doc):
    """본문 재무제표(BS/IS/CE/CF)의 행을 기간별 금액으로 추출"""
    statements = {}
    current_type, col_map, note_col = None, None, None

    for pno, page in enumerate(doc):
        title = _page_title(page)
        if title.startswith("주석"):
            break
        stype = STATEMENT_TITLES.get(title)
        if stype:
            current_type = stype
            statements.setdefault(stype, {"pages": [], "periods": [], "rows": []})
        if current_type is None:
            continue

        for tab in page.find_tables().tables:
            rows = tab.extract()
            if not rows:
                continue
            if _is_header(rows[0]):
                col_map, note_col = build_column_map(rows[0])
                rows = rows[1:]
                # 자본변동표 등 2단 헤더: 두 번째 행도 헤더면 건너뜀
                if rows and rows[0] and rows[0][0] is None:
                    rows = rows[1:]
            elif col_map is None:
                continue

            st = statements[current_type]
            st["pages"].append(pno + 1)
            for p in col_map.values():
                if p not in st["periods"]:
                    st["periods"].append(p)

            if current_type == "CE":
                # 자본변동표는 열이 자본 구성요소이므로 원형 그대로 보관
                st["rows"].extend(rows)
                continue

            for row in rows:
                name, level = normalize_account(row[0])
                if not name:
                    continue
                values = {}
                for ci, period in col_map.items():
                    if ci >= len(row):
                        continue
                    v = parse_amount(row[ci])
                    # (세부, 합계) 열 중 값이 있는 쪽을 채택
                    if v is not None and values.get(period) is None:
                        values[period] = v
                st["rows"].append({
                    "account": name,
                    "raw": (row[0] or "").replace("\n", ""),
                    "level": level,
                    "note": row[note_col] if note_col is not None and note_col < len(row) else None,
                    "values": values,
                })
    return statements


# ===== 메타데이터 (표지, 감사의견, 감사시간) =====

PERIOD_RE = re.compile(
    r"제(\d+)(?:\((당|전)\))?기(\d{4})년(\d{2})월(\d{2})일부터(\d{4})년(\d{2})월(\d{2})일까지")
DATE_RE = re.compile(r"(\d{4})년(\d{1,2})월(\d{1,2})일")


def _ymd(y, m, d):
    return f"{y}-{int(m):02d}-{int(d):02d}"


def _days(start, end):
    from datetime import date
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    return (e - s).days + 1


def extract_metadata(doc):
    cover = doc[1].get_text() if doc.page_count > 1 else ""
    full = "".join(p.get_text() for p in doc)
    flat = squash(full)
    meta = {}

    # 감사보고서 본문 = 표지 ~ '(첨부)재무제표' 직전, 첨부 표지에 당기/전기 기간이 모두 있다
    attach_idx = next((i for i, p in enumerate(doc)
                       if _page_title(p).startswith("(첨부)")), None)
    audit_flat = squash("".join(doc[i].get_text() for i in range(1, attach_idx or 1)))

    lines = [l.strip() for l in cover.split("\n") if l.strip()]
    if lines:
        meta["company"] = lines[0]
    # 표지 제목: '재무제표에 대한 감사보고서'(별도) / '연결재무제표에 대한 감사보고서'(연결)
    meta["consolidated"] = "연결재무제표에대한" in squash(cover)
    for l in lines:
        if squash(l).endswith("회계법인"):
            meta["auditor"] = squash(l)
            break

    # 회계기간: 첨부 표지에서 당기/전기 기간을 모두 읽는다
    period_src = squash(doc[attach_idx].get_text()) if attach_idx is not None else squash(cover)
    periods = PERIOD_RE.findall(period_src)
    for label, p in zip(("당기", "전기"), periods):
        start, end = _ymd(*p[2:5]), _ymd(*p[5:8])
        meta.setdefault("periods", {})[label] = {
            "term": int(p[0]), "start": start, "end": end, "days": _days(start, end)}
    if periods:
        cur = meta["periods"]["당기"]
        meta["fiscal_term"], meta["period_start"], meta["period_end"] = (
            cur["term"], cur["start"], cur["end"])

    # 감사보고서일: '감사보고서일(날짜)' → 없으면 '이 감사보고서는…' 앞의 마지막 날짜
    m = re.search(r"감사보고서일\((\d{4})년(\d{1,2})월(\d{1,2})일\)", audit_flat)
    if m:
        meta["report_date"] = _ymd(*m.groups())
    else:
        head = audit_flat.split("이감사보고서는감사보고서일")[0]
        dates = DATE_RE.findall(head)
        if dates:
            meta["report_date"] = _ymd(*dates[-1])

    # 회계기준: 감사의견 문단의 '…에 따라 중요성의 관점에서' 로 판정
    # (주석에는 다른 기준명이 언급될 수 있으므로 전체 검색은 오판한다)
    m = re.search(r"(한국채택국제회계기준|일반기업회계기준)에따라,?중요성의관점에서", audit_flat)
    if m:
        meta["gaap"] = "K-IFRS" if m.group(1).startswith("한국채택") else "K-GAAP(일반기업회계기준)"

    meta.update(audit_findings(audit_flat))
    meta["has_icfr_review"] = "내부회계관리제도" in flat and "검토의견" in flat
    meta["business"] = business_profile(_notes_intro(doc))

    meta["audit_hours"] = _extract_audit_hours(doc)
    meta["pages_without_text"] = [i + 1 for i, p in enumerate(doc)
                                  if p.get_images() and len(squash(p.get_text())) < 80]
    return meta


# ===== 감사의견 판정 =====
# 감사보고서 본문(표지 ~ 첨부 재무제표 표지)만 본다. 주석·내부회계관리제도 보고서의 문구로
# 판정이 흔들리지 않게 하려는 것이다.
#
# ⚠️ 모든 감사보고서의 '감사인의 책임' 표준 문단에 "계속기업으로서의 존속능력에 대하여 유의적
#    의문을 초래할 수 있는 … 중요한 불확실성이 존재하는지 여부"와 "중요한 불확실성이 존재한다고
#    결론을 내리는 경우"가 들어 있다. '중요한 불확실성' 같은 단어만 찾으면 모든 회사가 걸리고,
#    특정 문구 하나만 찾으면 표현이 조금만 달라도 놓친다(2026-09-26 검증에서 확인). 실제 해당
#    보고서에만 나오는 **단락 제목**과 **결론 문장**으로 판정한다.

# 비적정 신호 — 표준 문단에는 절대 나오지 않는 단락 제목·결론 문장. 이것부터 찾는다.
# '감사의견' 이라는 단어는 제목뿐 아니라 "감사의견을 위한 근거로서" 같은 표준 문장에도 있어서,
# 제목만 보고 판정하면 한정 제목이 빠진 옛 양식의 한정 보고서를 적정으로 읽는다(검증에서 확인).
NON_CLEAN_OPINIONS = [
    ("의견거절", re.compile(r"의견거절|의견을표명하지않습니다")),
    ("부적정", re.compile(r"부적정의견|공정하게표시하고있지않습니다")),
    ("한정", re.compile(r"한정의견|영향을제외하고는,?[^.]{0,200}공정하게표시하고있습니다")),
]
GOING_CONCERN = re.compile(
    r"계속기업관련중요한불확실성"                        # 감사기준서 570 단락 제목
    r"|중요한불확실성이존재함을나타냅니다"                  # 그 단락의 결론 문장
    r"|존속능력에(대하여)?(유의적|중대한)의문을제기(할만한|하고있)")  # 결론 문장 · 옛 강조사항 문구


def audit_findings(audit_text):
    """감사보고서 본문(공백 제거) → 감사의견 · 계속기업 불확실성 · 강조/기타사항"""
    opinion = next((name for name, pattern in NON_CLEAN_OPINIONS if pattern.search(audit_text)),
                   None)
    if opinion is None and ("공정하게표시하고있습니다" in audit_text or "감사의견" in audit_text):
        opinion = "적정"
    return {
        "opinion": opinion,
        "going_concern_uncertainty": bool(GOING_CONCERN.search(audit_text)),
        "has_emphasis_of_matter": "강조사항" in audit_text,
        "has_key_audit_matters": "핵심감사사항" in audit_text,
        "has_other_matter": "기타사항" in audit_text,
    }


# ===== 업종 판정 (주석 1. 일반사항) =====
# OpenDART 업종코드를 못 받을 때 쓴다. 도매업체도 "제조업체로부터 매입" 처럼 '제조' 라는 말을
# 쓰므로 주석 전체가 아니라 **사업 목적 문장** 안에서만 판정한다.

PURPOSE_SENTENCE = re.compile(
    r"[^.。]*(목적으로|목적사업|사업목적|주요사업내용|주요\s*사업\s*내용|영위)[^.。]*")
MANUFACTURING = re.compile(r"제조|생산|연구개발")
WHOLESALE = re.compile(r"도매|도ㆍ소매|도·소매|도소매|유통|판매업|수출입|수입")


def _notes_intro(doc):
    """주석 첫 부분(1. 일반사항 ~ 2. 중요한 회계정책 전)"""
    start = next((i for i, p in enumerate(doc) if _page_title(p).startswith("주석")), None)
    if start is None:
        return ""
    text = "".join(doc[i].get_text() for i in range(start, min(start + 2, doc.page_count)))
    end = re.search(r"\n\s*2\s*[\.-]?\s*(중요한\s*회계정책|재무제표\s*작성\s*기준)", text)
    return text[:end.start()] if end else text[:2000]


def business_profile(notes_intro):
    """→ {"purpose": 사업 목적 문장, "industry": '도매' | '제조' | None}"""
    text = re.sub(r"\s+", " ", notes_intro)
    m = PURPOSE_SENTENCE.search(text)
    purpose = m.group(0).strip() if m else None
    if purpose:   # 문장 앞에 붙어 나온 주석 제목('1. 일반 사항', '1-3. 주요 사업내용') 떼기
        purpose = re.sub(r"^[\d\-\.\s]*(일반\s*사항|회사의\s*개요|주요\s*사업\s*내용)\s*", "", purpose)
    industry = None
    if purpose:
        if MANUFACTURING.search(purpose):
            industry = "제조"
        elif WHOLESALE.search(purpose):
            industry = "도매"
    return {"purpose": purpose, "industry": industry}


def _extract_audit_hours(doc):
    """외부감사 실시내용의 '감사' 시간 합계(당기, 전기)

    이 표는 선 인식이 불안정해 텍스트 순서로 읽는다:
    '감사' 다음에 (당기, 전기) 쌍이 인력 구분별로 나열되고 마지막 쌍이 합계.
    """
    for page in doc:
        text = page.get_text()
        if "감사참여자" not in text or "투입시" not in text:
            continue
        lines = [l.strip() for l in text.split("\n")]
        try:
            idx = lines.index("감사", lines.index("분ㆍ반기검토"))
        except ValueError:
            return None
        nums = []
        for l in lines[idx + 1:]:
            if l == "합계":
                break
            nums.append(parse_amount(l) or 0)
        if len(nums) >= 2 and len(nums) % 2 == 0:
            return {"당기": nums[-2], "전기": nums[-1]}
    return None


# ===== 표준 계정 추출 =====

def _with_sections(rows):
    """행마다 속한 재무상태표 구간(유동부채 등)을 붙인다"""
    section, out = None, []
    for r in rows:
        if r["account"] in BS_SECTIONS:
            section = r["account"]
        out.append((section, r))
    return out


def _find(rows, candidates):
    """후보 순서대로 첫 일치 행. '구간:계정' 후보는 그 구간 안에서만 찾는다"""
    sectioned = _with_sections(rows)
    for cand in candidates:
        section, _, name = cand.rpartition(":")
        for sec, r in sectioned:
            if r["account"] == name and r["values"] and (not section or sec == section):
                return r
    return None


def standardize(statements):
    """표준 키 → {기간: 금액}"""
    std = {}
    for stype, mapping in STANDARD_ACCOUNTS.items():
        rows = statements.get(stype, {}).get("rows", [])
        for key, cands in mapping.items():
            r = _find(rows, cands)
            if r is None:
                continue
            vals = dict(r["values"])
            if key in EXPENSE_KEYS:
                vals = {p: abs(v) for p, v in vals.items() if v is not None}
            std[key] = vals

    # 법인세비용: 비용을 양수로 표기하는 문서와 괄호로 표기하는 문서가 섞여 있다.
    # 매출원가 부호로 문서의 표기 관례를 판별해 '비용 = 양수'로 통일한다.
    is_rows = statements.get("IS", {}).get("rows", [])
    cogs = _find(is_rows, STANDARD_ACCOUNTS["IS"]["cost_of_sales"])
    signed_expenses = cogs is not None and any(
        v is not None and v < 0 for v in cogs["values"].values())
    if "income_tax" in std and signed_expenses:
        std["income_tax"] = {p: -v for p, v in std["income_tax"].items()}

    # CAPEX: 현금흐름표의 유형자산(및 세부 자산) 취득 합계
    capex = {}
    for r in statements.get("CF", {}).get("rows", []):
        if CAPEX_PATTERN.match(r["account"]):
            for p, v in r["values"].items():
                if v is not None:
                    capex[p] = capex.get(p, 0) + abs(v)
    if capex:
        std["capex"] = capex
    return std


# ===== 검증 =====

def validate(std, tol=1):
    """회계 항등식으로 추출 결과를 교차 검증 (파싱 오류 탐지)"""
    checks = []

    def chk(name, lhs, rhs, period):
        if lhs is None or rhs is None:
            return
        checks.append({"check": name, "period": period, "lhs": lhs, "rhs": rhs,
                       "ok": abs(lhs - rhs) <= tol})

    def g(key, p):
        return std.get(key, {}).get(p)

    periods = set()
    for v in std.values():
        periods.update(v.keys())
    for p in sorted(periods):
        ta, tl, te = g("total_assets", p), g("total_liabilities", p), g("total_equity", p)
        if tl is not None and te is not None:
            chk("자산총계 = 부채총계 + 자본총계", ta, tl + te, p)
        chk("자산총계 = 부채및자본총계", ta, g("total_liabilities_and_equity", p), p)
        ca, nca = g("current_assets", p), g("non_current_assets", p)
        if ca is not None and nca is not None:
            chk("자산총계 = 유동자산 + 비유동자산", ta, ca + nca, p)
        rev, cogs = g("revenue", p), g("cost_of_sales", p)
        if rev is not None and cogs is not None:
            chk("매출총이익 = 매출 - 매출원가", g("gross_profit", p), rev - cogs, p)
        gp, sga = g("gross_profit", p), g("sga", p)
        if gp is not None and sga is not None:
            chk("영업이익 = 매출총이익 - 판관비", g("operating_income", p), gp - sga, p)
        pti, tax = g("pretax_income", p), g("income_tax", p)
        if pti is not None and tax is not None:
            chk("당기순이익 = 세전이익 - 법인세", g("net_income", p), pti - tax, p)
        chk("기말현금(CF) = 현금및현금성자산(BS)", g("cash_end", p), g("cash", p), p)
    return checks


# ===== 재무비율 =====

def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def compute_ratios(std, period="당기", prev="전기", days=365, prev_days=365):
    g = lambda k, p=period: std.get(k, {}).get(p)
    # 전기가 비정상 기간(신설/분할/결산월 변경)이면 성장률은 비교 불가
    comparable = prev_days >= days * 0.9
    borrowings = sum(v for v in (
        g("short_term_borrowings"), g("current_portion_ltd"), g("long_term_borrowings"),
        g("bonds"), g("current_lease_liabilities"), g("non_current_lease_liabilities")) if v)
    interest = g("interest_expense") or g("interest_paid")
    cfo, capex = g("cfo"), g("capex")
    ratios = {
        "부채비율(%)": _div(g("total_liabilities"), g("total_equity")),
        "유동비율(%)": _div(g("current_assets"), g("current_liabilities")),
        "차입금의존도(%)": _div(borrowings, g("total_assets")),
        "매출총이익률(%)": _div(g("gross_profit"), g("revenue")),
        "영업이익률(%)": _div(g("operating_income"), g("revenue")),
        "순이익률(%)": _div(g("net_income"), g("revenue")),
        "ROE(%)": _div(g("net_income"), g("total_equity")),
        "ROA(%)": _div(g("net_income"), g("total_assets")),
        "매출성장률(%)": (_div(g("revenue"), g("revenue", prev)) - 1)
        if g("revenue", prev) and comparable else None,
    }
    ratios = {k: (v * 100 if v is not None else None) for k, v in ratios.items()}
    ratios["이자보상배율(배)"] = _div(g("operating_income"), interest)
    ratios["매출채권회전일수"] = _div((g("receivables") or 0) * days, g("revenue"))
    ratios["재고자산회전일수"] = _div((g("inventories") or 0) * days, g("cost_of_sales"))
    ratios["매입채무회전일수"] = _div((g("payables") or 0) * days, g("cost_of_sales"))
    if None not in (ratios["매출채권회전일수"], ratios["재고자산회전일수"], ratios["매입채무회전일수"]):
        ratios["현금전환주기(일)"] = (ratios["매출채권회전일수"] + ratios["재고자산회전일수"]
                                - ratios["매입채무회전일수"])
    ratios["잉여현금흐름(FCF)"] = cfo - capex if cfo is not None and capex is not None else None
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in ratios.items()}


# ===== 진입점 =====

def parse_audit_report(path):
    doc = pymupdf.open(path)
    statements = extract_statements(doc)
    std = standardize(statements)
    meta = extract_metadata(doc)
    periods = meta.get("periods", {})
    days = periods.get("당기", {}).get("days", 365)
    prev_days = periods.get("전기", {}).get("days", days)
    warnings = []
    if prev_days < days * 0.9:
        warnings.append(f"전기 회계기간이 {prev_days}일로 당기({days}일)와 달라 "
                        "성장률 등 기간 비교가 불가합니다.")
    return {
        "meta": meta,
        "statements": {k: {"pages": v["pages"], "periods": v["periods"],
                           "row_count": len(v["rows"])} for k, v in statements.items()},
        "standard": std,
        "validation": validate(std),
        "ratios": compute_ratios(std, days=days, prev_days=prev_days),
        "warnings": warnings,
        "_raw": statements,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python disclosure_parser.py <감사보고서.pdf> [...]")
        sys.exit(1)
    for pdf in sys.argv[1:]:
        result = parse_audit_report(pdf)
        result.pop("_raw")
        print(json.dumps(result, ensure_ascii=False, indent=2))
