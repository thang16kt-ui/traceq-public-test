-- Backfill and duplicate preflight run transactionally in app.cli.migrate.
-- Do not run this file alone: use python -m backend.app.cli migrate.
ALTER TABLE product_types ADD COLUMN is_active boolean NOT NULL DEFAULT true;
ALTER TABLE batches ADD COLUMN is_active boolean NOT NULL DEFAULT true;
ALTER TABLE product_types ADD COLUMN name_key text;
ALTER TABLE product_types ADD COLUMN sku_key text;
ALTER TABLE batches ADD COLUMN lot_key text;
ALTER TABLE defect_types ADD COLUMN name_key text;
ALTER TABLE defect_types ADD COLUMN code_key text;
ALTER TABLE product_types ADD COLUMN has_been_used boolean NOT NULL DEFAULT false;
ALTER TABLE batches ADD COLUMN has_been_used boolean NOT NULL DEFAULT false;
ALTER TABLE defect_types ADD COLUMN has_been_used boolean NOT NULL DEFAULT false;

UPDATE product_types p SET has_been_used=true WHERE EXISTS (SELECT 1 FROM batches b WHERE b.product_type_id=p.id);
UPDATE batches b SET has_been_used=true WHERE EXISTS (SELECT 1 FROM units u WHERE u.batch_id=b.id) OR EXISTS (SELECT 1 FROM inspection_sessions s WHERE s.batch_id=b.id);
UPDATE defect_types d SET has_been_used=true WHERE EXISTS (SELECT 1 FROM case_defects c WHERE c.defect_type_id=d.id);
-- A removed case-defect may remain in historical audit/mirror data. Conservatively
-- preserve those catalog identities too; never rewrite or erase the old records.
UPDATE defect_types d SET has_been_used=true WHERE NOT has_been_used AND (
    EXISTS (SELECT 1 FROM audit_logs a WHERE a.entity_type='defect_cases' AND strpos(a.changed_fields::text,d.id::text)>0)
    OR EXISTS (SELECT 1 FROM analysis_records a WHERE a.record_type='case_defects' AND a.data->>'defect_type_id'=d.id::text)
);
