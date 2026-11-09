# ===== expert_settings.py — إعدادات ثابتة خاصة بكل خبير على حدة =====
"""
إعدادات لا تتغير من قضية لقضية، بل خاصية ثابتة بالخبير نفسه (مثل
شقّه التخصصي وقت محاضر الاستعانة: كهرباء، حاسب آلي، مدني، حسابي...،
وكذلك مكان مكتبه: المقر/الدور/المكتب/الجناح المستخدم بإخطارات
الحكومة).
تُحفظ بمجلد خاص بالخبير الحالي (current_expert.py) — مب مجلد عام
يتشاركه كل من يستخدم نفس الجهاز، لأن التخصص والمكتب يختلفان من خبير
لآخر فعليًا.

ترحيل تلقائي (مرة واحدة فقط): لو الإعداد موجود بالمكان القديم
(العام، قبل هذا التحديث)، يُنقَل (move، لا نسخ) لمجلد أول خبير يفتح
البرنامج بعد التحديث، ويختفي من المكان القديم فورًا — حتى لا يرثه
أي خبير ثاني بالغلط.
"""
import os
import json
from current_expert import expert_data_dir

_OLD_SETTINGS_PATH = os.path.join(
    os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'expert_settings.json'
)

# المقر الافتراضي (نفس المكتوب بقالب إخطار الحكومة) — يقدر الخبير
# يعدّله من الإعدادات، لكن لو ما ضبط شيء نستخدم هذا افتراضيًا.
DEFAULT_MAQAR = 'مبنى الإدارة العامة للخبراء - الرقعي'


def _settings_path():
    return os.path.join(expert_data_dir(), 'expert_settings.json')


def _migrate_if_needed():
    new_path = _settings_path()
    if os.path.exists(new_path):
        return
    if not os.path.exists(_OLD_SETTINGS_PATH):
        return
    try:
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        os.replace(_OLD_SETTINGS_PATH, new_path)
    except Exception:
        pass


def save_specialty(specialty):
    """يحفظ الشق التخصصي للخبير الحالي"""
    data = _load_all()
    data['specialty'] = specialty.strip()
    _save_all(data)


def load_specialty():
    """يرجع الشق التخصصي المحفوظ للخبير الحالي، أو نص فاضي لو ما فيه بعد"""
    return _load_all().get('specialty', '')


def save_location(maqar='', dor='', maktab='', janah=''):
    """
    يحفظ مكان مكتب الخبير الحالي (يُستخدم بإخطارات الحكومة).
    يُضاف مرة واحدة ويُعدّل فقط لو تغيّر مكتب الخبير.
    """
    data = _load_all()
    data['location'] = {
        'maqar': maqar.strip(),
        'dor': dor.strip(),
        'maktab': maktab.strip(),
        'janah': janah.strip(),
    }
    _save_all(data)


def load_location():
    """
    يرجع مكان مكتب الخبير الحالي كـ dict فيه المفاتيح:
    maqar / dor / maktab / janah. المقر يرجع بالقيمة الافتراضية
    لو ما ضُبط بعد (باقي الحقول فاضية).
    """
    loc = _load_all().get('location', {}) or {}
    return {
        'maqar': loc.get('maqar') or DEFAULT_MAQAR,
        'dor': loc.get('dor', ''),
        'maktab': loc.get('maktab', ''),
        'janah': loc.get('janah', ''),
    }


def save_update_folder(path):
    """يحفظ مسار مجلد التحديثات على الشبكة (يستخدمه الأدمن فقط — انظر updater.py)"""
    data = _load_all()
    data['update_folder'] = path.strip()
    _save_all(data)


def load_update_folder():
    """يرجع مسار مجلد التحديثات المحفوظ، أو نص فاضي لو ما فيه بعد"""
    return _load_all().get('update_folder', '')


def save_update_online_url(url):
    """يحفظ رابط التحديث الأونلاين (يُجرّب بعد المصدر الداخلي — انظر updater.py)"""
    data = _load_all()
    data['update_online_url'] = (url or '').strip()
    _save_all(data)


def load_update_online_url():
    """يرجع رابط التحديث الأونلاين المحفوظ، أو نص فاضي لو ما فيه بعد"""
    return _load_all().get('update_online_url', '')


