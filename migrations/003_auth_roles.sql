-- TraceQ migration 003: một nhà máy mặc định, nhiều vai trò/tài khoản, khóa tài khoản,
-- phiên theo thiết bị. Chạy bằng: python -m backend.app.cli migrate

CREATE TABLE sites (
	id UUID NOT NULL,
	name VARCHAR(160) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id)
);
INSERT INTO sites (id, name) VALUES ('00000000-0000-0000-0000-000000000001', 'Nhà máy chính');

ALTER TABLE users ADD COLUMN site_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES sites (id);
ALTER TABLE users ADD COLUMN code VARCHAR(40);
CREATE UNIQUE INDEX ix_users_code_lower ON users (lower(code)) WHERE code IS NOT NULL;

ALTER TABLE users ADD COLUMN roles VARCHAR(20)[] NOT NULL DEFAULT '{}';
-- Vai trò cũ: inspector → Người tạo; manager → Quản lý; admin giữ đủ quyền cũ (Admin + Quản lý).
UPDATE users SET roles = CASE role
	WHEN 'inspector' THEN ARRAY['nguoi_tao']::varchar(20)[]
	WHEN 'manager' THEN ARRAY['quan_ly']::varchar(20)[]
	ELSE ARRAY['admin','quan_ly']::varchar(20)[] END;
ALTER TABLE users DROP COLUMN role;
ALTER TABLE users ALTER COLUMN roles DROP DEFAULT;
ALTER TABLE users ADD CONSTRAINT users_roles_valid CHECK (
	cardinality(roles) > 0 AND roles <@ ARRAY['nguoi_tao','giam_sat','cap_tren','quan_ly','admin']::varchar(20)[]);

ALTER TABLE users ADD COLUMN locked_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN locked_reason TEXT;
ALTER TABLE users ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN locked_until TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN away_until TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN notify_prefs JSON NOT NULL DEFAULT '{}';

-- Bản test public cũ dùng danh tính khách chung không cần mật khẩu: tắt hẳn.
UPDATE users SET is_active = false WHERE username IN ('public.guest', 'public.catalog');

ALTER TABLE auth_sessions ADD COLUMN id UUID;
UPDATE auth_sessions SET id = gen_random_uuid();
ALTER TABLE auth_sessions ALTER COLUMN id SET NOT NULL;
ALTER TABLE auth_sessions ADD CONSTRAINT auth_sessions_id_key UNIQUE (id);
ALTER TABLE auth_sessions ADD COLUMN device_label VARCHAR(160) NOT NULL DEFAULT '';
ALTER TABLE auth_sessions ADD COLUMN user_agent VARCHAR(300) NOT NULL DEFAULT '';
ALTER TABLE auth_sessions ADD COLUMN created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE auth_sessions ADD COLUMN last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE auth_sessions ADD COLUMN revoked_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE auth_sessions ADD COLUMN remember BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id);
