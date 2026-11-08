-- ===== supabase_schema_updates.sql — جدول إصدار البرنامج (نظام التحديث التلقائي) =====
-- شغّله مرة واحدة من SQL Editor بـSupabase. صف واحد فقط (id=1) يحدّثه الأدمن
-- من صفحة الإعدادات: رقم آخر نسخة + مسار مجلد التحديثات على الشبكة.

CREATE TABLE IF NOT EXISTS app_version (
    id int PRIMARY KEY DEFAULT 1,
    version text,
    folder_path text,
    released_at timestamptz
);

ALTER TABLE app_version ENABLE ROW LEVEL SECURITY;

CREATE POLICY "allow_all_app_version" ON app_version
    FOR ALL USING (true) WITH CHECK (true);
