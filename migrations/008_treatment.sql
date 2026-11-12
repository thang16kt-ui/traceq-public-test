-- TraceQ migration 008: phương án xử lý (mỗi lần "Chốt phương án" là một bản ghi; bản cũ giữ lịch sử).
CREATE TABLE treatments (
	id UUID NOT NULL,
	case_id UUID NOT NULL REFERENCES defect_cases (id),
	method VARCHAR(10) NOT NULL,
	note TEXT NOT NULL DEFAULT '',
	est_cost NUMERIC(18, 2),
	est_source VARCHAR(30) NOT NULL,
	est_sample_n INTEGER NOT NULL,
	est_breakdown JSON NOT NULL,
	deadline_at TIMESTAMP WITH TIME ZONE,
	needs_approval BOOLEAN NOT NULL,
	approval_reasons JSON NOT NULL,
	status VARCHAR(12) NOT NULL,
	decided_by UUID NOT NULL REFERENCES users (id),
	decided_at TIMESTAMP WITH TIME ZONE NOT NULL,
	approved_by UUID REFERENCES users (id),
	approved_at TIMESTAMP WITH TIME ZONE,
	rejected_reason TEXT,
	PRIMARY KEY (id),
	CONSTRAINT treatments_method_check CHECK (method IN ('sua','tai_che','huy','khac')),
	CONSTRAINT treatments_status_check CHECK (status IN ('cho_duyet','hieu_luc','bi_tu_choi','thay_the'))
);
CREATE INDEX ix_treatments_case ON treatments (case_id, decided_at);
