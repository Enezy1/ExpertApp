-- ===== supabase_main1_access.sql — جدول صلاحية "إضافة قضية جديدة" =====
-- شغّل هذا الملف مرة واحدة من SQL Editor بلوحة تحكم Supabase.
-- يخزّن أسماء الخبراء المخوّلين باستخدام ميزة "إضافة قضية جديدة".
--
-- ⚠️ الصلاحية بالاسم لا برقم الحساب: رقم الحساب غير موثوق (النظام الحكومي
-- يعلق على رقم أول مستخدم دخل الجهاز حتى لو غُيّر يدويًا)، بينما الاسم المعروض
-- بعد اكتمال الدخول (get_logged_in_name) موثوق 100%.
--
-- المالك (محمد العنزي) مخوّل دائمًا بالكود ولا يحتاج تسجيله هنا.

CREATE TABLE IF NOT EXISTS main1_authorized_users (
    expert_name TEXT PRIMARY KEY,          -- اسم الخبير (كما يظهر بالتطبيق)
    granted_by  TEXT,                       -- اسم من منح الصلاحية (المالك) — اختياري
    granted_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE main1_authorized_users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "allow_all_main1_access" ON main1_authorized_users
    FOR ALL USING (true) WITH CHECK (true);
