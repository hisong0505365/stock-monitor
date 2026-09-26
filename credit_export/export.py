# credit_export/export.py
# 감사보고서 폴더 → 파싱·검증·평가 → 거래처 매칭 → ar-dashboard Supabase(0008) 적재
#
#   python -m credit_export.export --folder ./audit_reports --org 1100 --org 1200
#       기본은 미리보기(dry-run): 올릴 행을 export_preview.json 에 쓰고 요약만 출력한다.
#   python -m credit_export.export --folder ./audit_reports --org 1100 --upload
#       실제로 dart_companies → dart_evaluations → dart_partner_links 순서로 upsert 한다.
#
# 환경변수(.env 가능): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENDART_API_KEY(선택)
#
# 기존 데이터 보호 (dart-analyzer 가 같은 테이블에 쓴다)
#   - 평가: 같은 (corp_code, 결산일)에 다른 원본 파일의 평가가 있으면 건너뜀 (--overwrite 로 교체)
#   - 매칭: 이미 matched 인 거래처는 건너뜀 (--overwrite-links 로 교체). no_match 였던 거래처는
#           감사보고서로 새로 찾았으므로 갱신. match_type='수동' 은 어떤 옵션으로도 건드리지 않음
#   - 회사: 이미 있으면 최신 보고서 정보만 갱신 (다른 컬럼은 그대로)

import argparse
import csv
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from credit_export.corp_codes import (
    CorpCodeResolver, download_corp_codes, fetch_company, load_corp_map,
)
from credit_export.matching import match_customers
from credit_export.scoring import score_report
from credit_export.supabase_rest import SupabaseRest
from disclosure_parser import parse_audit_report

BS_ITEMS = [
    ("자산총계", "total_assets"), ("부채총계", "total_liabilities"), ("자본총계", "total_equity"),
    ("현금및현금성자산", "cash"), ("매출채권", "receivables"), ("재고자산", "inventories"),
    ("매입채무", "payables"),
]
FLOW_ITEMS = [
    ("매출액", "revenue"), ("매출원가", "cost_of_sales"), ("매출총이익", "gross_profit"),
    ("판매비와관리비", "sga"), ("영업이익", "operating_income"),
    ("법인세비용차감전순이익", "pretax_income"), ("당기순이익", "net_income"),
    ("영업활동현금흐름", "cfo"), ("설비투자(CAPEX)", "capex"),
]
EXTRA_RATIOS = ["매출총이익률(%)", "순이익률(%)", "ROE(%)", "매입채무회전일수",
                "현금전환주기(일)", "잉여현금흐름(FCF)", "총차입금"]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(v):
    """JSON 에 못 싣는 값 정리 — inf 는 '상환불가' 로, 소수는 둘째 자리까지"""
    if isinstance(v, float):
        if math.isinf(v):
            return "상환불가(영업CF≤0)"
        if math.isnan(v):
            return None
        return round(v, 2)
    return v


# ===== 행 만들기 =====

def build_financials(report):
    """{결산일: {항목: 원}} — 대시보드 normalizeFinancials 의 '기간 우선' 모양

    전기가 1년이 아니면(신설·분할 법인) 손익·현금흐름은 빼고 재무상태표만 싣는다 —
    28일치 매출을 연간 매출 옆에 두면 대시보드가 '전기 대비 +1,268%' 를 그린다.
    """
    std, periods = report["standard"], report["meta"].get("periods", {})
    cur = periods.get("당기")
    if not cur:
        return {}
    prev = periods.get("전기")
    out = {}
    for label, info in (("당기", cur), ("전기", prev)):
        if not info:
            continue
        flow = label == "당기" or info["days"] >= cur["days"] * 0.9
        items = BS_ITEMS + (FLOW_ITEMS if flow else [])
        row = {name: std.get(key, {}).get(label) for name, key in items}
        row = {k: v for k, v in row.items() if v is not None}
        if row:
            out[info["end"]] = row
    return out


