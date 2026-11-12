import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, Uuid, event, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, mapped_column

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)

class Base(DeclarativeBase): pass

class Versioned:
    created_at = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    row_version = mapped_column(Integer, default=1, nullable=False)

DEFAULT_SITE_ID = '00000000-0000-0000-0000-000000000001'
ROLES = ('nguoi_tao', 'giam_sat', 'cap_tren', 'quan_ly', 'admin')

class Site(Base):
    __tablename__ = 'sites'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    name = mapped_column(String(160), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), default=now, server_default=func.now(), nullable=False)

class User(Base, Versioned):
    __tablename__ = 'users'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    site_id = mapped_column(ForeignKey('sites.id'), default=DEFAULT_SITE_ID, server_default=DEFAULT_SITE_ID, nullable=False)
    username = mapped_column(String(80), unique=True, nullable=False)
    code = mapped_column(String(40), nullable=True)
    display_name = mapped_column(String(160), nullable=False)
    roles = mapped_column(ARRAY(String(20)), nullable=False)
    password_hash = mapped_column(Text, nullable=False)
    is_active = mapped_column(Boolean, default=True, nullable=False)
    locked_at = mapped_column(DateTime(timezone=True), nullable=True)
    locked_reason = mapped_column(Text, nullable=True)
    failed_logins = mapped_column(Integer, default=0, server_default='0', nullable=False)
    locked_until = mapped_column(DateTime(timezone=True), nullable=True)
    must_change_password = mapped_column(Boolean, default=False, server_default='false', nullable=False)
    last_login_at = mapped_column(DateTime(timezone=True), nullable=True)
    away_until = mapped_column(DateTime(timezone=True), nullable=True)
    notify_prefs = mapped_column(JSON, default=dict, server_default='{}', nullable=False)
    __table_args__ = (
        CheckConstraint("cardinality(roles) > 0 AND roles <@ ARRAY['nguoi_tao','giam_sat','cap_tren','quan_ly','admin']::varchar(20)[]", name='users_roles_valid'),
        Index('ix_users_code_lower', func.lower(code), unique=True, postgresql_where=code.isnot(None)),
    )

    def has(self, *roles):
        return any(r in (self.roles or ()) for r in roles)

class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash = mapped_column(String(64), primary_key=True)
    id = mapped_column(Uuid(as_uuid=False), unique=True, default=uid, nullable=False)
    user_id = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    csrf_token = mapped_column(String(100), nullable=False)
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    device_label = mapped_column(String(160), default='', server_default='', nullable=False)
    user_agent = mapped_column(String(300), default='', server_default='', nullable=False)
    created_at = mapped_column(DateTime(timezone=True), default=now, server_default=func.now(), nullable=False)
    last_seen_at = mapped_column(DateTime(timezone=True), default=now, server_default=func.now(), nullable=False)
    revoked_at = mapped_column(DateTime(timezone=True), nullable=True)
    remember = mapped_column(Boolean, default=False, server_default='false', nullable=False)

class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    address = mapped_column(String(100), nullable=False, index=True)
    attempted_at = mapped_column(DateTime(timezone=True), default=now, nullable=False)

class ProductType(Base, Versioned):
    __tablename__ = 'product_types'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    sku = mapped_column(String(80), unique=True, nullable=False)
    name = mapped_column(String(200), nullable=False)
    unit_of_measure = mapped_column(String(40), default='cái', nullable=False)
    is_active = mapped_column(Boolean, default=True, server_default='true', nullable=False)
    name_key = mapped_column(Text, unique=True, nullable=False)
    sku_key = mapped_column(Text, unique=True, nullable=False)
    has_been_used = mapped_column(Boolean, default=False, server_default='false', nullable=False)

class Batch(Base, Versioned):
    __tablename__ = 'batches'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    product_type_id = mapped_column(ForeignKey('product_types.id'), nullable=False)
    lot_code = mapped_column(String(100), nullable=False)
    is_active = mapped_column(Boolean, default=True, server_default='true', nullable=False)
    lot_key = mapped_column(Text, nullable=False)
    has_been_used = mapped_column(Boolean, default=False, server_default='false', nullable=False)
    __table_args__ = (UniqueConstraint('product_type_id', 'lot_code'), UniqueConstraint('product_type_id', 'lot_key'))

class Unit(Base, Versioned):
    __tablename__ = 'units'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    batch_id = mapped_column(ForeignKey('batches.id'), nullable=False)
    serial_number = mapped_column(String(100), nullable=False)
    qr_token = mapped_column(String(100), unique=True, nullable=False)
    __table_args__ = (UniqueConstraint('batch_id', 'serial_number'), CheckConstraint("length(trim(serial_number)) > 0"), CheckConstraint("length(qr_token) > 20"))

