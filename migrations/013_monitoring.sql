-- TraceQ migration 013: ghi lỗi server/client để giám sát (giữ 2000 bản ghi gần nhất).
CREATE TABLE error_events (
	id UUID NOT NULL,
	source VARCHAR(10) NOT NULL,
	message TEXT NOT NULL,
	detail TEXT,
	path VARCHAR(300),
	request_id VARCHAR(100),
	user_id UUID REFERENCES users (id),
	at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT error_events_source_check CHECK (source IN ('server','client','worker'))
);
CREATE INDEX ix_error_events_at ON error_events (at);
