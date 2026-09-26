# credit_export/scoring.py
# 감사보고서 파싱 결과 → 신용점수(0~100) · 등급(AAA~D)
#
# 범주는 ar-dashboard 0008 주석에 적힌 5축(성장성/수익성/재무구조/부채상환능력/활동성)을 따른다.
# 대시보드는 category_scores 를 {범주: {score, max, weight}} 로 읽는다(lib/credit/model.ts).
#
# ⚠️ 초안 스코어카드: 기준값·가중치는 설계 예시이며 실제 부도·연체 이력으로 검증(백테스트)한
#    모형이 아니다. 운영 전 내부 여신 기준에 맞춰 조정할 것.

from disclosure_parser import compute_ratios

CATEGORY_WEIGHTS = {
    "성장성": 15,
    "수익성": 25,
    "재무구조": 25,
    "부채상환능력": 25,
    "활동성": 10,
}

# (지표, 범주, 양호 기준, 위험 기준) — 양호 이상 100점, 위험 이하 0점, 사이는 선형.
# 양호 < 위험이면 낮을수록 좋은 지표.
METRICS = [
    ("매출성장률(%)", "성장성", 10, -10),
    ("총자산증가율(%)", "성장성", 10, -10),
    ("영업이익률(%)", "수익성", 10, 0),
    ("ROA(%)", "수익성", 8, 0),
    ("부채비율(%)", "재무구조", 100, 400),
    ("유동비율(%)", "재무구조", 150, 80),
    ("차입금의존도(%)", "재무구조", 10, 50),
    ("이자보상배율(배)", "부채상환능력", 5, 1),
    ("차입금상환기간(년)", "부채상환능력", 2, 8),
    ("매출채권회전일수", "활동성", 60, 180),
    ("재고자산회전일수", "활동성", 60, 180),
]

# 업종별 기준 덮어쓰기 — 의약품 도매처럼 매입채무가 큰 저마진 업종은 기본 기준으로 보면
# 부채비율·이익률에서 구조적으로 깎인다(지오영 부채비율 290%, 영업이익률 2%).
# 키는 한국표준산업분류(KSIC) 코드 앞자리 — dart_companies.induty_code 와 맞춘다.
INDUSTRY_THRESHOLDS = {
    "46": {   # 도매 및 상품 중개업
        "부채비율(%)": (250, 600),
        "영업이익률(%)": (3, 0),
        "ROA(%)": (4, 0),
        "매출채권회전일수": (90, 180),
        "재고자산회전일수": (45, 120),
    },
}

GRADES = [
    (90, "AAA"), (80, "AA"), (70, "A"), (60, "BBB"),
    (50, "BB"), (40, "B"), (30, "CCC"), (20, "CC"), (0, "C"),
]
GRADE_ORDER = [g for _, g in GRADES] + ["D"]


def _linear(value, good, bad):
    if value is None:
        return None
    if value == float("inf"):
        return 0.0 if good < bad else 100.0
    t = (value - bad) / (good - bad)
    return round(max(0.0, min(1.0, t)) * 100, 1)


def grade_for(score):
    for cutoff, grade in GRADES:
        if score >= cutoff:
            return grade
    return "C"


def cap_grade(grade, floor):
    """grade 가 floor 보다 좋으면 floor 로 낮춘다"""
    return floor if GRADE_ORDER.index(grade) < GRADE_ORDER.index(floor) else grade


def thresholds_for(induty_code):
    code = str(induty_code or "")
    for prefix, overrides in INDUSTRY_THRESHOLDS.items():
        if code.startswith(prefix):
            return overrides
    return {}


