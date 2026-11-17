"""Run the uploaded TraceQ application in its own logical PostgreSQL database.

Render resolves the provisioning URL through a Blueprint reference. The new
database shares the existing managed instance, without migrating its original
database or needing a second paid instance. No credentials belong in source.
"""
import os
import re
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def configure_isolated_database():
    target = os.environ['TRACEQ_DATABASE_NAME']
    if not re.fullmatch(r'traceq_moi_[0-9]{8}_demo', target):
        raise RuntimeError('An explicitly named TraceQ demo database is required')
    source = make_url(os.environ['TRACEQ_PROVISIONING_DATABASE_URL'])
    if source.database == target:
        raise RuntimeError('Provisioning must reference a different database')
    connection_url = source.set(drivername='postgresql').render_as_string(hide_password=False)
    with psycopg.connect(connection_url, autocommit=True, connect_timeout=15) as connection:
        # A session lock also serializes overlapping startup attempts.
        connection.execute('SELECT pg_advisory_lock(hashtextextended(%s, 0))', ('traceq-provision:' + target,))
        try:
            found = connection.execute('SELECT 1 FROM pg_database WHERE datname = %s', (target,)).fetchone()
            if not found:
                connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
        finally:
            connection.execute('SELECT pg_advisory_unlock(hashtextextended(%s, 0))', ('traceq-provision:' + target,))
    os.environ['DATABASE_URL'] = source.set(drivername='postgresql+psycopg', database=target).render_as_string(hide_password=False)
    os.environ.pop('TRACEQ_PROVISIONING_DATABASE_URL', None)
    print('TraceQ: isolated demo database ready', flush=True)


if __name__ == '__main__':
    configure_isolated_database()
    from scripts.run_public import main
    main()
