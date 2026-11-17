-- TraceQ migration 005: mức lỗi do Quản lý cài (tối đa 3: Nhẹ/Trung bình/Nặng), cờ ưu tiên ở cấp
-- loại lỗi (áp cho mọi mức), cách tính chi phí, lịch sử giá thị trường. Bỏ mức mặc định.

ALTER TABLE defect_types ADD COLUMN priority_flag BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE defect_types ADD COLUMN cost_mode VARCHAR(10) NOT NULL DEFAULT 'auto';
ALTER TABLE defect_types ADD CONSTRAINT defect_types_cost_mode_check CHECK (cost_mode IN ('auto','market','actual'));
ALTER TABLE defect_types DROP COLUMN severity_default;

CREATE TABLE defect_levels (
	id UUID NOT NULL,
	defect_type_id UUID NOT NULL REFERENCES defect_types (id),
	level VARCHAR(12) NOT NULL,
	enabled BOOLEAN NOT NULL,
	criteria TEXT NOT NULL,
	market_price NUMERIC(18, 2),
	price_effective_from DATE,
	deadline_hours INTEGER,
	suggested_actions VARCHAR(10)[] NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	row_version INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT defect_levels_type_level_key UNIQUE (defect_type_id, level),
	CONSTRAINT defect_levels_level_check CHECK (level IN ('nhe','trung_binh','nang')),
	CONSTRAINT defect_levels_deadline_check CHECK (deadline_hours IS NULL OR deadline_hours > 0),
	CONSTRAINT defect_levels_price_check CHECK (market_price IS NULL OR market_price >= 0),
	CONSTRAINT defect_levels_actions_check CHECK (suggested_actions <@ ARRAY['sua','tai_che','huy','khac']::varchar(10)[])
);

CREATE TABLE market_price_history (
	id UUID NOT NULL,
	level_id UUID NOT NULL REFERENCES defect_levels (id),
	price NUMERIC(18, 2) NOT NULL,
	effective_from DATE NOT NULL,
	changed_by UUID REFERENCES users (id),
	changed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	reason TEXT,
	PRIMARY KEY (id),
	CONSTRAINT market_price_history_price_check CHECK (price >= 0)
);
CREATE INDEX ix_market_price_history_level ON market_price_history (level_id, effective_from);

-- Loại lỗi đang có: bật đủ 3 mức (dữ liệu cũ đã dùng các mức), tiêu chí để trống cho Quản lý điền.
INSERT INTO defect_levels (id, defect_type_id, level, enabled, criteria, deadline_hours, suggested_actions, created_at, updated_at, row_version)
SELECT gen_random_uuid(), d.id, l.level, true, '', l.hours, l.actions::varchar(10)[], CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1
FROM defect_types d CROSS JOIN (VALUES ('nhe', 72, '{sua}'), ('trung_binh', 48, '{sua}'), ('nang', 24, '{sua,huy}')) AS l(level, hours, actions);

-- Mục lỗi: mức theo danh mục + snapshot tiêu chí và cờ ưu tiên lúc ghi nhận.
ALTER TABLE case_defects ADD COLUMN level VARCHAR(12);
ALTER TABLE case_defects ADD COLUMN level_id UUID REFERENCES defect_levels (id);
ALTER TABLE case_defects ADD COLUMN level_criteria_snapshot TEXT NOT NULL DEFAULT '';
ALTER TABLE case_defects ADD COLUMN priority_snapshot BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE case_defects ADD COLUMN severity_original VARCHAR(20);
UPDATE case_defects SET severity_original = severity,
	level = CASE severity WHEN 'low' THEN 'nhe' WHEN 'medium' THEN 'trung_binh' ELSE 'nang' END;
UPDATE case_defects c SET level_id = l.id FROM defect_levels l WHERE l.defect_type_id = c.defect_type_id AND l.level = c.level;
ALTER TABLE case_defects ALTER COLUMN level SET NOT NULL;
ALTER TABLE case_defects ADD CONSTRAINT case_defects_level_check CHECK (level IN ('nhe','trung_binh','nang'));
ALTER TABLE case_defects DROP COLUMN severity;
