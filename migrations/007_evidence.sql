-- TraceQ migration 007: minh chứng BẤT BIẾN – mã băm SHA-256, thời điểm chụp, chỉ số chất lượng ảnh.
-- Không có API sửa/xóa; trigger chặn UPDATE/DELETE ở mức database.

ALTER TABLE attachments ADD COLUMN sha256 VARCHAR(64);
ALTER TABLE attachments ADD COLUMN original_sha256 VARCHAR(64);
ALTER TABLE attachments ADD COLUMN taken_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE attachments ADD COLUMN quality JSON NOT NULL DEFAULT '{}';
ALTER TABLE attachments ADD COLUMN width INTEGER;
ALTER TABLE attachments ADD COLUMN height INTEGER;
-- Ảnh cũ chưa có mã băm: đánh dấu rõ, không bịa giá trị.
UPDATE attachments SET sha256 = 'chua_tinh', taken_at = created_at;
ALTER TABLE attachments ALTER COLUMN sha256 SET NOT NULL;

CREATE OR REPLACE FUNCTION attachments_immutable() RETURNS trigger AS $$
BEGIN
	RAISE EXCEPTION 'Minh chứng là bất biến: không được sửa hoặc xóa';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER attachments_immutable BEFORE UPDATE OR DELETE ON attachments FOR EACH ROW EXECUTE FUNCTION attachments_immutable();

-- Đợt kiểm: cho phép tạo nhanh không cần population_key (tự sinh).
ALTER TABLE inspection_sessions ALTER COLUMN population_key SET DEFAULT '';
