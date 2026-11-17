-- TraceQ migration 006: máy trạng thái đề xuất, mã DX-xxxx, lịch sử trạng thái, quyết định.

ALTER TABLE defect_cases DROP CONSTRAINT defect_cases_status_check;
UPDATE defect_cases SET status = CASE status
	WHEN 'draft' THEN 'nhap' WHEN 'confirmed' THEN 'cho_phuong_an' WHEN 'in_progress' THEN 'dang_xu_ly'
	WHEN 'recheck' THEN 'cho_dong' WHEN 'closed' THEN 'da_dong' WHEN 'cancelled' THEN 'da_huy' ELSE status END;
ALTER TABLE defect_cases ALTER COLUMN status SET DEFAULT 'nhap';
ALTER TABLE defect_cases ADD CONSTRAINT defect_cases_status_check CHECK (status IN
	('nhap','cho_minh_chung','cho_xac_nhan','cho_phuong_an','cho_cap_tren','dang_xu_ly','cho_dong','da_dong','da_huy'));

CREATE SEQUENCE proposal_code_seq;
ALTER TABLE defect_cases ADD COLUMN code VARCHAR(20);
WITH numbered AS (SELECT id, row_number() OVER (ORDER BY created_at, id) AS n FROM defect_cases)
UPDATE defect_cases c SET code = 'DX-' || CASE WHEN n < 10000 THEN lpad(n::text, 4, '0') ELSE n::text END FROM numbered WHERE numbered.id = c.id;
SELECT setval('proposal_code_seq', GREATEST((SELECT count(*) FROM defect_cases), 1), (SELECT count(*) FROM defect_cases) > 0);
ALTER TABLE defect_cases ALTER COLUMN code SET NOT NULL;
ALTER TABLE defect_cases ADD CONSTRAINT defect_cases_code_key UNIQUE (code);

ALTER TABLE defect_cases ADD COLUMN site_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES sites (id);
ALTER TABLE defect_cases ADD COLUMN priority BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE defect_cases ADD COLUMN max_level VARCHAR(12);
ALTER TABLE defect_cases ADD COLUMN supervisor_id UUID REFERENCES users (id);
ALTER TABLE defect_cases ADD COLUMN supervisor_name_snapshot VARCHAR(160);
ALTER TABLE defect_cases ADD COLUMN submitted_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE defect_cases ADD COLUMN deadline_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE defect_cases ADD COLUMN closed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE defect_cases ADD COLUMN status_changed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP;
UPDATE defect_cases c SET priority = EXISTS (SELECT 1 FROM case_defects d WHERE d.case_id = c.id AND d.priority_snapshot),
	max_level = (SELECT CASE max(CASE level WHEN 'nhe' THEN 1 WHEN 'trung_binh' THEN 2 ELSE 3 END) WHEN 1 THEN 'nhe' WHEN 2 THEN 'trung_binh' WHEN 3 THEN 'nang' END FROM case_defects d WHERE d.case_id = c.id),
	submitted_at = CASE WHEN status <> 'nhap' THEN created_at END,
	closed_at = CASE WHEN status = 'da_dong' THEN updated_at END,
	status_changed_at = updated_at;
CREATE INDEX ix_defect_cases_status ON defect_cases (status);

-- Một sản phẩm chỉ có một đề xuất đang mở (thêm mục lỗi vào đề xuất đó). Bỏ ràng buộc cũ theo đợt.
ALTER TABLE defect_cases DROP CONSTRAINT defect_cases_inspection_session_id_unit_id_key;
DO $$ BEGIN
	IF NOT EXISTS (SELECT unit_id FROM defect_cases WHERE status NOT IN ('da_dong','da_huy') GROUP BY unit_id HAVING count(*) > 1) THEN
		CREATE UNIQUE INDEX ix_defect_cases_one_open_per_unit ON defect_cases (unit_id) WHERE status NOT IN ('da_dong','da_huy');
	END IF;
END $$;

CREATE TABLE state_history (
	id UUID NOT NULL,
	case_id UUID NOT NULL REFERENCES defect_cases (id),
	from_status VARCHAR(20),
	to_status VARCHAR(20) NOT NULL,
	action VARCHAR(40) NOT NULL,
	actor_id UUID REFERENCES users (id),
	actor_kind VARCHAR(10) NOT NULL,
	reason TEXT,
	at TIMESTAMP WITH TIME ZONE NOT NULL,
	meta JSON NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT state_history_actor_kind_check CHECK (actor_kind IN ('nguoi','tu_dong','he_thong'))
);
CREATE INDEX ix_state_history_case ON state_history (case_id, at);
INSERT INTO state_history (id, case_id, from_status, to_status, action, actor_id, actor_kind, reason, at, meta)
SELECT gen_random_uuid(), id, NULL, status, 'chuyen_du_lieu_cu', NULL, 'he_thong', 'Trạng thái chuyển từ phiên bản cũ', updated_at, '{}' FROM defect_cases;

CREATE TABLE decisions (
	id UUID NOT NULL,
	case_id UUID NOT NULL REFERENCES defect_cases (id),
	step VARCHAR(20) NOT NULL,
	actor_id UUID REFERENCES users (id),
	actor_kind VARCHAR(10) NOT NULL,
	action VARCHAR(40) NOT NULL,
	reason TEXT,
	confidence NUMERIC(5, 4),
	suggestion JSON,
	agreed BOOLEAN,
	at TIMESTAMP WITH TIME ZONE NOT NULL,
	reversible_until TIMESTAMP WITH TIME ZONE,
	reversed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT decisions_actor_kind_check CHECK (actor_kind IN ('nguoi','tu_dong','he_thong'))
);
CREATE INDEX ix_decisions_case ON decisions (case_id, at);
CREATE INDEX ix_decisions_step ON decisions (step, at);

-- Mục không có ảnh minh chứng phải có lý do.
ALTER TABLE case_defects ADD COLUMN no_photo_reason TEXT;
-- Ảnh gắn từng mục lỗi; loại 'truoc' (minh chứng lỗi) hoặc 'sau' (sau xử lý).
ALTER TABLE attachments ADD COLUMN case_defect_id UUID REFERENCES case_defects (id);
ALTER TABLE attachments ADD COLUMN kind VARCHAR(10) NOT NULL DEFAULT 'truoc';
ALTER TABLE attachments ADD CONSTRAINT attachments_kind_check CHECK (kind IN ('truoc','sau'));
