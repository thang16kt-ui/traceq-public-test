-- TraceQ migration 012: kiểm tra mẫu ngẫu nhiên các quyết định tự động (Đúng/Sai do Quản lý đánh giá).
CREATE TABLE auto_checks (
	id UUID NOT NULL,
	decision_id UUID NOT NULL REFERENCES decisions (id),
	case_id UUID NOT NULL REFERENCES defect_cases (id),
	step VARCHAR(20) NOT NULL,
	defect_type_id UUID REFERENCES defect_types (id),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	result VARCHAR(5),
	note TEXT,
	checked_by UUID REFERENCES users (id),
	checked_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT auto_checks_decision_key UNIQUE (decision_id),
	CONSTRAINT auto_checks_result_check CHECK (result IS NULL OR result IN ('dung','sai'))
);
CREATE INDEX ix_auto_checks_pending ON auto_checks (result, created_at);
ALTER TABLE decisions ADD COLUMN defect_type_id UUID REFERENCES defect_types (id);
ALTER TABLE decisions ADD COLUMN context JSON;
ALTER TABLE decisions ADD COLUMN entered_at TIMESTAMP WITH TIME ZONE;
