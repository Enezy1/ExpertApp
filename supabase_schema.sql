-- ===== سكيمة قاعدة بيانات رئيس القسم السحابية (Supabase) =====
-- شغّل هذا الملف كامل من SQL Editor بلوحة تحكم Supabase (مرة واحدة فقط)

-- جدول القضايا (نسخة مصغّرة من القاعدة المحلية، تُرفع فقط عند التفعيل)
CREATE TABLE IF NOT EXISTS cases (
    caso_no TEXT PRIMARY KEY,
    autocase_no TEXT,
    expert_name TEXT NOT NULL,
    case_type TEXT,
    title TEXT,
    received_date TEXT,
    court_case_number TEXT,
    status TEXT,                    -- متداولة / محجوزة / منجزة
    status_updated_at TEXT,
    is_committee TEXT,
    committee_members TEXT,         -- JSON كنص
    updated_at TEXT,
    synced_at TIMESTAMPTZ DEFAULT now()
);

-- فهرس يسرّع استعلامات "قضايا هذا الخبير"
CREATE INDEX IF NOT EXISTS idx_cases_expert ON cases (expert_name);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases (status);

-- جدول التحكم بتفعيل المزامنة لكل خبير (رئيس القسم يتحكم فيه)
CREATE TABLE IF NOT EXISTS expert_sync_status (
    expert_name TEXT PRIMARY KEY,
    sync_enabled BOOLEAN NOT NULL DEFAULT false,
    enabled_by TEXT,                -- اسم رئيس القسم اللي فعّل (اختياري)
    enabled_at TIMESTAMPTZ,
    last_sync_at TIMESTAMPTZ
);

-- تفعيل Row Level Security (مهم أمنياً — نتحكم بالوصول بسياسات صريحة)
ALTER TABLE cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE expert_sync_status ENABLE ROW LEVEL SECURITY;

-- سياسة مؤقتة تسمح بالقراءة/الكتابة للجميع عبر anon key
-- (تكفي للمرحلة الحالية بدون تسجيل دخول مستخدمين حقيقي بـSupabase Auth؛
--  لاحقاً لما نضيف طبقة تسجيل دخول لرئيس القسم، نضيّق هذي السياسات)
CREATE POLICY "allow_all_cases" ON cases
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "allow_all_sync_status" ON expert_sync_status
    FOR ALL USING (true) WITH CHECK (true);