def save_update_version(version):
    """يحفظ رقم النسخة المُدخَل يدويًا للنشر (يستخدمه الأدمن فقط)"""
    data = _load_all()
    data['update_version'] = version.strip()
    _save_all(data)


def load_update_version():
    """يرجع رقم النسخة المحفوظ للنشر، أو نص فاضي لو ما فيه بعد"""
    return _load_all().get('update_version', '')


def save_reports_root(path):
    """يحفظ جذر مجلدات تقارير الخبرة (فارغ = الافتراضي Desktop\تقارير الخبراء)"""
    data = _load_all()
    data['reports_root'] = path.strip()
    _save_all(data)


def load_reports_root():
    """يرجع جذر مجلدات التقارير المحفوظ، أو نص فاضي لو ما ضُبط (يُستخدم الافتراضي)"""
    return _load_all().get('reports_root', '')


def case_minutes_dir(caso_no):
    """البنية المختصرة (2026-10-21): المحاضر تُحفظ في «{مجلد القضية}\مستندات_النظام» باسم «محضر الخبرة رقم N.docx»."""
    import case_workspace
    return os.path.join(case_workspace.case_dir(caso_no), 'مستندات_النظام')


def minute_path(caso_no, num):
    return os.path.join(case_minutes_dir(caso_no), f'محضر الخبرة رقم {int(num)}.docx')


def notice_path(caso_no):
    """الإخطار الحكومي ليس مستنداً للتقرير: في _نظام/إخطارات (مخفي، يُفتح للطباعة مباشرة)."""
    import case_workspace
    return os.path.join(case_workspace.case_dir(caso_no), '_نظام', 'إخطارات', 'اخطار_حكومة.docx')


def minutes_read_dirs(caso_no):
    """أماكن قراءة محاضر القضية: مجلد القضية أولاً، ثم مجلد «محاضر» القديم داخل القضية، ثم «مكان حفظ المحاضر»
    القديم للتوافق فقط (لا يُكتب فيهما جديد)."""
    import case_workspace
    out = []
    for d in (case_minutes_dir(caso_no), os.path.join(case_workspace.case_dir(caso_no), 'محاضر'),
              os.path.join(load_minutes_root(), caso_no or '')):
        if os.path.normcase(os.path.abspath(d)) not in [os.path.normcase(os.path.abspath(x)) for x in out]:
            out.append(d)
    return out


def default_minutes_root():
    return os.path.join(os.path.expanduser('~'), 'Desktop', 'محاضر')


def save_minutes_root(path):
    """يحفظ مكان حفظ المحاضر (فارغ = الافتراضي Desktop\\محاضر). تكتب فيه صفحة الجلسات وتبحث فيه خطوة الإجراءات."""
    data = _load_all()
    data['minutes_root'] = path.strip()
    _save_all(data)


def load_minutes_root():
    """مكان حفظ المحاضر المضبوط، وإلا الافتراضي Desktop\\محاضر (لا يرجع فارغاً)."""
    try:
        return _load_all().get('minutes_root', '') or default_minutes_root()
    except Exception:
        return default_minutes_root()


def _save_all(data):
    path = _settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def _load_all():
    _migrate_if_needed()
    try:
        path = _settings_path()
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_report_header(governorate='', department=''):
    """المحافظة والقسم لترويسة التقرير (يُعبَّآن من نظام الخبراء متى توفرا، ويعدّلهما الخبير من الإعدادات)."""
    data = _load_all()
    data['report_header'] = {'governorate': (governorate or '').strip(), 'department': (department or '').strip()}
    _save_all(data)


def load_report_header():
    h = _load_all().get('report_header', {}) or {}
    return {'governorate': h.get('governorate', ''), 'department': h.get('department', '')}


def resolve_report_header(info=None):
    """
    (المحافظة، القسم) للطباعة — بأولوية: **نظام الخبراء** (سجل الحركة:
    خانة القسم بعد «توزيع للخبراء») ← **إعدادات الخبير**.

    يعني: تجي تلقائية لِمن يناسبه قسمه، وإذا واحد من قسم ثاني يبي يطبع
    المحضر باسم محافظته، يكتبها بالإعدادات وتنعكس هنا (2026-11-09).
    """
    info = info or {}
    hdr = load_report_header()
    gov = (info.get('governorate') or '').strip() or (hdr.get('governorate') or '').strip()
    dep = (info.get('department') or '').strip() or (hdr.get('department') or '').strip()
    return gov, dep