def build_ratios(report, score):
    """{범주: {지표: 값}} — 대시보드 normalizeRatios 의 '한 단계 묶음' 모양"""
    grouped = {}
    for m in score["metrics"]:
        grouped.setdefault(m["범주"], {})[m["지표"]] = _clean(m["값"])
    grouped["기타"] = {k: _clean(score["values"].get(k)) for k in EXTRA_RATIOS}
    meta = report["meta"]
    hours = meta.get("audit_hours") or {}
    business = meta.get("business") or {}
    grouped["감사"] = {
        "감사의견": meta.get("opinion"),
        "계속기업 불확실성": "있음" if meta.get("going_concern_uncertainty") else "없음",
        "강조사항": "있음" if meta.get("has_emphasis_of_matter") else "없음",
        "업종(보고서)": business.get("industry"),
        "사업목적": (business.get("purpose") or "")[:120] or None,
        "감사인": meta.get("auditor"),
        "회계기준": meta.get("gaap"),
        "감사보고서일": meta.get("report_date"),
        "감사시간(당기)": hours.get("당기"),
        "감사시간(전기)": hours.get("전기"),
        "추출검증": f"{sum(c['ok'] for c in report['validation'])}/{len(report['validation'])} 통과",
        "경고": " / ".join(score["flags"]) or None,
    }
    return grouped


def build_evaluation(report, corp_code, score):
    meta = report["meta"]
    return {
        "corp_code": corp_code,
        "period_end": meta["period_end"],
        "report_type": "감사보고서",
        "fiscal_term": str(meta.get("fiscal_term")) if meta.get("fiscal_term") else None,
        "consolidated": bool(meta.get("consolidated")),
        "total_score": score["total_score"],
        "credit_grade": score["credit_grade"],
        "category_scores": score["category_scores"],
        "ratios": build_ratios(report, score),
        "financials": build_financials(report),
        "source_file": report["file"],
        "analyzed_at": now_iso(),
    }


def build_company(report, corp_code, profile=None):
    meta = report["meta"]
    row = {
        "corp_code": corp_code,
        "corp_name": (profile or {}).get("corp_name") or meta["company"],
        "latest_report_name": f"감사보고서 ({meta['period_end'][:7]})",
        "latest_report_date": meta.get("report_date"),
        "updated_at": now_iso(),
    }
    for k, v in (profile or {}).items():
        if v and k not in row:
            row[k] = v
    return row


def build_link(customer, corp_code):
    t = now_iso()
    return {
        "org_code": customer["org_code"],
        "customer_code": customer["code"],
        "partner_name": customer["name"],
        "corp_code": corp_code,
        "status": "matched",
        "match_type": customer["match_type"],
        "score": customer["score"],
        "reason": None,
        "checked_at": t,
        "updated_at": t,
    }


# ===== 폴더 안 중복 =====

def dedupe_reports(resolved):
    """같은 (고유번호, 결산일) 보고서가 여럿이면 하나만 남긴다

    한 번의 upsert 에 같은 키가 두 번 들어가면 PostgreSQL 이 요청 전체를 거절한다
    ("ON CONFLICT DO UPDATE command cannot affect row a second time") — 폴더에 '보고서 (1).pdf'
    사본이 섞이는 것만으로 적재가 통째로 실패했다(2026-09-26 통합 테스트).
    우선순위: 별도 > 연결 (거래처 법인 자체의 신용을 본다) → 감사보고서일이 늦은 것 → 파일명 순.
    resolved: [(report, corp_code, source)] → (남긴 것, [(뺀 파일, 남긴 파일, 사유)])
    """
    groups = {}
    for item in resolved:
        r, corp_code, _ = item
        groups.setdefault((corp_code, r["meta"]["period_end"]), []).append(item)
    keep, dropped = [], []
    for items in groups.values():
        items.sort(key=lambda it: (bool(it[0]["meta"].get("consolidated")),
                                   _neg_date(it[0]["meta"].get("report_date")),
                                   bool(COPY_MARK.search(it[0]["file"])), it[0]["file"]))
        keep.append(items[0])
        for other in items[1:]:
            why = ("연결 — 별도 감사보고서를 씀" if other[0]["meta"].get("consolidated")
                   and not items[0][0]["meta"].get("consolidated") else "같은 결산의 중복 파일")
            dropped.append((other[0]["file"], items[0][0]["file"], why))
    return keep, dropped


