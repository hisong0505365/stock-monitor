# 감사보고서 폴더 → ar-dashboard DB 적재 통합 테스트
#
# 필요한 것
#   TEST_PG_DSN   ar-dashboard supabase/migrations 를 적용한 PostgreSQL (Supabase auth 스텁 포함)
#                 — 이 테스트는 dart_* · customers 테이블을 비우고 다시 채운다. 운영 DB 금지.
#   AUDIT_PDF_DIR 감사보고서 PDF — 지오영·알보젠코리아·아주약품·백제약품 4건은 반드시.
#                 그 밖의 보고서(고유번호를 못 찾는 회사)는 올리지 않고 보류돼야 한다
import argparse
import os
import random
import uuid
from pathlib import Path

import pytest

pytest.importorskip("psycopg")
from credit_export.export import run  # noqa: E402
from tests.pg_rest import PgRest  # noqa: E402

DSN = os.environ.get("TEST_PG_DSN")
PDF_DIR = os.environ.get("AUDIT_PDF_DIR")
pytestmark = pytest.mark.skipif(not DSN or not PDF_DIR,
                                reason="TEST_PG_DSN 과 AUDIT_PDF_DIR 이 필요합니다")

# 감사보고서에서 고유번호를 못 찾는 회사는 올리지 않는다 — 테스트용 고정 번호
CORP = {"지오영": "00100001", "알보젠": "00100002", "아주": "00100003", "백제": "00100004"}

# 실제로 있을 법한 이름 — 붙어야 하는 것과 붙으면 안 되는 것
REAL = [
    ("1100", "R001", "(주)지오영"), ("1100", "R002", "지오영 부산지점"),
    ("1100", "R003", "백제약품(주)대구지점"), ("1100", "R004", "백제약품(주)"),
    ("1100", "R005", "아주약품(주)"), ("1100", "R006", "알보젠코리아"),
    ("1200", "R101", "주식회사 지오영"),
]
DECOYS = [
    ("1100", "D001", "지오영약국"), ("1100", "D002", "백제약국"),
    ("1100", "D003", "(주)지오영경동"),          # 지오영 차입금 주석에 나오는 별개 법인
    ("1100", "D004", "지오영경동물류센터"),        # 별개 법인의 물류센터
    ("1100", "D005", "아주약품상사"), ("1100", "D006", "지오영케어"),
    ("1100", "D007", "백제약품의원"), ("1100", "D008", "알보젠"),
]


def _synthetic_customers(n=9500, seed=7):
    """1100 실제 분포(의원 4,489 · 약국 2,593 · 그외 1,026 · 도매 903 · 병원 378)를 본뜬 이름"""
    rng = random.Random(seed)
    first = "가나다라마바사아자차카타파하" + "강건경고공관광구국군권금기길"
    kinds = ["의원"] * 47 + ["약국"] * 27 + ["메디칼"] * 11 + ["약품"] * 10 + ["병원"] * 5
    rows = []
    for i in range(n):
        base = "".join(rng.choice(first) for _ in range(rng.choice([2, 3])))
        kind = rng.choice(kinds)
        name = f"(주){base}{kind}" if kind in ("약품", "메디칼") else f"{base}{kind}"
        rows.append(("1100", f"{100000 + i}", name))
    return rows


@pytest.fixture(scope="module")
def db():
    rest = PgRest(DSN)
    admin = PgRest(DSN, role="postgres")
    with admin.conn.cursor() as cur:
        cur.execute("truncate dart_partner_links, dart_evaluations, dart_companies cascade")
        cur.execute("delete from customers where org_code in ('1100', '1200')")
        rows = REAL + DECOYS + _synthetic_customers()
        with cur.copy("copy customers (org_code, code, name) from stdin") as cp:
            for r in rows:
                cp.write_row(r)
        # dart-analyzer 가 먼저 넣어 둔 데이터를 흉내 낸다
        cur.execute("insert into dart_companies (corp_code, corp_name, induty_code) values "
                    "(%s, '알보젠코리아(주)', '21210')", [CORP["알보젠"]])
        cur.execute("insert into dart_evaluations (corp_code, period_end, report_type, total_score, "
                    "credit_grade, category_scores, ratios, source_file) values "
                    "(%s, '2025-12-31', '감사보고서', 77, 'A', '{}', '{}', 'dart-analyzer.pdf')",
                    [CORP["알보젠"]])
        cur.execute("insert into dart_partner_links (org_code, customer_code, partner_name, corp_code, "
                    "status, match_type) values ('1100', 'R006', '알보젠코리아', %s, 'matched', '수동'), "
                    "('1100', 'R001', '(주)지오영', null, 'no_match', null)", [CORP["알보젠"]])
    return rest, admin


def _args(tmp_path, **over):
    corp_map = tmp_path / "corp_map.csv"
    corp_map.write_text("name,corp_code\n주식회사 지오영,{}\n아주약품주식회사,{}\n백제약품주식회사,{}\n"
                        .format(CORP["지오영"], CORP["아주"], CORP["백제"]), encoding="utf-8")
    base = dict(folder=PDF_DIR, org=["1100", "1200"], customers=None, corp_map=str(corp_map),
                out=str(tmp_path / "preview.json"), upload=True, overwrite=False, overwrite_links=False)
    base.update(over)
    return argparse.Namespace(**base)


