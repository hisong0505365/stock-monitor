# credit_export/supabase_rest.py
# Supabase(PostgREST) 최소 클라이언트 — service_role 키로 0008 테이블에 쓴다
#
# ar-dashboard 는 브라우저에서 anon key + RLS 로 읽기만 하고, 쓰기는 이 쪽(서비스 키)이
# 한다(0008 설계). 서비스 키는 RLS 를 우회하므로 이 PC 의 .env 에만 두고 커밋하지 않는다.

import requests

PAGE = 1000   # Supabase 한 번 조회 상한 — ar-dashboard fetch.ts 와 같은 제약


class SupabaseRest:
    def __init__(self, url, service_key, session=None):
        self.base = url.rstrip("/") + "/rest/v1"
        self.session = session or requests.Session()
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def select_all(self, table, columns="*", order=None, filters=None):
        """커서 방식 전체 조회 — 깊은 OFFSET 의 누락·중복을 피한다(ar-dashboard 와 같은 방식)"""
        out, cursor = [], None
        while True:
            params = {"select": columns, "limit": str(PAGE)}
            if order:
                params["order"] = f"{order}.asc"
            params.update(filters or {})
            if cursor is not None:
                params[order] = f"gt.{cursor}"
            res = self.session.get(f"{self.base}/{table}", headers=self.headers,
                                   params=params, timeout=60)
            res.raise_for_status()
            rows = res.json()
            out.extend(rows)
            if len(rows) < PAGE or not order:
                return out
            cursor = rows[-1][order]

    def upsert(self, table, rows, on_conflict, ignore_duplicates=False):
        """on_conflict 키가 같으면 갱신(기본) 또는 건너뜀(ignore_duplicates)"""
        if not rows:
            return
        resolution = "ignore-duplicates" if ignore_duplicates else "merge-duplicates"
        res = self.session.post(
            f"{self.base}/{table}",
            headers={**self.headers, "Prefer": f"resolution={resolution},return=minimal"},
            params={"on_conflict": on_conflict}, json=rows, timeout=60)
        if res.status_code >= 300:
            raise RuntimeError(f"{table} upsert 실패 {res.status_code}: {res.text[:300]}")
