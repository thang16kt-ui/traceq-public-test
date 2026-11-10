#!/bin/sh
set -eu
# Only runs on a new database volume. Values are quoted as psql literals.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv app_password POSTGRES_APP_PASSWORD
CREATE ROLE traceq_app LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
SQL