class InspectionSession(Base, Versioned):
    __tablename__ = 'inspection_sessions'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    batch_id = mapped_column(ForeignKey('batches.id'), nullable=False)
    line = mapped_column(String(80), nullable=False)
    shift = mapped_column(String(80), nullable=False)
    stage = mapped_column(String(80), nullable=False)
    inspected_count = mapped_column(Integer, nullable=True)
    sample_method = mapped_column(String(160), nullable=False, default='manual')
    population_key = mapped_column(String(160), nullable=False)
    started_at = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    ended_at = mapped_column(DateTime(timezone=True), nullable=True)
    status = mapped_column(String(30), default='open', nullable=False)
    created_by = mapped_column(ForeignKey('users.id'), nullable=False)
    __table_args__ = (CheckConstraint('inspected_count IS NULL OR inspected_count >= 0'), CheckConstraint("status in ('open','closed')"))

class DefectType(Base, Versioned):
    __tablename__ = 'defect_types'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    code = mapped_column(String(80), unique=True, nullable=False)
    name = mapped_column(String(160), nullable=False)
    severity_default = mapped_column(String(20), default='medium', nullable=False)
    is_active = mapped_column(Boolean, default=True, nullable=False)
    name_key = mapped_column(Text, unique=True, nullable=False)
    code_key = mapped_column(Text, unique=True, nullable=False)
    has_been_used = mapped_column(Boolean, default=False, server_default='false', nullable=False)


def set_catalog_keys(mapper, connection, target):
    from .catalog_keys import KEY_FIELDS, catalog_key
    for key, source in KEY_FIELDS[target.__tablename__].items():
        setattr(target, key, catalog_key(getattr(target, source)))


for catalog_model in (ProductType, Batch, DefectType):
    event.listen(catalog_model, 'before_insert', set_catalog_keys)
    event.listen(catalog_model, 'before_update', set_catalog_keys)

class DefectCase(Base, Versioned):
    __tablename__ = 'defect_cases'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    unit_id = mapped_column(ForeignKey('units.id'), nullable=False, index=True)
    inspection_session_id = mapped_column(ForeignKey('inspection_sessions.id'), nullable=False, index=True)
    status = mapped_column(String(30), default='draft', nullable=False)
    detected_at = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    first_confirmed_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_by = mapped_column(ForeignKey('users.id'), nullable=False)
    assigned_to = mapped_column(ForeignKey('users.id'), nullable=True)
    result = mapped_column(String(80), nullable=True)
    note = mapped_column(Text, default='', nullable=False)
    __table_args__ = (UniqueConstraint('inspection_session_id','unit_id'), CheckConstraint("status in ('draft','confirmed','in_progress','recheck','closed','cancelled')"))

class CaseDefect(Base, Versioned):
    __tablename__ = 'case_defects'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    case_id = mapped_column(ForeignKey('defect_cases.id'), nullable=False, index=True)
    defect_type_id = mapped_column(ForeignKey('defect_types.id'), nullable=False)
    occurrence_count = mapped_column(Integer, default=1, nullable=False)
    severity = mapped_column(String(20), nullable=False)
    suspected_cause = mapped_column(Text, nullable=True)
    verified_cause = mapped_column(Text, nullable=True)
    __table_args__ = (CheckConstraint('occurrence_count > 0'), CheckConstraint("severity in ('low','medium','high','critical')"), UniqueConstraint('case_id','defect_type_id'))

class CaseEvent(Base):
    __tablename__ = 'case_events'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    case_id = mapped_column(ForeignKey('defect_cases.id'), nullable=False)
    event_type = mapped_column(String(80), nullable=False)
    actor_id = mapped_column(ForeignKey('users.id'), nullable=False)
    occurred_at = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    action_taken = mapped_column(Text, nullable=True)
    result = mapped_column(Text, nullable=True)
    reason = mapped_column(Text, nullable=True)

class CostEntry(Base, Versioned):
    __tablename__ = 'cost_entries'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    case_id = mapped_column(ForeignKey('defect_cases.id'), nullable=False)
    category = mapped_column(String(80), nullable=False)
    amount = mapped_column(Numeric(18,2), nullable=False)
    currency = mapped_column(String(3), nullable=False)
    cost_status = mapped_column(String(20), nullable=False)
    source_reference = mapped_column(String(200), nullable=False)
    __table_args__ = (CheckConstraint('amount >= 0'), CheckConstraint("cost_status in ('actual','estimated')"))

class CostAllocation(Base, Versioned):
    __tablename__ = 'cost_allocations'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    cost_entry_id = mapped_column(ForeignKey('cost_entries.id'), nullable=False)
    case_defect_id = mapped_column(ForeignKey('case_defects.id'), nullable=False)
    allocated_amount = mapped_column(Numeric(18,2), nullable=False)
    __table_args__ = (CheckConstraint('allocated_amount >= 0'), UniqueConstraint('cost_entry_id','case_defect_id'))