# '보고서 (1).pdf', '보고서 - 복사본.pdf', 'report copy.pdf' — 동점이면 원본 이름을 남긴다.
# 사본 이름이 source_file 로 남으면, 사본을 지운 뒤 다시 돌릴 때 '다른 원본의 평가'로 보여 갱신이 막힌다
COPY_MARK = re.compile(r"\(\d+\)\.pdf$|복사본|사본|copy", re.IGNORECASE)


def _neg_date(d):
    """늦은 날짜가 앞에 오도록 하는 정렬 키 ('2026-03-23' → -20260323, 없으면 맨 뒤)"""
    return -int(d.replace("-", "")) if d else 0


# ===== 기존 데이터 보호 =====

def filter_evaluations(rows, existing, overwrite):
    """existing: {(corp_code, period_end): source_file}"""
    keep, skipped = [], []
    for r in rows:
        other = existing.get((r["corp_code"], r["period_end"]))
        if other is not None and other != r["source_file"] and not overwrite:
            skipped.append((r, f"이미 다른 평가 있음({other}) — --overwrite 로 교체"))
        else:
            keep.append(r)
    return keep, skipped


def filter_links(rows, existing, overwrite):
    """existing: {(org_code, customer_code): {status, match_type, corp_code}}"""
    keep, skipped = [], []
    for r in rows:
        old = existing.get((r["org_code"], r["customer_code"]))
        if old is None or old["status"] == "no_match":
            keep.append(r)
        elif old.get("match_type") == "수동":
            skipped.append((r, "수동 매칭 — 변경 안 함"))
        elif old.get("corp_code") == r["corp_code"]:
            skipped.append((r, "이미 같은 기업으로 매칭됨"))
        elif overwrite:
            keep.append(r)
        else:
            skipped.append((r, f"이미 다른 기업({old.get('corp_code')})으로 매칭 — --overwrite-links 로 교체"))
    return keep, skipped


# ===== 입력 =====

