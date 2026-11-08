# ===== case_autoreview.py — الخطوات الآلية تُعدّ معتمدة تلقائياً متى اكتملت معلوماتها (2026-10-17) =====
# لا زر «اعتماد» للموضوع والمأمورية والمستندات والمرفقات (والإجراءات تعتمد نفسها في case_procedures.re_evaluate).
# القاعدة: كُتبت (done) واكتملت ← reviewed؛ وإلا تبقى «تحتاج مدخلاً» من الخطوة نفسها. أي تعديل يدوي لاحق يعيد الخطوة
# done ثم يعتمدها هذا المرور من جديد، وmark_modified (في دوال التعديل) ينبّه الخطوات اللاحقة.
# الاستثناء: البحث ورأي الخبرة والنتيجة تبقى بمراجعة صريحة («اعتماد رأيي») ولا يلمسها هذا الملف.
import case_model as cm
import case_subject_mission as sm
import case_workspace as cw

TODO = '[يُكتب]'


def run(base, data):
    """يعتمد الخطوات الآلية المكتملة. يرجع True إن غيّر شيئاً (ويكتب case.json)."""
    changed = False
    # ما كتبه البرنامج يُعدّ صحيحاً (النقص تنبيه بسيط لا يحجب)؛ وإن أخطأ يطلب الخبير إعادة الكتابة
    if cm.state(data, 'subject') in ('done', 'needs_input') and (data.get('subject') or '').strip()             and TODO not in data['subject']:
        cm.set_step(data, 'subject', 'reviewed', (data.get('steps', {}).get('subject') or {}).get('message', ''))
        changed = True
    # المأمورية تُعدّ صحيحة ما لم يعدّلها الخبير — لا يُطلب منه «تأكيدها»
    if cm.state(data, 'mission') in ('done', 'needs_input') and (data.get('mission') or {}).get('points'):
        sm.confirm_mission(base, data)
        changed = True
    for key in ('documents', 'attachments'):
        if cm.state(data, key) == 'done':
            cm.set_step(data, key, 'reviewed', (data.get('steps', {}).get(key) or {}).get('message', ''))
            changed = True
    if changed:
        cm.refresh_blocked(data)
        cw.write_case_json(base, data)
    return changed
