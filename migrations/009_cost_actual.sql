-- TraceQ migration 009: chi phí thực tế nhập ở "Hoàn tất xử lý" (mỗi lần hoàn tất một dòng;
-- làm lại thì cộng thêm). Khi đóng, tổng thực tế vào dữ liệu dự báo.
CREATE TABLE cost_actuals (
	id UUID NOT NULL,
	case_id UUID NOT NULL REFERENCES defect_cases (id),
	treatment_id UUID REFERENCES treatments (id),
	material NUMERIC(18, 2) NOT NULL,
	hours NUMERIC(8, 2) NOT NULL,
	hourly_rate NUMERIC(18, 2) NOT NULL,
	other NUMERIC(18, 2) NOT NULL,
	total NUMERIC(18, 2) NOT NULL,
	root_causes JSON NOT NULL,
	note TEXT NOT NULL DEFAULT '',
	entered_by UUID NOT NULL REFERENCES users (id),
	entered_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT cost_actuals_nonnegative CHECK (material >= 0 AND hours >= 0 AND hourly_rate >= 0 AND other >= 0 AND total >= 0)
);
CREATE INDEX ix_cost_actuals_case_id ON cost_actuals (case_id);