class Attachment(Base, Versioned):
    __tablename__ = 'attachments'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    case_id = mapped_column(ForeignKey('defect_cases.id'), nullable=False)
    storage_key = mapped_column(String(200), nullable=False)
    content_type = mapped_column(String(100), nullable=False)
    size_bytes = mapped_column(Integer, nullable=False)
    uploaded_by = mapped_column(ForeignKey('users.id'), nullable=False)

class ScanEvent(Base):
    __tablename__ = 'scan_events'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    client_event_id = mapped_column(Uuid(as_uuid=False), unique=True, nullable=False)
    case_id = mapped_column(ForeignKey('defect_cases.id'), nullable=False)
    actor_id = mapped_column(ForeignKey('users.id'), nullable=False)
    observed_at = mapped_column(DateTime(timezone=True), nullable=False)
    received_at = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    device_id = mapped_column(String(160), nullable=True)
    outcome = mapped_column(String(40), nullable=False)
    payload_hash = mapped_column(String(64), nullable=False)
    response = mapped_column(JSON, nullable=False)

class IdempotencyRecord(Base):
    __tablename__ = 'idempotency_records'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    actor_id = mapped_column(ForeignKey('users.id'), nullable=False)
    operation = mapped_column(String(200), nullable=False)
    key = mapped_column(String(160), nullable=False)
    payload_hash = mapped_column(String(64), nullable=False)
    response = mapped_column(JSON, nullable=False)
    status_code = mapped_column(Integer, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (UniqueConstraint('actor_id','operation','key'),)

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    actor_id = mapped_column(ForeignKey('users.id'), nullable=True)
    action = mapped_column(String(100), nullable=False)
    entity_type = mapped_column(String(80), nullable=False)
    entity_id = mapped_column(String(100), nullable=False)
    changed_fields = mapped_column(JSON, nullable=False)
    reason = mapped_column(Text, nullable=True)
    request_id = mapped_column(String(100), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), default=now, nullable=False)

class ExportSchedule(Base, Versioned):
    __tablename__ = 'export_schedules'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    name = mapped_column(String(120), default='Xuất cuối ngày', nullable=False)
    enabled = mapped_column(Boolean, default=True, nullable=False)
    local_time = mapped_column(String(5), nullable=False)
    days_of_week = mapped_column(JSON, nullable=False)
    timezone = mapped_column(String(100), default='Asia/Ho_Chi_Minh', nullable=False)
    period_rule = mapped_column(String(40), default='previous_day', nullable=False)
    format = mapped_column(String(10), default='csv', nullable=False)
    filters = mapped_column(JSON, default=dict, nullable=False)
    destination_id = mapped_column(String(80), default='local', nullable=False)
    next_run_at = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_period_end = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at = mapped_column(DateTime(timezone=True), nullable=True)

class ExportRun(Base, Versioned):
    __tablename__ = 'export_runs'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    schedule_id = mapped_column(ForeignKey('export_schedules.id'), nullable=True)
    business_key = mapped_column(String(250), unique=True, nullable=False)
    period_start = mapped_column(DateTime(timezone=True), nullable=False)
    period_end = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff_at = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    revision = mapped_column(Integer, default=1, nullable=False)
    scope = mapped_column(JSON, default=dict, nullable=False)
    timezone = mapped_column(String(100), default='Asia/Ho_Chi_Minh', nullable=False)
    format = mapped_column(String(10), default='csv', nullable=False)
    status = mapped_column(String(20), default='queued', nullable=False, index=True)
    attempts = mapped_column(Integer, default=0, nullable=False)
    next_retry_at = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at = mapped_column(DateTime(timezone=True), nullable=True)
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
    error_details = mapped_column(Text, nullable=True)
    snapshot_reference = mapped_column(Text, nullable=True)
    file_path = mapped_column(Text, nullable=True)
    requested_by = mapped_column(ForeignKey('users.id'), nullable=True)
    checksum = mapped_column(String(64), nullable=True)

class ImportRun(Base, Versioned):
    __tablename__ = 'import_runs'
    id = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    export_id = mapped_column(String(100), nullable=False)
    revision = mapped_column(Integer, nullable=False)
    checksum = mapped_column(String(64), nullable=False)
    status = mapped_column(String(30), nullable=False)
    processed_at = mapped_column(DateTime(timezone=True), nullable=True)
    error_details = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint('export_id','revision'),)

class AnalysisRecord(Base):
    __tablename__ = 'analysis_records'
    record_type = mapped_column(String(60), primary_key=True)
    source_id = mapped_column(String(100), primary_key=True)
    row_version = mapped_column(Integer, nullable=False)
    data = mapped_column(JSON, nullable=False)
    scope_key = mapped_column(String(300), nullable=False)

class SchemaMigration(Base):
    __tablename__ = 'schema_migrations'
    version = mapped_column(String(30), primary_key=True)
    applied_at = mapped_column(DateTime(timezone=True), default=now, nullable=False)
