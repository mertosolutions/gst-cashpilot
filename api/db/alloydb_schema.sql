-- GST CashPilot schema for AlloyDB for PostgreSQL (pgvector + row level security).
-- The API creates the same tables through SQLAlchemy on SQLite locally; use this file on AlloyDB.
-- Run as the table owner, then connect the API as the restricted role `cashpilot_app`.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE businesses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_uid text NOT NULL UNIQUE,
  gstin text NOT NULL,
  legal_name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE vendors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id),
  gstin text NOT NULL, name text NOT NULL, UNIQUE (business_id, gstin)
);
CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id),
  file_type text NOT NULL, filename text NOT NULL, content_type text, file_uri text, status text NOT NULL DEFAULT 'uploaded',
  engine text, extracted jsonb, checks jsonb, stages jsonb, invoice_id uuid, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE purchase_invoices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id),
  vendor_id uuid NOT NULL REFERENCES vendors(id),
  document_id uuid REFERENCES documents(id),
  month text NOT NULL, invoice_no text NOT NULL, invoice_no_clean text NOT NULL, invoice_date date NOT NULL,
  taxable_value numeric(14,2) NOT NULL, igst numeric(14,2) NOT NULL DEFAULT 0, cgst numeric(14,2) NOT NULL DEFAULT 0, sgst numeric(14,2) NOT NULL DEFAULT 0,
  category text NOT NULL DEFAULT 'General purchase', confirmed boolean NOT NULL DEFAULT true, source text NOT NULL DEFAULT 'register'
);
CREATE INDEX ON purchase_invoices (business_id, month, invoice_no_clean);
CREATE TABLE gstr2b_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id),
  month text NOT NULL, supplier_gstin text NOT NULL, supplier_name text, invoice_no text NOT NULL, invoice_no_clean text NOT NULL, invoice_date date NOT NULL,
  taxable_value numeric(14,2) NOT NULL, igst numeric(14,2) NOT NULL DEFAULT 0, cgst numeric(14,2) NOT NULL DEFAULT 0, sgst numeric(14,2) NOT NULL DEFAULT 0,
  itc_available boolean NOT NULL DEFAULT true
);
CREATE INDEX ON gstr2b_entries (business_id, month, supplier_gstin, invoice_no_clean);
CREATE TABLE sales_summary (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id),
  month text NOT NULL, taxable_value numeric(14,2) NOT NULL, igst numeric(14,2) NOT NULL DEFAULT 0, cgst numeric(14,2) NOT NULL DEFAULT 0, sgst numeric(14,2) NOT NULL DEFAULT 0,
  UNIQUE (business_id, month)
);
CREATE TABLE matches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id), month text NOT NULL,
  purchase_invoice_id uuid REFERENCES purchase_invoices(id), gstr2b_entry_id uuid REFERENCES gstr2b_entries(id),
  match_type text NOT NULL, diff_amount numeric(14,2) NOT NULL DEFAULT 0
);
CREATE TABLE legal_chunks (            -- shared GST rule passages: no business_id, no RLS
  id text PRIMARY KEY, citation text NOT NULL, topic text NOT NULL, body text NOT NULL, tags jsonb,
  embedding vector(768), embed_engine text NOT NULL DEFAULT 'gemini-embedding'
);
CREATE INDEX ON legal_chunks USING hnsw (embedding vector_cosine_ops);
CREATE TABLE itc_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id), month text NOT NULL,
  purchase_invoice_id uuid NOT NULL REFERENCES purchase_invoices(id), match_id uuid,
  status text NOT NULL, rule_key text NOT NULL,
  eligible_igst numeric(14,2) DEFAULT 0, eligible_cgst numeric(14,2) DEFAULT 0, eligible_sgst numeric(14,2) DEFAULT 0,
  at_risk_igst numeric(14,2) DEFAULT 0, at_risk_cgst numeric(14,2) DEFAULT 0, at_risk_sgst numeric(14,2) DEFAULT 0,
  blocked_igst numeric(14,2) DEFAULT 0, blocked_cgst numeric(14,2) DEFAULT 0, blocked_sgst numeric(14,2) DEFAULT 0,
  reason text, citation text, passage_ids jsonb, passage_scores jsonb, engine text, llm_explanation text
);
CREATE TABLE gstr3b_drafts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id), month text NOT NULL, tables jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (business_id, month)
);
CREATE TABLE pipeline_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id), month text NOT NULL, status text NOT NULL,
  stages jsonb NOT NULL DEFAULT '[]', started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, total_ms int NOT NULL DEFAULT 0
);

-- Row level security: the app role sees only the rows of the business set by the API for this transaction.
CREATE ROLE cashpilot_app LOGIN;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cashpilot_app;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['vendors','documents','purchase_invoices','gstr2b_entries','sales_summary','matches','itc_checks','gstr3b_drafts','pipeline_runs'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY own_business ON %I
       USING (business_id = current_setting('app.business_id', true)::uuid)
       WITH CHECK (business_id = current_setting('app.business_id', true)::uuid)$p$, t);
  END LOOP;
END $$;
ALTER TABLE businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE businesses FORCE ROW LEVEL SECURITY;
CREATE POLICY own_row ON businesses USING (id = current_setting('app.business_id', true)::uuid OR current_setting('app.business_id', true) IS NULL);
-- The API sets the id per request (app/core/database.py: set_tenant) with set_config('app.business_id', :id, true).