def _q(admin, query, params=()):
    with admin.conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall() if cur.description else None


def test_적재_후_DB_상태(db, tmp_path):
    rest, admin = db
    preview = run(_args(tmp_path), db=rest)

    # 회사: 알보젠은 Supabase 에 있던 번호를 재사용(이름 기준), 나머지는 corp-map
    sources = {s["company"]: s["corp_source"] for s in preview["summary"]}
    assert sources["알보젠코리아 주식회사"] == "supabase"
    names = dict(_q(admin, "select corp_code, corp_name from dart_companies"))
    assert names[CORP["알보젠"]] == "알보젠코리아(주)"          # 기존 이름은 그대로
    assert set(names) == set(CORP.values())

    # 평가: 알보젠은 dart-analyzer 평가가 있어 건너뜀, 나머지 3건 적재
    evals = dict(_q(admin, "select corp_code, source_file from dart_evaluations"))
    assert evals[CORP["알보젠"]] == "dart-analyzer.pdf"
    assert len(evals) == 4
    row = _q(admin, "select total_score, credit_grade, category_scores->'수익성'->>'weight', "
                    "financials ? '2025-12-31', ratios->'감사'->>'감사의견' "
                    "from dart_evaluations where corp_code = %s", [CORP["지오영"]])[0]
    assert row[1] is not None and row[2] == "25" and row[3] is True and row[4] == "적정"

    # 매칭: 붙어야 할 것만, 수동은 보존, no_match 는 갱신
    links = {r[0]: r[1:] for r in _q(
        admin, "select customer_code, corp_code, status, match_type from dart_partner_links")}
    assert links["R006"] == (CORP["알보젠"], "matched", "수동")
    assert links["R001"] == (CORP["지오영"], "matched", "정확일치")
    assert links["R002"][2] == "유사" and links["R003"][2] == "유사"
    wrong = [(code, name) for _, code, name in DECOYS if code in links]
    assert wrong == [], f"오매칭 {wrong}"
    synthetic = [c for c in links if c.isdigit()]
    assert synthetic == [], f"합성 거래처 오매칭 {synthetic[:5]}"


def test_다시_돌려도_중복이_생기지_않는다(db, tmp_path):
    rest, admin = db
    before = [_q(admin, f"select count(*) from {t}")[0][0]
              for t in ("dart_companies", "dart_evaluations", "dart_partner_links")]
    run(_args(tmp_path), db=rest)
    after = [_q(admin, f"select count(*) from {t}")[0][0]
             for t in ("dart_companies", "dart_evaluations", "dart_partner_links")]
    assert before == after


def test_대시보드_권한으로_읽힌다(db):
    """ar-dashboard 는 anon key + RLS(승인 사용자)로 읽는다 — 같은 조건으로 조회"""
    _, admin = db
    uid = str(uuid.uuid4())
    _q(admin, "insert into auth.users (id, email) values (%s, 'v@test')", [uid])
    # 가입 트리거(0003)가 프로필을 pending 으로 만든다 — 관리자 승인처럼 approved 로 바꾼다
    _q(admin, "insert into profiles (id, display_name, role, status) values (%s, '조회', 'viewer', 'approved') "
              "on conflict (id) do update set status = 'approved', role = 'viewer'", [uid])
    with admin.conn.cursor() as cur:
        cur.execute("set role authenticated")
        cur.execute("select set_config('request.jwt.claim.sub', %s, false)", [uid])
        cur.execute("select count(*) from dart_partner_links where org_code = '1100'")
        assert cur.fetchone()[0] > 0
        cur.execute("select count(*) from dart_evaluations")
        assert cur.fetchone()[0] == 4
        cur.execute("select set_config('request.jwt.claim.sub', '', false)")   # 로그인 안 함
        cur.execute("select count(*) from dart_evaluations")
        assert cur.fetchone()[0] == 0
        cur.execute("reset role")


def test_사본과_감사보고서가_아닌_PDF가_섞인_폴더(db, tmp_path):
    """'보고서 (1).pdf' 사본이 있으면 upsert 전체가 거절되던 문제(2026-09-26)의 회귀 테스트"""
    rest, admin = db
    folder = tmp_path / "messy"
    folder.mkdir()
    for pdf in Path(PDF_DIR).glob("*.pdf"):
        (folder / pdf.name).symlink_to(pdf)
    # 적재되는 회사의 보고서를 복사해야 중복 정리를 지난다 — 이름순 첫 파일은 폴더 구성에 따라
    # 고유번호가 없는 회사일 수 있다(보류돼 중복 검사까지 가지 않음)
    geoyoung = (sorted(Path(PDF_DIR).glob("46d30305*.pdf"))
                or sorted(Path(PDF_DIR).glob("*지오영*.pdf")))[0]
    (folder / "보고서 사본 (1).pdf").symlink_to(geoyoung)
    import pymupdf
    junk = pymupdf.open()
    junk.new_page().insert_text((72, 72), "invoice")
    junk.save(folder / "invoice.pdf")

    preview = run(_args(tmp_path, folder=str(folder)), db=rest)
    assert [d[0] for d in preview["duplicates"]] == ["보고서 사본 (1).pdf"]
    assert [e[0] for e in preview["parse_errors"]] == ["invoice.pdf"]
    keys = [(e["corp_code"], e["period_end"]) for e in preview["dart_evaluations"]]
    assert len(keys) == len(set(keys))
