#!/usr/bin/env bash
# 통합 테스트용 로컬 PostgreSQL 준비 — ar-dashboard 와 같은 스키마
#
#   tests/setup_test_db.sh /path/to/ar-dashboard [port]
#   TEST_PG_DSN="host=/tmp port=54329 user=postgres dbname=ar" \
#   AUDIT_PDF_DIR=/path/to/감사보고서 python -m pytest tests/test_export_integration.py
#
# ⚠️ 테스트는 dart_* · customers 테이블을 비우고 다시 채운다. 운영 Supabase 에 대고 돌리지 말 것.
# 0025(pg_net 알림)는 Supabase 전용 확장이라 건너뛴다.
set -euo pipefail
AR="${1:?ar-dashboard 경로}"
PORT="${2:-54329}"
BIN=$(ls -d /usr/lib/postgresql/*/bin | tail -1)
# 포트마다 따로 — 다른 포트에서 돌고 있는 테스트 DB 를 지우지 않게
DATA=/var/lib/postgresql/ar-test-$PORT
HERE="$(cd "$(dirname "$0")" && pwd)"
export PGOPTIONS='-c client_min_messages=warning'

# 같은 포트의 이전 테스트 DB 가 떠 있으면 멈춘 뒤 새로 만든다
su postgres -c "$BIN/pg_ctl -D $DATA stop -m fast" > /dev/null 2>&1 || true
su postgres -c "rm -rf $DATA && $BIN/initdb -D $DATA -U postgres --auth=trust -E UTF8 --locale=C.UTF-8" > /dev/null
su postgres -c "setsid $BIN/pg_ctl -D $DATA -o '-p $PORT -k /tmp' -l $DATA/server.log start" < /dev/null > /dev/null
sleep 2
psql -h /tmp -p "$PORT" -U postgres -q -c "create database ar"
cp "$HERE/fixtures/supabase_auth_stub.sql" /tmp/supabase_auth_stub.sql
psql -h /tmp -p "$PORT" -U postgres -d ar -q -v ON_ERROR_STOP=1 -f /tmp/supabase_auth_stub.sql
for f in $(ls "$AR"/supabase/migrations/*.sql | sort); do
  case "$f" in *0025_signup_notify.sql) continue ;; esac
  psql -h /tmp -p "$PORT" -U postgres -d ar -q -v ON_ERROR_STOP=1 -f "$f" > /dev/null
done
echo "준비 완료: TEST_PG_DSN=\"host=/tmp port=$PORT user=postgres dbname=ar\""
