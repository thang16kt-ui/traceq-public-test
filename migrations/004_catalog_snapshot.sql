-- TraceQ migration 004: giám sát/giá vốn theo sản phẩm, snapshot tên loại lỗi trên mục lỗi,
-- bảng cài đặt chung (ngưỡng, ca, công đoạn…).

ALTER TABLE product_types ADD COLUMN site_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES sites (id);
ALTER TABLE product_types ADD COLUMN supervisor_id UUID REFERENCES users (id);
ALTER TABLE product_types ADD COLUMN backup_supervisor_id UUID REFERENCES users (id);
ALTER TABLE product_types ADD COLUMN unit_cost NUMERIC(18, 2);
ALTER TABLE product_types ADD COLUMN salvage_value NUMERIC(18, 2);
ALTER TABLE product_types ADD CONSTRAINT product_types_costs_nonnegative CHECK ((unit_cost IS NULL OR unit_cost >= 0) AND (salvage_value IS NULL OR salvage_value >= 0));

ALTER TABLE defect_types ADD COLUMN site_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES sites (id);

-- Bản ghi cũ giữ đúng tên loại lỗi tại thời điểm ghi nhận, kể cả khi danh mục bị đổi tên/ngừng dùng.
ALTER TABLE case_defects ADD COLUMN defect_type_name_snapshot VARCHAR(160);
ALTER TABLE case_defects ADD COLUMN defect_type_code_snapshot VARCHAR(80);
UPDATE case_defects c SET defect_type_name_snapshot = d.name, defect_type_code_snapshot = d.code FROM defect_types d WHERE d.id = c.defect_type_id;
ALTER TABLE case_defects ALTER COLUMN defect_type_name_snapshot SET NOT NULL;
ALTER TABLE case_defects ALTER COLUMN defect_type_code_snapshot SET NOT NULL;
ALTER TABLE case_defects ADD COLUMN note TEXT NOT NULL DEFAULT '';

CREATE TABLE app_settings (
	key VARCHAR(80) NOT NULL,
	value JSON NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_by UUID REFERENCES users (id),
	PRIMARY KEY (key)
);
