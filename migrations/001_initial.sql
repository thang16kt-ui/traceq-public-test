-- TraceQ migration 001. PostgreSQL 17; execute once transactionally.

CREATE TABLE analysis_records (
	record_type VARCHAR(60) NOT NULL, 
	source_id VARCHAR(100) NOT NULL, 
	row_version INTEGER NOT NULL, 
	data JSON NOT NULL, 
	scope_key VARCHAR(300) NOT NULL, 
	PRIMARY KEY (record_type, source_id)
)

;

CREATE TABLE defect_types (
	id UUID NOT NULL, 
	code VARCHAR(80) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	severity_default VARCHAR(20) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
)

;

CREATE TABLE export_schedules (
	id UUID NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	local_time VARCHAR(5) NOT NULL, 
	days_of_week JSON NOT NULL, 
	timezone VARCHAR(100) NOT NULL, 
	period_rule VARCHAR(40) NOT NULL, 
	format VARCHAR(10) NOT NULL, 
	filters JSON NOT NULL, 
	destination_id VARCHAR(80) NOT NULL, 
	next_run_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_period_end TIMESTAMP WITH TIME ZONE, 
	last_run_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_export_schedules_next_run_at ON export_schedules (next_run_at);

CREATE TABLE import_runs (
	id UUID NOT NULL, 
	export_id VARCHAR(100) NOT NULL, 
	revision INTEGER NOT NULL, 
	checksum VARCHAR(64) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	error_details TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (export_id, revision)
)

;

CREATE TABLE login_attempts (
	id UUID NOT NULL, 
	address VARCHAR(100) NOT NULL, 
	attempted_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_login_attempts_address ON login_attempts (address);

CREATE TABLE product_types (
	id UUID NOT NULL, 
	sku VARCHAR(80) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	unit_of_measure VARCHAR(40) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (sku)
)

;

CREATE TABLE schema_migrations (
	version VARCHAR(30) NOT NULL, 
	applied_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (version)
)

;

CREATE TABLE users (
	id UUID NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	display_name VARCHAR(160) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	password_hash TEXT NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (role in ('inspector','manager','admin')), 
	UNIQUE (username)
)

;

CREATE TABLE audit_logs (
	id UUID NOT NULL, 
	actor_id UUID, 
	action VARCHAR(100) NOT NULL, 
	entity_type VARCHAR(80) NOT NULL, 
	entity_id VARCHAR(100) NOT NULL, 
	changed_fields JSON NOT NULL, 
	reason TEXT, 
	request_id VARCHAR(100) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
)

;

CREATE TABLE auth_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	user_id UUID NOT NULL, 
	csrf_token VARCHAR(100) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;

CREATE TABLE batches (
	id UUID NOT NULL, 
	product_type_id UUID NOT NULL, 
	lot_code VARCHAR(100) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (product_type_id, lot_code), 
	FOREIGN KEY(product_type_id) REFERENCES product_types (id)
)

;

CREATE TABLE export_runs (
	id UUID NOT NULL, 
	schedule_id UUID, 
	business_key VARCHAR(250) NOT NULL, 
	period_start TIMESTAMP WITH TIME ZONE NOT NULL, 
	period_end TIMESTAMP WITH TIME ZONE NOT NULL, 
	cutoff_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revision INTEGER NOT NULL, 
	scope JSON NOT NULL, 
	timezone VARCHAR(100) NOT NULL, 
	format VARCHAR(10) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	attempts INTEGER NOT NULL, 
	next_retry_at TIMESTAMP WITH TIME ZONE, 
	heartbeat_at TIMESTAMP WITH TIME ZONE, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	error_details TEXT, 
	snapshot_reference TEXT, 
	file_path TEXT, 
	requested_by UUID, 
	checksum VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(schedule_id) REFERENCES export_schedules (id), 
	UNIQUE (business_key), 
	FOREIGN KEY(requested_by) REFERENCES users (id)
)

;
CREATE INDEX ix_export_runs_status ON export_runs (status);

CREATE TABLE idempotency_records (
	id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	operation VARCHAR(200) NOT NULL, 
	key VARCHAR(160) NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	response JSON NOT NULL, 
	status_code INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor_id, operation, key), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
)

;

CREATE TABLE inspection_sessions (
	id UUID NOT NULL, 
	batch_id UUID NOT NULL, 
	line VARCHAR(80) NOT NULL, 
	shift VARCHAR(80) NOT NULL, 
	stage VARCHAR(80) NOT NULL, 
	inspected_count INTEGER, 
	sample_method VARCHAR(160) NOT NULL, 
	population_key VARCHAR(160) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(30) NOT NULL, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (inspected_count IS NULL OR inspected_count >= 0), 
	CHECK (status in ('open','closed')), 
	FOREIGN KEY(batch_id) REFERENCES batches (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
)

;

CREATE TABLE units (
	id UUID NOT NULL, 
	batch_id UUID NOT NULL, 
	serial_number VARCHAR(100) NOT NULL, 
	qr_token VARCHAR(100) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (batch_id, serial_number), 
	CHECK (length(trim(serial_number)) > 0), 
	CHECK (length(qr_token) > 20), 
	FOREIGN KEY(batch_id) REFERENCES batches (id), 
	UNIQUE (qr_token)
)

;

CREATE TABLE defect_cases (
	id UUID NOT NULL, 
	unit_id UUID NOT NULL, 
	inspection_session_id UUID NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	detected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	first_confirmed_at TIMESTAMP WITH TIME ZONE, 
	created_by UUID NOT NULL, 
	assigned_to UUID, 
	result VARCHAR(80), 
	note TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (inspection_session_id, unit_id), 
	CHECK (status in ('draft','confirmed','in_progress','recheck','closed','cancelled')), 
	FOREIGN KEY(unit_id) REFERENCES units (id), 
	FOREIGN KEY(inspection_session_id) REFERENCES inspection_sessions (id), 
	FOREIGN KEY(created_by) REFERENCES users (id), 
	FOREIGN KEY(assigned_to) REFERENCES users (id)
)

;
CREATE INDEX ix_defect_cases_unit_id ON defect_cases (unit_id);
CREATE INDEX ix_defect_cases_inspection_session_id ON defect_cases (inspection_session_id);

CREATE TABLE attachments (
	id UUID NOT NULL, 
	case_id UUID NOT NULL, 
	storage_key VARCHAR(200) NOT NULL, 
	content_type VARCHAR(100) NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	uploaded_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(case_id) REFERENCES defect_cases (id), 
	FOREIGN KEY(uploaded_by) REFERENCES users (id)
)

;

CREATE TABLE case_defects (
	id UUID NOT NULL, 
	case_id UUID NOT NULL, 
	defect_type_id UUID NOT NULL, 
	occurrence_count INTEGER NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	suspected_cause TEXT, 
	verified_cause TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (occurrence_count > 0), 
	CHECK (severity in ('low','medium','high','critical')), 
	UNIQUE (case_id, defect_type_id), 
	FOREIGN KEY(case_id) REFERENCES defect_cases (id), 
	FOREIGN KEY(defect_type_id) REFERENCES defect_types (id)
)

;
CREATE INDEX ix_case_defects_case_id ON case_defects (case_id);

CREATE TABLE case_events (
	id UUID NOT NULL, 
	case_id UUID NOT NULL, 
	event_type VARCHAR(80) NOT NULL, 
	actor_id UUID NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	action_taken TEXT, 
	result TEXT, 
	reason TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(case_id) REFERENCES defect_cases (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
)

;

CREATE TABLE cost_entries (
	id UUID NOT NULL, 
	case_id UUID NOT NULL, 
	category VARCHAR(80) NOT NULL, 
	amount NUMERIC(18, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	cost_status VARCHAR(20) NOT NULL, 
	source_reference VARCHAR(200) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (amount >= 0), 
	CHECK (cost_status in ('actual','estimated')), 
	FOREIGN KEY(case_id) REFERENCES defect_cases (id)
)

;

CREATE TABLE scan_events (
	id UUID NOT NULL, 
	client_event_id UUID NOT NULL, 
	case_id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	received_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	device_id VARCHAR(160), 
	outcome VARCHAR(40) NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	response JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (client_event_id), 
	FOREIGN KEY(case_id) REFERENCES defect_cases (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
)

;

CREATE TABLE cost_allocations (
	id UUID NOT NULL, 
	cost_entry_id UUID NOT NULL, 
	case_defect_id UUID NOT NULL, 
	allocated_amount NUMERIC(18, 2) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (allocated_amount >= 0), 
	UNIQUE (cost_entry_id, case_defect_id), 
	FOREIGN KEY(cost_entry_id) REFERENCES cost_entries (id), 
	FOREIGN KEY(case_defect_id) REFERENCES case_defects (id)
)

;
