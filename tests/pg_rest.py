# tests/pg_rest.py
# 통합 테스트용 — SupabaseRest 와 같은 인터페이스를 실제 PostgreSQL 에 대고 흉내 낸다.
#
# 이 환경에서는 PostgREST 서버를 받을 수 없어서, PostgREST 가 요청을 SQL 로 바꾸는 방식을
# 그대로 따라 한다:
#   upsert  → INSERT … SELECT … FROM json_populate_recordset(NULL::표, 본문)
#             ON CONFLICT (충돌키) DO UPDATE SET 본문 컬럼 = EXCLUDED.컬럼   (merge-duplicates)
#                                    DO NOTHING                           (ignore-duplicates)
#   select  → 필터(eq. / gt. / in.( ))·정렬·limit
# HTTP·헤더 계층은 tests/test_credit_export.py 에서 따로 검증한다. 여기서는 제약조건·타입 변환·
# 충돌 처리 같은 DB 쪽 동작을 실제 스키마(ar-dashboard 마이그레이션)로 확인한다.

import json

import psycopg
from psycopg import sql

from credit_export.supabase_rest import PAGE


class PgRest:
    def __init__(self, dsn, role="service_role"):
        self.conn = psycopg.connect(dsn, autocommit=True)
        self.role = role
        self.requests = []

    def _cursor(self):
        cur = self.conn.cursor()
        cur.execute(sql.SQL("set role {}").format(sql.Identifier(self.role)))
        return cur

    @staticmethod
    def _where(filters):
        parts, params = [], []
        for col, expr in (filters or {}).items():
            op, _, value = expr.partition(".")
            ident = sql.Identifier(col)
            if op == "eq":
                parts.append(sql.SQL("{} = %s").format(ident))
                params.append(value)
            elif op == "gt":
                parts.append(sql.SQL("{} > %s").format(ident))
                params.append(value)
            elif op == "in":
                items = [v for v in value.strip("()").split(",") if v]
                parts.append(sql.SQL("{} = any(%s)").format(ident))
                params.append(items)
            else:
                raise ValueError(f"지원하지 않는 필터 {expr}")
        where = sql.SQL(" where ") + sql.SQL(" and ").join(parts) if parts else sql.SQL("")
        return where, params

    def select_all(self, table, columns="*", order=None, filters=None):
        cols = (sql.SQL("*") if columns == "*" else
                sql.SQL(", ").join(sql.Identifier(c) for c in columns.split(",")))
        out, cursor = [], None
        while True:
            f = dict(filters or {})
            if cursor is not None:
                f[order] = f"gt.{cursor}"
            where, params = self._where(f)
            q = sql.SQL("select {} from {}").format(cols, sql.Identifier(table)) + where
            if order:
                q += sql.SQL(" order by {}").format(sql.Identifier(order))
            q += sql.SQL(" limit {}").format(sql.Literal(PAGE))
            self.requests.append(("GET", table, f))
            with self._cursor() as cur:
                cur.execute(q, params)
                names = [d.name for d in cur.description]
                rows = [dict(zip(names, r)) for r in cur.fetchall()]
            # PostgREST 는 JSON 으로 돌려준다 — date·numeric 을 JSON 과 같은 모양으로
            rows = json.loads(json.dumps(rows, default=str))
            out.extend(rows)
            if len(rows) < PAGE or not order:
                return out
            cursor = rows[-1][order]

    def upsert(self, table, rows, on_conflict, ignore_duplicates=False):
        if not rows:
            return
        keys = list(rows[0])
        if any(list(r) != keys for r in rows):
            # PostgREST 는 일괄 요청의 객체 키가 모두 같아야 한다
            raise RuntimeError(f"{table} upsert 실패 400: All object keys must match")
        cols = sql.SQL(", ").join(sql.Identifier(k) for k in keys)
        conflict = sql.SQL(", ").join(sql.Identifier(c) for c in on_conflict.split(","))
        if ignore_duplicates:
            action = sql.SQL("do nothing")
        else:
            action = sql.SQL("do update set ") + sql.SQL(", ").join(
                sql.SQL("{} = excluded.{}").format(sql.Identifier(k), sql.Identifier(k))
                for k in keys)
        q = sql.SQL(
            "insert into {t} ({cols}) select {cols} from json_populate_recordset(null::{t}, %s) "
            "on conflict ({conflict}) {action}").format(
            t=sql.Identifier(table), cols=cols, conflict=conflict, action=action)
        self.requests.append(("POST", table, len(rows)))
        try:
            with self._cursor() as cur:
                cur.execute(q, [json.dumps(rows, ensure_ascii=False)])
        except psycopg.Error as e:
            raise RuntimeError(f"{table} upsert 실패: {e}") from e
