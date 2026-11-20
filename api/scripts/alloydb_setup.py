"""Prepare an AlloyDB (or any PostgreSQL) database for GST CashPilot.

Creates the tables from the SQLAlchemy models, a restricted app role, and (with --rls) row level security.
Run once as the database owner:
  python scripts/alloydb_setup.py --admin-url postgresql+psycopg://postgres:PW@HOST/postgres --app-password APP_PW [--rls]
Then point the API at the app role:  DATABASE_URL=postgresql+psycopg://cashpilot_app:APP_PW@HOST/postgres?sslmode=require
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TENANT_TABLES = ["vendors", "documents", "purchase_invoices", "gstr2b_entries", "sales_summary", "matches", "itc_checks", "gstr3b_drafts", "pipeline_runs"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin-url", required=True)
    ap.add_argument("--app-password", required=True)
    ap.add_argument("--rls", action="store_true", help="turn on row level security")
    a = ap.parse_args()

    from app.core.database import Base
    import app.models  # noqa: F401 - registers the tables

    eng = create_engine(a.admin_url, isolation_level="AUTOCOMMIT")
    Base.metadata.create_all(eng)
    pw = a.app_password.replace("'", "''")
    with eng.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname='cashpilot_app'")).first()
        c.execute(text(f"{'ALTER' if exists else 'CREATE'} ROLE cashpilot_app LOGIN PASSWORD '{pw}'"))
        c.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cashpilot_app"))
        c.execute(text("GRANT USAGE ON SCHEMA public TO cashpilot_app"))
        if a.rls:
            for t in TENANT_TABLES:
                c.execute(text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
                c.execute(text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
                c.execute(text(f"DROP POLICY IF EXISTS own_business ON {t}"))
                c.execute(text(f"CREATE POLICY own_business ON {t} USING (business_id = current_setting('app.business_id', true)) WITH CHECK (business_id = current_setting('app.business_id', true))"))
            c.execute(text("ALTER TABLE businesses ENABLE ROW LEVEL SECURITY"))
            c.execute(text("ALTER TABLE businesses FORCE ROW LEVEL SECURITY"))
            c.execute(text("DROP POLICY IF EXISTS own_row ON businesses"))
            c.execute(text("CREATE POLICY own_row ON businesses USING (id = current_setting('app.business_id', true) OR NULLIF(current_setting('app.business_id', true), '') IS NULL) WITH CHECK (true)"))
    print("Tables created, role cashpilot_app ready" + (", row level security ON" if a.rls else ", row level security OFF"))


if __name__ == "__main__":
    main()