def ratio_table(report, period="당기", prev="전기"):
    """스코어카드 지표값 (disclosure_parser 비율 + 추가 지표)"""
    std = report["standard"]
    periods = report["meta"].get("periods", {})
    days = periods.get(period, {}).get("days", 365)
    prev_days = periods.get(prev, {}).get("days", days)
    comparable = prev_days >= days * 0.9
    ratios = compute_ratios(std, period=period, prev=prev, days=days, prev_days=prev_days)
    g = lambda k, p=period: std.get(k, {}).get(p)

    # 총자산증가율: 재무상태표는 시점 값이라 전기가 짧아도(신설 법인) 비교 자체는 되지만,
    # 기간이 1년이 아니면 '연간 성장'이 아니므로 성장성에서는 뺀다
    ta, ta_prev = g("total_assets"), g("total_assets", prev)
    ratios["총자산증가율(%)"] = (round((ta / ta_prev - 1) * 100, 2)
                            if ta and ta_prev and comparable else None)

    borrowings = sum(v for v in (
        g("short_term_borrowings"), g("current_portion_ltd"), g("long_term_borrowings"),
        g("bonds"), g("current_lease_liabilities"), g("non_current_lease_liabilities")) if v)
    cfo = g("cfo")
    if cfo is None:
        ratios["차입금상환기간(년)"] = None
    elif borrowings == 0:
        ratios["차입금상환기간(년)"] = 0.0
    elif cfo > 0:
        ratios["차입금상환기간(년)"] = round(borrowings / cfo, 2)
    else:
        ratios["차입금상환기간(년)"] = float("inf")   # 영업현금흐름으로 상환 불가
    ratios["총차입금"] = borrowings
    return ratios


def score_report(report, induty_code=None):
    """파싱된 감사보고서 1건 → {total_score, credit_grade, category_scores, ratios, flags}"""
    meta = report["meta"]
    overrides = thresholds_for(induty_code)
    values = ratio_table(report)

    metrics = []
    for name, category, good, bad in METRICS:
        good, bad = overrides.get(name, (good, bad))
        metrics.append({"범주": category, "지표": name, "값": values.get(name),
                        "점수": _linear(values.get(name), good, bad),
                        "양호기준": good, "위험기준": bad})

    category_scores = {}
    for category, weight in CATEGORY_WEIGHTS.items():
        scores = [m["점수"] for m in metrics if m["범주"] == category and m["점수"] is not None]
        category_scores[category] = {
            "score": round(sum(scores) / len(scores), 1) if scores else None,
            "max": 100,
            "weight": weight,
        }
    rated = {k: v for k, v in category_scores.items() if v["score"] is not None}
    total_weight = sum(v["weight"] for v in rated.values())
    total = (round(sum(v["score"] * v["weight"] for v in rated.values()) / total_weight, 1)
             if total_weight else None)

    flags = []
    grade = grade_for(total) if total is not None else None

    # 추출 검증에 실패한 숫자로는 등급을 내지 않는다 — 대시보드에서 '미평가'로 보인다
    failed = [c for c in report.get("validation", []) if not c["ok"]]
    if failed:
        flags.append(f"재무제표 추출 검증 {len(failed)}건 실패 — 수치 수동 확인 전까지 평가 보류")
        total, grade = None, None

    opinion = meta.get("opinion")
    if grade:
        if opinion in ("부적정", "의견거절"):
            grade = "D"
            flags.append(f"감사의견 {opinion} → D")
        elif opinion == "한정":
            grade = cap_grade(grade, "BB")
            flags.append("감사의견 한정 → BB 이하")
        if meta.get("going_concern_uncertainty"):
            grade = cap_grade(grade, "CCC")
            flags.append("계속기업 존속능력 불확실성 → CCC 이하")
        equity = report["standard"].get("total_equity", {}).get("당기")
        if equity is not None and equity <= 0:
            grade = cap_grade(grade, "CCC")
            flags.append("완전자본잠식 → CCC 이하")

    hours = meta.get("audit_hours") or {}
    if hours.get("당기") and hours.get("전기") and hours["당기"] < hours["전기"] * 0.7:
        flags.append(f"감사시간 {(1 - hours['당기'] / hours['전기']) * 100:.0f}% 감소 "
                     f"({hours['전기']:,}h → {hours['당기']:,}h)")
    if total_weight and total_weight < sum(CATEGORY_WEIGHTS.values()):
        missing = [k for k in CATEGORY_WEIGHTS if k not in rated]
        flags.append(f"평가 불가 범주 제외: {', '.join(missing)}")
    flags.extend(report.get("warnings", []))

    return {
        "total_score": total,
        "credit_grade": grade,
        "category_scores": category_scores,
        "metrics": metrics,
        "values": values,
        "flags": flags,
    }
