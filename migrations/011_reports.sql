-- TraceQ migration 011: lịch sử xuất báo cáo (mã BC-xxxx), kể cả báo cáo gửi định kỳ.
CREATE SEQUENCE report_code_seq;
CREATE TABLE report_exports (
	id UUID NOT NULL,
	code VARCHAR(20) NOT NULL,
	kind VARCHAR(10) NOT NULL,
	format VARCHAR(5) NOT NULL,
	params JSON NOT NULL,
	period_key VARCHAR(40),
	created_by UUID REFERENCES users (id),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	file_ref VARCHAR(300) NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	size_bytes INTEGER NOT NULL,
	delivery JSON NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT report_exports_code_key UNIQUE (code),
	CONSTRAINT report_exports_period_key UNIQUE (kind, period_key),
	CONSTRAINT report_exports_kind_check CHECK (kind IN ('thu_cong','dinh_ky')),
	CONSTRAINT report_exports_format_check CHECK (format IN ('pdf','xlsx'))
);
