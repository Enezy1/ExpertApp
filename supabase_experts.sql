-- ===== supabase_experts.sql — جدول سجل أسماء الخبراء الموحّد =====
-- شغّل هذا الملف مرة واحدة من SQL Editor بلوحة تحكم Supabase.
--
-- الغرض: مرجع موحّد أونلاين لأسماء الخبراء، يحل محل الاعتماد على قاعدة Access
-- المحلية (ExpretDB.MDB) التي لا تتوفر إلا على شبكة الدوام. أي خبير يفتح
-- البرنامج، اسمه المعروض (الموثوق) يُسجَّل هنا تلقائيًا (upsert)، فتتراكم القائمة
-- تدريجيًا وتُقرأ من أي مكان (بيت أو دوام).

CREATE TABLE IF NOT EXISTS experts (
    expert_name TEXT PRIMARY KEY,          -- اسم الخبير كما يظهر بالتطبيق (get_logged_in_name)
    account_no  TEXT,                       -- رقم الحساب (معلومة إضافية فقط — غير موثوق للتخويل)
    first_seen  TIMESTAMPTZ DEFAULT now(),  -- أول مرة فتح فيها البرنامج
    last_seen   TIMESTAMPTZ DEFAULT now()   -- آخر دخول (يُحدَّث كل مرة)
);

-- تفعيل Row Level Security (نفس نهج باقي جداول المشروع)
ALTER TABLE experts ENABLE ROW LEVEL SECURITY;

-- سياسة مؤقتة تسمح بالقراءة/الكتابة عبر anon key (تكفي للمرحلة الحالية —
-- تُضيَّق لاحقًا مع أي طبقة تسجيل دخول حقيقية بـSupabase Auth).
CREATE POLICY "allow_all_experts" ON experts
    FOR ALL USING (true) WITH CHECK (true);