def load_env(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_customers_csv(path, orgs):
    """CSV: org_code,code,name (Supabase 없이 미리보기할 때)"""
    with open(path, encoding="utf-8-sig") as f:
        rows = [{"org_code": r["org_code"].strip(), "code": r["code"].strip(),
                 "name": r["name"].strip()} for r in csv.DictReader(f)]
    return [r for r in rows if not orgs or r["org_code"] in orgs]


def parse_folder(folder):
    reports, errors = [], []
    for pdf in sorted(p for p in Path(folder).iterdir() if p.suffix.lower() == ".pdf"):
        try:
            r = parse_audit_report(str(pdf))
            r.pop("_raw", None)
            r["file"] = pdf.name
            if not r["meta"].get("company") or not r["meta"].get("period_end"):
                errors.append((pdf.name, "감사보고서 표지(회사명·회계기간)를 찾지 못함"))
            elif "revenue" not in r["standard"] or "total_assets" not in r["standard"]:
                errors.append((pdf.name, "재무제표(매출액·자산총계)를 찾지 못함"))
            else:
                reports.append(r)
        except Exception as e:   # 손상 파일, 감사보고서가 아닌 PDF 등
            errors.append((pdf.name, f"{type(e).__name__}: {e}"))
    return reports, errors


# ===== 실행 =====

def run(args, db=None, dart_session=None):
    reports, parse_errors = parse_folder(args.folder)
    api_key = os.environ.get("OPENDART_API_KEY")

    existing_companies = db.select_all("dart_companies", "corp_code,corp_name,induty_code",
                                       order="corp_code") if db else []
    dart_list = download_corp_codes(api_key, dart_session) if api_key else []
    resolver = CorpCodeResolver(load_corp_map(args.corp_map) if args.corp_map else {},
                                existing_companies, dart_list)
    industry = {c["corp_code"]: c.get("induty_code") for c in existing_companies}
    known = {c["corp_code"] for c in existing_companies}

    companies, evaluations, unresolved, summary = {}, [], [], []
    resolved = []
    for r in reports:
        corp_code, source = resolver.resolve(r["meta"]["company"], r["file"])
        if corp_code:
            resolved.append((r, corp_code, source))
        else:
            unresolved.append((r["file"], r["meta"]["company"], source))
    resolved, duplicates = dedupe_reports(resolved)

    latest = {}   # 회사명 → 가장 최근 결산 보고서 (거래처 매칭·회사 정보는 최신 기준)
    for r, corp_code, source in resolved:
        name = r["meta"]["company"]
        profile = None
        if api_key and corp_code not in known:
            profile = fetch_company(api_key, corp_code, dart_session)
            if profile and profile.get("induty_code"):
                industry[corp_code] = profile["induty_code"]
        score = score_report(r, industry.get(corp_code))
        evaluations.append(build_evaluation(r, corp_code, score))
        if name not in latest or r["meta"]["period_end"] > latest[name][0]["meta"]["period_end"]:
            latest[name] = (r, corp_code, profile)
        summary.append({"file": r["file"], "company": name, "corp_code": corp_code,
                        "corp_source": source, "period_end": r["meta"]["period_end"],
                        "grade": score["credit_grade"], "score": score["total_score"],
                        "validation": f"{sum(c['ok'] for c in r['validation'])}/{len(r['validation'])}",
                        "flags": score["flags"]})
    existing_names = {c["corp_code"]: c["corp_name"] for c in existing_companies}
    for name, (r, corp_code, profile) in latest.items():
        row = build_company(r, corp_code, profile)
        if corp_code in known:
            # 기존 회사는 최신 보고서 정보만 갱신. corp_name 은 NOT NULL 이라 upsert 의 insert
            # 단계에서도 필요하므로 기존 이름을 그대로 싣는다(바꾸지 않는다)
            row = {"corp_code": corp_code, "corp_name": existing_names[corp_code],
                   "latest_report_name": row["latest_report_name"],
                   "latest_report_date": row["latest_report_date"],
                   "updated_at": row["updated_at"]}
        companies[corp_code] = row

    # 거래처 매칭 — 파싱 회사명과 DART 공식 회사명 둘 다로 맞춘다
    orgs = args.org or []
    if args.customers:
        customers = load_customers_csv(args.customers, orgs)
    elif db:
        customers = [c for org in orgs for c in db.select_all(
            "customers", "org_code,code,name", order="code", filters={"org_code": f"eq.{org}"})]
    else:
        customers = []
    name_to_corp = {}
    for name, (r, corp_code, profile) in latest.items():
        name_to_corp[name] = corp_code
        if profile and profile.get("corp_name"):
            name_to_corp[profile["corp_name"]] = corp_code
    matched = match_customers(customers, list(name_to_corp))
    links = [build_link(m, name_to_corp[m["company"]]) for m in matched]

    # 기존 데이터 보호
    skipped = []
    if db:
        codes = sorted({e["corp_code"] for e in evaluations})
        existing_eval = {}
        for i in range(0, len(codes), 200):
            chunk = ",".join(codes[i:i + 200])
            for row in db.select_all("dart_evaluations", "corp_code,period_end,source_file",
                                     filters={"corp_code": f"in.({chunk})"}):
                existing_eval[(row["corp_code"], row["period_end"])] = row["source_file"]
        evaluations, s1 = filter_evaluations(evaluations, existing_eval, args.overwrite)
        existing_links = {}
        for org in orgs:
            for row in db.select_all("dart_partner_links", "org_code,customer_code,corp_code,status,match_type",
                                     order="customer_code", filters={"org_code": f"eq.{org}"}):
                existing_links[(row["org_code"], row["customer_code"])] = row
        links, s2 = filter_links(links, existing_links, args.overwrite_links)
        skipped = [(r.get("source_file") or r.get("customer_code"), why) for r, why in s1 + s2]

    preview = {
        "summary": summary,
        "parse_errors": parse_errors,
        "unresolved_corp_codes": unresolved,
        "duplicates": duplicates,
        "corp_code_conflicts": [
            f"{name}: corp-map {code} ≠ Supabase 기존 {', '.join(existing)} — 같은 회사가 둘로 갈라질 수 있음"
            for name, code, existing in resolver.conflicts],
        "skipped": skipped,
        "dart_companies": list(companies.values()),
        "dart_evaluations": evaluations,
        "dart_partner_links": links,
    }
    Path(args.out).write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.upload:
        if not db:
            raise SystemExit("--upload 에는 SUPABASE_URL · SUPABASE_SERVICE_ROLE_KEY 가 필요합니다")
        for row in companies.values():   # 행마다 컬럼이 달라 한 건씩 (PostgREST 일괄 upsert 는 키가 같아야 함)
            db.upsert("dart_companies", [row], on_conflict="corp_code")
        db.upsert("dart_evaluations", evaluations, on_conflict="corp_code,period_end")
        db.upsert("dart_partner_links", links, on_conflict="org_code,customer_code")
    return preview


def print_summary(preview, uploaded):
    print(f"\n감사보고서 {len(preview['summary'])}건 평가 · 파싱 실패 {len(preview['parse_errors'])}건 · "
          f"고유번호 미확인 {len(preview['unresolved_corp_codes'])}건")
    for s in preview["summary"]:
        print(f"  {s['company']:<16} {s['period_end']}  {s['grade'] or '보류':<4} "
              f"{s['score'] if s['score'] is not None else '-':>5}  검증 {s['validation']}  "
              f"({s['corp_code']}, {s['corp_source']})")
        for f in s["flags"]:
            print(f"      ⚠ {f}")
    for f, why in preview["parse_errors"]:
        print(f"  ✕ {f}: {why}")
    for f, name, why in preview["unresolved_corp_codes"]:
        print(f"  ? {name} ({f}): {why}")
    for msg in preview.get("corp_code_conflicts", []):
        print(f"  ⚠ 고유번호 충돌 {msg}")
    for dropped, kept, why in preview.get("duplicates", []):
        print(f"  = {dropped}: {why} ({kept} 사용)")
    links = preview["dart_partner_links"]
    print(f"\n거래처 매칭 {len(links)}건 (유사 {sum(l['match_type'] == '유사' for l in links)}건은 대시보드에서 '확인 필요')")
    for l in links:
        print(f"  {l['org_code']} {l['customer_code']:<10} {l['partner_name']:<20} → {l['corp_code']} "
              f"[{l['match_type']} {l['score']}]")
    for key, why in preview["skipped"]:
        print(f"  건너뜀 {key}: {why}")
    print("\n업로드 완료" if uploaded else "\n미리보기만 했습니다 (--upload 로 실제 반영)")


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(description="감사보고서 폴더 → 매출채권 대시보드 기업신용평가")
    ap.add_argument("--folder", required=True, help="감사보고서 PDF 폴더")
    ap.add_argument("--org", action="append", help="거래처를 맞출 영업조직(1100/1200/1300), 여러 번 가능")
    ap.add_argument("--customers", help="거래처 CSV(org_code,code,name) — Supabase 대신")
    ap.add_argument("--corp-map", help="CSV(name,corp_code) — 회사명·파일명별 DART 고유번호 지정")
    ap.add_argument("--out", default="export_preview.json", help="미리보기 JSON 경로")
    ap.add_argument("--upload", action="store_true", help="Supabase 에 실제로 반영")
    ap.add_argument("--overwrite", action="store_true", help="다른 원본의 같은 결산 평가를 교체")
    ap.add_argument("--overwrite-links", action="store_true", help="다른 기업으로 매칭된 거래처를 교체")
    args = ap.parse_args(argv)

    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    db = SupabaseRest(url, key) if url and key else None
    if args.upload and not db:
        ap.error("--upload 에는 SUPABASE_URL · SUPABASE_SERVICE_ROLE_KEY 가 필요합니다")
    preview = run(args, db)
    print_summary(preview, args.upload)


if __name__ == "__main__":
    sys.exit(main())
