-- TraceQ migration 010: thông báo trong app (kiêm hàng đợi gửi Web Push) và đăng ký Web Push theo thiết bị.
CREATE TABLE notifications (
	id UUID NOT NULL,
	user_id UUID NOT NULL REFERENCES users (id),
	type VARCHAR(20) NOT NULL,
	case_id UUID REFERENCES defect_cases (id),
	title VARCHAR(200) NOT NULL,
	body TEXT NOT NULL,
	link VARCHAR(300),
	dedupe_key VARCHAR(200),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	read_at TIMESTAMP WITH TIME ZONE,
	push_status VARCHAR(10) NOT NULL,
	push_attempts INTEGER NOT NULL DEFAULT 0,
	PRIMARY KEY (id),
	CONSTRAINT notifications_dedupe_key UNIQUE (user_id, dedupe_key)
);
CREATE INDEX ix_notifications_user ON notifications (user_id, created_at);
CREATE INDEX ix_notifications_push ON notifications (push_status);

CREATE TABLE push_subscriptions (
	id UUID NOT NULL,
	user_id UUID NOT NULL REFERENCES users (id),
	endpoint TEXT NOT NULL,
	p256dh VARCHAR(200) NOT NULL,
	auth VARCHAR(100) NOT NULL,
	user_agent VARCHAR(300) NOT NULL DEFAULT '',
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	last_error TEXT,
	PRIMARY KEY (id),
	CONSTRAINT push_subscriptions_endpoint_key UNIQUE (endpoint)
);
