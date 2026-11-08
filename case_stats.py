# ===== case_stats.py — محرك إحصائية القضايا (محالة / منجزة / مستبعدة) =====
"""
يحلّل سجل الحركة الفعلي (ECS_CASE_FLOW) لكل قضية ويحدد:
  - تاريخ آخر إحالة فعلية للخبير الحالي (بلوك 'توزيع للخبراء' اللي اسم
    المستلم فيه = الخبير — خانة to_name).
  - تاريخ الإنجاز الفعلي (بلوك 'انجاز القضية' اللي اسم الفاعل فيه =
    الخبير — خانة from_name، عكس بلوك التوزيع). يغطي هذا الحدث تقرير/
    صلح/إعادة كلها بنفس التسمية بالسيرفر.
  - هل انوزعت القضية لخبير ثاني بعد آخر إحالة (حدث 'اعادة توزيع القضية'
    الكامل الموثوق فقط — الصيغة المختصرة 'اعـادة توزيع' سجل تاريخي
    مرجعي مضلِّل وتُتجاهل عمداً).

نتائج كل قضية تُخزَّن بـcase_db (عمود flow_checked_at كعلامة "تم
الفحص") — الفحص الشبكي يصير مرة وحدة لكل قضية إلا لو طُلب تحديث صريح.
"""
import os
import re
import html as html_lib
from datetime import datetime

import requests
import urllib3

urllib3.disable_warnings()
from config import BASE_URL
from api import get_sessions, get_logged_in_name, short_name, parse_case_info
from pending_cases import get_pending_cases, get_reserved_cases, get_title_fallback
import case_db

NORMAL_DIST_LABEL = 'توزيع للخبراء'
SECONDMENT_DIST_LABELS = ('توزيع استعانه بخبير على الخبراء',
                           'توزيع استعانة بخبير على الخبراء')
# قضايا الاستعانة تُسجَّل بسجل الحركة تحت تسمية مختلفة تمامًا (نفس
# التسمية المستخدمة بـui.py وapi.py) — كانت غائبة هنا بالكامل، فأي
# قضية استعانة تختفي بصمت من الإحصائية كلها (لا محالة ولا مستبعدة).
DIST_TO_EXPERT_LABELS = (NORMAL_DIST_LABEL,) + SECONDMENT_DIST_LABELS
COMPLETION_LABEL = 'انجاز القضية'
# إنجاز الخبير المُستعان به يُسجَّل بتسمية مختلفة كليًا عن إنجاز صاحب
# القضية الأصلي — 'انجاز القضية' خاص بصاحب القضية الأصلي بس. لو ما
# ضفنا هذي، كل قضايا الاستعانة تفضل "غير منجزة" للأبد حتى لو خلّصها
# الخبير المُستعان به فعليًا (نفس بنية الحقول [تسمية،قسم،اسم الفاعل،
# قسم،اسم المستلم،رقم إجراء،تاريخ] بالضبط — نفس مكان اسم الفاعل).
COMPLETION_LABELS = (COMPLETION_LABEL, 'انجاز استعانه بخبير', 'انجاز استعانة بخبير')
# ⚠️ REDIST_LABELS / 'اعادة توزيع القضية': جرّبنا الاعتماد على هذا
# الحدث مرتين لتحديد "الاستبعاد" وفشل الاثنتين — تأكدنا من بيانات
# حقيقية (قضية لجنة فعلية) إن عرضه غير ثابت العرض: خانة "إلى موظف"
# تختفي من HTML كليًا لو فاضية (مو &nbsp، حرفيًا غير موجودة)، فتتزحزح
# كل الفهارس بعدها بدون أي طريقة موثوقة للتفريق. والأخطر: حتى لو
# الخانة موجودة، اسمها يمثّل "أي عضو لجنة خلّص دوره وتحرّك الملف
# داخليًا"، مو "مين استلم القضية" ولا "مين أُبعد عنها" — أي عضو لجنة
# غيري يخلّص دوره يولّد نفس الحدث بدون أي علاقة بوضعي أنا بالقضية.
# الاعتماد عليه كان يعتبر أي نشاط داخلي بين أعضاء اللجنة استبعادًا لي
# بالغلط. البديل الموثوق (تحت): نفس أسلوب get_experts في ui.py —
# نجمّع كتل 'توزيع للخبراء' المتتالية بنفس التاريخ كلجنة واحدة، ونشوف
# هل أنا عضو بآخر كتلة فعليًا، بدل تفسير حدث 'اعادة التوزيع' المبهم.
DATE_RE = re.compile(r'^\d{2}/\d{2}/\d{4}$')


def name_matches(my_name, full_name):
    """يطابق بالاسم الأول والأخير بس (سجل الحركة يعرض الاسم كامل بأسماء
    الأب/الجد بينهم، بينما my_name مختصر لأول واسم أخير فقط)."""
    if not my_name or not full_name:
        return False
    parts = my_name.split()
    if len(parts) < 2:
        return parts[0] in full_name
    first, last = parts[0], parts[-1]
    return first in full_name and last in full_name


def _parse_flow(cookies, caso_no):
    r = requests.post(f"{BASE_URL}/ECS_CASE_FLOW",
        data={'P_CASES': caso_no}, cookies=cookies, verify=False, timeout=15)
    tds = re.findall(r'<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
    tds = [re.sub(r'<[^>]+>', ' ', t).strip() for t in tds]
    tds = [t for t in tds if t and t != '&nbsp']
    return tds


# تسميات الإجراءات الإدارية المعروفة (بلوك 7 خانات: تسمية، قسم1،
# اسم1، قسم2، اسم2، رقم إجراء، تاريخ) — مجمّعة من عدة قضايا حقيقية
# فحصناها (تجارية، تأمين، ترميمات، استعانة درايه...). أي تسمية جديدة
# غير موجودة هنا تُعرض كسطر خام بدل ما تُفقد أو تكسر الترتيب.
ADMIN_ACTION_LABELS = {
    'توزيع القضايا على المراقبات', 'توزيع للاقسام', 'توزيع للخبراء',
    'توزيع استعانه بخبير على الخبراء', 'توزيع استعانة بخبير على الخبراء',
    'توزيع استعانه بخبير على المراقبات', 'توزيع استعانه بخبير على الأقسام',
    'توزيع استعانه على الوارد',
    'انجاز القضية', 'انجاز استعانه بخبير', 'انجاز استعانة بخبير',
    'اعادة توزيع القضية', 'اعادة توزيع طلب الاستعانه',
    'مباشرة القضية', 'طلب اعلان',
    'طلب استعانة بخبير', 'متابعة طلب استعانة بخبير',
    'طلب استعانه بخبير درايه', 'متابعة طلب استعانه بخبير درايه',
    'استلام قسم الاسناد الفنى طلب الاستعانه',
    'انجاز خبير الدرايه لطلب الاستعانه',
    'ارسال انجاز الدرايه الى رئيس القسم الفنى',
    'ارسال انجاز الدرايه للخبير الاصلى',
    'استلام الخبير لانجاز الدرايه',
    'ارسال انجاز الاستعانه للخبير الاصلى',
    'استلام الخبير الاصلى (انجاز/اعادة)  الاستعانه',
    'موافقة و تصدير', 'مطلوبه للتفتيش', 'معاد للمراقب',
}
# أنواع الجلسات (بلوك 7 خانات مختلف الترتيب: اسم، نوع، تاريخ، وقت،
# خانتين فاضيتين عادة، مكان) — نتعرف عليها بادئة النص لأن بعضها يُكتب
# بشرطات ممدودة (مناقشـــة) تختلف بعدد الشرطات بين قضية وثانية.
SESSION_TYPE_PREFIXES = (
    'فتح محضر', 'مناقش', 'جلسه محكمه', 'جلسة محكمة', 'معاين',
    'للاعلان', 'حجز للاعادة', 'حجز للتقرير', 'حجز للصلح',
    'انتظار الخبير المستعان',
)


def get_case_actions(cookies, caso_no):
    """
    يرجع كل الإجراءات والجلسات المسجَّلة على القضية كقائمة منظّمة مرتبة
    من الأقدم للأحدث: [{'date': 'DD/MM/YYYY', 'time': '', 'action': '',
    'from_name': '', 'from_dept': '', 'to_name': '', 'to_dept': ''}].
    للجلسات: from = الخبير، to = مكان الجلسة. مبني فوق tds الخام
    (_parse_flow) بدون أي طلب شبكي إضافي.
    """
    tds = _parse_flow(cookies, caso_no)
    events = []  # (date_obj, dict)
    i, n = 0, len(tds)
    while i < n:
        label = tds[i].strip()

        if label in ADMIN_ACTION_LABELS and i + 6 < n:
            block = tds[i:i + 7]
            _, dept1, name1, dept2, name2, _action_no, date_str = block
            if DATE_RE.match(date_str):
                try:
                    d = datetime.strptime(date_str, '%d/%m/%Y')
                    events.append((d, {
                        'date': date_str, 'time': '', 'action': label,
                        'from_name': name1, 'from_dept': dept1,
                        'to_name': name2, 'to_dept': dept2}))
                except Exception:
                    pass
                i += 7
                continue

        if i + 6 < n:
            name_cand = tds[i].strip()
            type_cand = tds[i + 1].strip()
            if len(name_cand) > 5 and any(type_cand.startswith(p) for p in SESSION_TYPE_PREFIXES):
                date_str = tds[i + 2].strip()
                time_str = tds[i + 3].strip()
                loc = tds[i + 6].strip()
                if DATE_RE.match(date_str):
                    try:
                        d = datetime.strptime(date_str, '%d/%m/%Y')
                        events.append((d, {
                            'date': date_str, 'time': time_str,
                            'action': f"جلسة «{type_cand}»",
                            'from_name': name_cand, 'from_dept': '',
                            'to_name': loc if loc and loc != 'لا يوجد' else '',
                            'to_dept': ''}))
                    except Exception:
                        pass
                    i += 7
                    continue

        i += 1

    events.sort(key=lambda e: e[0])
    return [e[1] for e in events]


def build_case_actions_text(cookies, caso_no):
    """نسخة نصية من get_case_actions (للاستخدام النصي/التشخيص)."""
    acts = get_case_actions(cookies, caso_no)
    if not acts:
        return "ما لقيت أي إجراءات مفهومة بسجل الحركة لهذي القضية."
    lines = [f"سجل إجراءات القضية {caso_no} — {len(acts)} إجراء/جلسة\n"]
    for idx, a in enumerate(acts, start=1):
        when = f"{a['date']} {a['time']}".strip()
        frm = a['from_name'] + (f" ({a['from_dept']})" if a['from_dept'] else '')
        to = a['to_name'] + (f" ({a['to_dept']})" if a['to_dept'] else '')
        lines.append(f"{idx}. [{when}] {a['action']} — {frm}" + (f" ← {to}" if to else ''))
    return '\n'.join(lines)


def dump_case_flow_debug(cookies, caso_no, my_name=''):
    """
    أداة تشخيص فقط — ترجع نص فيه كل خلية بسجل الحركة الخام مرقّمة
    بترتيبها بالضبط، عشان نتأكد بشكل مباشر من ترتيب/عدد الخانات
    الحقيقي بدل الاعتماد على افتراضات (خصوصاً بالحالات المعقّدة: لجان،
    إعادة توزيع). لا تُستخدم بأي منطق فعلي بالبرنامج — تشخيص يدوي بس.
    """
    tds = _parse_flow(cookies, caso_no)
    lines = [f"عدد الخلايا الكلي: {len(tds)}", f"اسم المطابقة (my_name): {my_name!r}", ""]
    for i, t in enumerate(tds):
        marker = ""
        if t.strip() in DIST_TO_EXPERT_LABELS:
            marker = "  ← [توزيع للخبراء/استعانة]"
        elif t.strip() == 'اعادة توزيع القضية':
            marker = "  ← [اعادة توزيع القضية (غير مستخدم بالمنطق الآن)]"
        elif t.strip() in COMPLETION_LABELS:
            marker = "  ← [انجاز]"
        lines.append(f"[{i:3d}] {t}{marker}")
    return '\n'.join(lines)


# فارق أيام مسموح بين توزيع أعضاء نفس اللجنة (انظر تفسير كامل داخل
# _build_dist_clusters) — قضية حقيقية وزّعت أعضاء لجنتها على يومين
# متتاليين وانقسمت غلط لكتلتين قبل هذا التصحيح.
MAX_CLUSTER_GAP_DAYS = 3


def _build_dist_clusters(tds):
    """
    يبني قائمة 'كتل التوزيع' (لجان/أفراد) بترتيبها الزمني الفعلي —
    نواة مشتركة بين analyze_case_flow (فحص خبير معيّن) وget_case_snapshot
    (لقطة عامة عن أي قضية بغض النظر عن الخبير). كل كتلة:
    {'type': 'normal'|'secondment', 'members': [...], 'date': datetime}.

    منهجية التجميع: نفس أسلوب get_experts المُثبَت بـui.py — نجمّع كل
    أحداث 'توزيع للخبراء' المتتالية بفارق أيام قليل (≤3، يغطي توزيع
    إداري لأعضاء نفس اللجنة على أكثر من يوم) كـ'لجنة' واحدة، أحداث
    الاستعانة تبقى كتل مستقلة بدون تجميع.
    """
    entries = []
    for i, td in enumerate(tds):
        label = td.strip()
        is_normal = label == NORMAL_DIST_LABEL
        is_secondment = label in SECONDMENT_DIST_LABELS
        if not (is_normal or is_secondment):
            continue
        block = tds[i:i + 7]
        if len(block) != 7:
            continue
        to_name, date_str = block[4], block[6]
        if not to_name or len(to_name) <= 5 or not DATE_RE.match(date_str):
            continue
        try:
            d = datetime.strptime(date_str, '%d/%m/%Y')
        except Exception:
            continue
        entries.append({'type': 'secondment' if is_secondment else 'normal',
                         'name': to_name, 'date': d})

    clusters = []
    for e in entries:
        prev = clusters[-1] if clusters else None
        can_merge = (e['type'] == 'normal' and prev is not None
                     and prev['type'] == 'normal'
                     and abs((e['date'] - prev['date']).days) <= MAX_CLUSTER_GAP_DAYS)
        if can_merge:
            if e['name'] not in prev['members']:
                prev['members'].append(e['name'])
        else:
            clusters.append({'type': e['type'], 'members': [e['name']], 'date': e['date']})
    return clusters


def _completions_for(tds, names):
    """كل أحداث الإنجاز (COMPLETION_LABELS) اللي فاعلها يطابق أي اسم من
    القائمة المُمرَّرة — يرجع قائمة (date, actor_name)."""
    out = []
    for i, td in enumerate(tds):
        if td.strip() not in COMPLETION_LABELS:
            continue
        block = tds[i:i + 7]
        if len(block) != 7:
            continue
        actor_name, date_str = block[2], block[6]
        if not DATE_RE.match(date_str):
            continue
        if any(name_matches(n, actor_name) for n in names):
            try:
                out.append((datetime.strptime(date_str, '%d/%m/%Y'), actor_name))
            except Exception:
                pass
    return out


def get_autocase_no(caso_no, cookies):
    """يجيب الرقم الآلي (autocase_no) مباشرة من basic_info_result.php —
    يعمل لأي رقم خبرة بغض النظر عن كونه متداول عندي أنا شخصيًا أو لأ
    (بعكس البحث بقوائم pending_cases المحدودة لخبير واحد)."""
    try:
        r = requests.post(
            f"{BASE_URL}/includes/basic_info_result.php",
            data={'id': '1', 'title': caso_no, 'met_date': '', 'met_time': '', 'description': caso_no},
            cookies=cookies, verify=False, timeout=10
        )
        numbers = re.findall(r'\b\d{6,9}\b', r.text)
        return numbers[0] if numbers else ''
    except Exception:
        return ''


def get_case_snapshot(cookies, caso_no):
    """
    لقطة شاملة عن حالة أي قضية الآن — بغض النظر عن هوية الخبير
    (لاستخدام رئيس القسم بأداة البحث). يرجع dict:
      found: bool — فيه أي توزيع أصلاً
      is_committee, holder_type ('normal'|'secondment'), current_holders
      last_referral_date, completed, completion_date, completed_by
    """
    tds = _parse_flow(cookies, caso_no)
    clusters = _build_dist_clusters(tds)
    if not clusters:
        return {'found': False}

    latest = clusters[-1]
    completions = _completions_for(tds, latest['members'])
    relevant = [d for d, _ in completions if d >= latest['date']]
    completed = bool(relevant)
    completion_date = max(relevant) if relevant else None
    completed_by = next((n for d, n in completions if d == completion_date), None) if completed else None

    return {
        'found': True,
        'is_committee': len(latest['members']) > 1,
        'holder_type': latest['type'],
        'current_holders': latest['members'],
        'last_referral_date': latest['date'],
        'completed': completed,
        'completion_date': completion_date,
        'completed_by': completed_by,
    }


def get_upcoming_session_for_case(cookies, caso_no):
    """أقرب جلسة قادمة (تاريخ >= اليوم) لأي قضية — لاستخدام أداة البحث
    مع القضايا الغير منجزة. يرجع dict {'date','time','type'} أو None."""
    try:
        from api import get_all_case_sessions
        sessions = get_all_case_sessions(cookies, caso_no)
    except Exception:
        return None
    today = datetime.now().strftime('%Y-%m-%d')
    upcoming = []
    for s in sessions or []:
        parts = (s.get('start') or '').split(' ')
        date = (parts[0] if parts else '').replace('/', '-')
        time = parts[1] if len(parts) > 1 else ''
        if date and date >= today:
            upcoming.append({'date': date, 'time': time, 'title': s.get('title', '')})
    if not upcoming:
        return None
    upcoming.sort(key=lambda s: (s['date'], s['time']))
    return upcoming[0]


# تسميات إعادة التوزيع الكاملة (بلوك 7 خانات: تسمية، قسم1، اسم الفاعل،
# قسم2، اسم2، رقم إجراء، تاريخ — الفاعل في block[2] مثل الإنجاز تمامًا،
# مؤكَّد من سجل حقيقي: 'اعادة توزيع القضية' → block[2] = من أعاد التوزيع).
# ⚠️ نعتمد فقط الصيغة الكاملة 'اعادة توزيع القضية'/'اعادة توزيع طلب
# الاستعانه' (7 خانات). الصيغة المختصرة 'اعـادة توزيع' (بشرطة ممدودة، 5
# خانات، سجل تاريخي مرجعي) تُتجاهل عمدًا — بنيتها مختلفة وغير موثوقة.
REDIST_LABELS = ('اعادة توزيع القضية', 'اعادة توزيع طلب الاستعانه',
                 'اعادة توزيع طلب الاستعانة')


def _my_actions_in_order(tds, my_name):
    """
    يمرّ على كل بلوكات الأحداث (7 خانات) ويجمع الأحداث التي **فاعلها**
    (block[2]) يطابق الخبير المعني فقط — مع الاحتفاظ بموضعها (index) في
    السجل. يرجع قائمة (index, kind, date) مرتبة بالـindex، حيث kind من:
    'completion' (إنجاز) / 'redistribute' (إعادة توزيع) / 'mubashara'
    (مباشرة). الاعتماد على الـindex (لا التاريخ) ضروري لأن أحداث الخبير
    قد تقع بنفس اليوم (إنجاز ثم إعادة توزيع بنفس التاريخ) — الترتيب
    الحقيقي هو ترتيب ظهورها بالسجل، لا تاريخها.
    """
    actions = []
    for i, td in enumerate(tds):
        label = td.strip()
        if label in COMPLETION_LABELS:
            kind = 'completion'
        elif label in REDIST_LABELS:
            kind = 'redistribute'
        elif label == 'مباشرة القضية':
            kind = 'mubashara'
        else:
            continue
        block = tds[i:i + 7]
        if len(block) != 7:
            continue
        actor_name, date_str = block[2], block[6]
        if not name_matches(my_name, actor_name):
            continue
        d = None
        if DATE_RE.match(date_str):
            try:
                d = datetime.strptime(date_str, '%d/%m/%Y')
            except Exception:
                d = None
        actions.append((i, kind, d))
    return actions


def analyze_case_flow(cookies, caso_no, my_name):
    """يرجّع dict: {'referred', 'referral_date', 'completed',
    'completion_date', 'is_redistributed'} — referral_date/completion_date
    كائنات datetime أو None.

    ✅ المنهجية الجديدة (مبنية على قاعدة عمل القسم الفعلية، مؤكَّدة من
    قضايا حقيقية): القرار يعتمد **حصريًا على أفعال الخبير المعني نفسه**
    (اسمه في خانة الفاعل block[2])، وننظر إلى **آخر فعل له** بالسجل
    (بترتيب الظهور index، لا التاريخ — لأن الإنجاز وإعادة التوزيع قد
    يقعان بنفس اليوم):
      • آخر فعل = إنجاز (أي نوع، بما فيه حجز للإعادة للمحكمة) → محسوبة (منجزة).
      • آخر فعل = إعادة توزيع (الخبير أعادها بنفسه بعد مباشرتها) → مستبعدة.
      • آخر فعل = مباشرة فقط (بلا إنجاز/إعادة بعده) → محالة غير منجزة (لسه معه).
      • لا يوجد أي فعل له إطلاقًا (اعتذر/لم يباشر) → ليست قضيته.

    هذا يحل خطأين قديمين: (١) الاعتماد على "آخر كتلة توزيع" كان يعتبر
    الاستعانات المتوازية إعادة توزيع بالغلط؛ (٢) الاعتماد على أي حدث
    إعادة توزيع (لأي خبير) كان يستبعد قضايا اللجان بالغلط. الآن كل شيء
    مربوط بأفعال الخبير المعني فقط.

    referral_date: تاريخ آخر توزيع اسم الخبير فيه (من كتل التوزيع) —
    للعرض والتصنيف الزمني بالإحصائية."""
    tds = _parse_flow(cookies, caso_no)
    clusters = _build_dist_clusters(tds)

    # تاريخ آخر إحالة للخبير — من كتل التوزيع التي هو عضو فيها (للعرض فقط)
    def cluster_has_me(c):
        return any(name_matches(my_name, n) for n in c['members'])

    my_clusters = [c for c in clusters if cluster_has_me(c)]
    last_referral = max((c['date'] for c in my_clusters), default=None)

    # أفعال الخبير المعني نفسه بترتيب ظهورها بالسجل (index, kind, date)
    actions = _my_actions_in_order(tds, my_name)

    # ===== شرط الدخول الأساسي: المباشرة =====
    # القاعدة الفعلية للقسم: لا تُحسب القضية للخبير إطلاقًا إلا إذا عمل
    # لها "مباشرة القضية" بنفسه. بدون مباشرة، القضية ليست من قضاياه مهما
    # صار فيها (سواء اعتذر عنها وردّها لرئيس القسم قبل المباشرة، أو مجرد
    # توزيع إداري عليه لم يستلمه فعليًا) — فتختفي كليًا من الإحصائية
    # (لا محالة ولا مستبعدة). هذا يميّز الحالة 3 (باشر ثم أعاد التوزيع =
    # مستبعدة) عن الحالة 2 (اعتذر بلا مباشرة = ليست قضيته أصلًا).
    has_mubashara = any(k == 'mubashara' for _, k, _ in actions)
    if not has_mubashara:
        return {'referred': False, 'referral_date': None, 'completed': False,
                'completion_date': None, 'is_redistributed': False}

    # ===== تاريخ إحالة احتياطي =====
    # ما كل قضية عندها تاريخ إحالة مسجّل: تكفي إن الخبير «باشر القضية»
    # عشان تكون قضيته، بس لو ما طلع اسمه بأي كتلة توزيع (اسم بصيغة ثانية،
    # أو سطر توزيع بصيغة غير معروفة) يبقى last_referral = None.
    # كانت هذه القضايا — حتى المنجزة منها — تسقط بصمت من تقرير الإحصائية
    # و«ملفاتي»، لأن الفلترة كانت تشترط تاريخ الإحالة.
    # فنستخدم تاريخ أول «مباشرة القضية» عنده: أقرب تاريخ صحيح متوفر،
    # والحقل موثّق أصلاً إنه «للعرض والتصنيف الزمني فقط» (لا تاريخ قانوني).
    if last_referral is None:
        last_referral = next((d for _, k, d in actions if k == 'mubashara' and d), None)

    # آخر فعل فعلي للخبير (أكبر index) هو الحاسم
    last_action = actions[-1] if actions else None

    # آخر فعل = إعادة توزيع (بعد مباشرة سابقة) → مستبعدة (الحالة 3)
    if last_action and last_action[1] == 'redistribute':
        return {'referred': False, 'referral_date': last_referral, 'completed': False,
                'completion_date': None, 'is_redistributed': True}

    # آخر إنجاز للخبير لم يعقبه إعادة توزيع → منجزة (الحالتان 1 و 4)
    completion_date = None
    for idx, kind, d in reversed(actions):
        if kind == 'redistribute':
            break  # إعادة توزيع أحدث من أي إنجاز — عولجت أعلاه
        if kind == 'completion':
            completion_date = d
            break

    completed = completion_date is not None

    # باشر ولم يُعِد التوزيع → قضيته (محالة)، منجزة لو فيها إنجاز وإلا جارية
    return {
        'referred': True, 'referral_date': last_referral,
        'completed': completed, 'completion_date': completion_date,
        'is_redistributed': False,
    }


def get_my_name(cookies):
    return short_name(get_logged_in_name(cookies) or '')


def get_candidate_cases(cookies, date_from=None, date_to=None):
    """
    يجمع أرقام القضايا المرشّحة للفحص الشبكي (سجل الحركة) — بس اللي
    لها احتمال حقيقي إنها ضمن فترة الإحصائية المطلوبة، بدل فحص كل
    قضية مرّت على هذا الجهاز من 2012.

    المصدر: جلسات النظام اللي تاريخها يقع ضمن [date_from - هامش 120
    يوم، date_to] — أي قضية أُحيلت بالفترة غالباً بيكون لها أول جلسة
    (فتح محضر/حجز) قريبة من تاريخ الإحالة. + القضايا المتداولة/
    المحجوزة حالياً دايماً (مفتوحة الحين بغض النظر عن تاريخ جلستها).

    لو date_from غير مُمرَّر: يرجع لسلوك قديم (كل التاريخ) — يُستخدم
    فقط لو احتجنا فحص شامل صريح.
    """
    candidates = set()

    # ⚠️ start/end بالرابط ما يفلترهم السيرفر فعلياً (مؤكد بالتجربة —
    # يرجّع نفس البيانات الكاملة بغض النظر عنهم)، فنطلب النطاق كامل
    # مرة وحدة (طلب شبكة واحد بس، رخيص) ونفلتر محلياً بحقل 'start'
    # لكل جلسة. ⚠️ عمداً بدون try/except هنا — لو فشل هذا المصدر لازم
    # نعرف بالضبط ليش (كوكيز منتهية، خطأ شبكة...)، بدل ما نرجع بصمت
    # لقائمة ناقصة (القضايا المتداولة بس) بدون أي تنبيه.
    sessions = get_sessions(cookies, "2010-01-01", "2035-01-01")
    if not isinstance(sessions, list):
        raise RuntimeError(f"استجابة غير متوقعة من load.php: {type(sessions)}")

    if date_from is not None:
        # نفس الفلترة المُجرَّبة بالضبط: جلسة تاريخها من date_from
        # فأعلى (بدون أي هامش إضافي) — القضايا المُحالة فعلاً بالفترة
        # يكون لها نشاط جلسات من نفس الفترة أو بعدها.
        margin_start = date_from.strftime('%Y-%m-%d')
        sessions = [
            s for s in sessions
            if (s.get('start', '') or '')[:10] >= margin_start
        ]

    candidates.update(
        s.get('description', '') for s in sessions if s.get('description')
    )

    try:
        for c in get_pending_cases(cookies):
            candidates.add(c['caso_no'])
    except Exception:
        pass

    try:
        for c in get_reserved_cases(cookies):
            candidates.add(c['caso_no'])
    except Exception:
        pass

    candidates.discard('')
    return sorted(candidates)


def get_case_parties(cookies, caso_no, current_user=''):
    """يرجّع (المدعي، المدعى عليه) كنص — من القاعدة المحلية أولاً، وإلا
    حياً من parse_case_info."""
    try:
        cached = case_db.get_case(caso_no)
        if cached and (cached.get('plaintiffs') or cached.get('defendants')):
            pl = cached.get('plaintiffs') or []
            df = cached.get('defendants') or []
            return ('، '.join(pl) if pl else '—', '، '.join(df) if df else '—')
    except Exception:
        pass

    try:
        info = parse_case_info(caso_no, cookies, current_user)
        pl = info.get('plaintiffs', [])
        df = info.get('defendants', [])
        return ('، '.join(pl) if pl else '—', '، '.join(df) if df else '—')
    except Exception:
        return ('—', '—')


def run_full_scan(cookies, current_user, date_from=None, date_to=None,
                   force_refresh=False, progress_cb=None, error_cb=None):
    """
    يفحص القضايا المرشّحة ضمن فترة [date_from, date_to] بس (+هامش
    زمني بسيط، انظر get_candidate_cases) ويحدّث case_db لكل وحدة لم
    تُفحص بعد (أو الكل لو force_refresh=True). progress_cb (اختياري):
    يُستدعى بـ(index, total, caso_no) بعد كل قضية — لعرض شريط تقدم.
    error_cb (اختياري): يُستدعى بـ(caso_no, exception) عند فشل فحص قضية
    واحدة — عشان الواجهة تقدر تنبّه المستخدم بدل ابتلاع الخطأ (في ملف EXE
    بدون كونسول، print ما ينشاف ولا حد يدري إن قضية ما فُحصت).

    يرجع قائمة أرقام القضايا اللي انفحصت فعلياً بهذا التشغيل (جديدة أو
    مُحدَّثة) — القضايا المخزّنة سابقاً وما احتاجت فحص لا تُرجَّع هنا.
    """
    my_name = get_my_name(cookies)
    candidates = get_candidate_cases(cookies, date_from=date_from, date_to=date_to)
    checked = []

    total = len(candidates)
    for idx, caso_no in enumerate(candidates, start=1):
        needs_check = force_refresh or not case_db.get_case_stats(caso_no, my_name)
        if needs_check:
            try:
                result = analyze_case_flow(cookies, caso_no, my_name)
                case_db.save_case_stats(
                    caso_no, my_name,
                    referral_date_actual=(
                        result['referral_date'].strftime('%Y-%m-%d')
                        if result['referral_date'] else ''
                    ),
                    completion_date_actual=(
                        result['completion_date'].strftime('%Y-%m-%d')
                        if result['completion_date'] else ''
                    ),
                    is_redistributed=result['is_redistributed'],
                )
                # نعبّي عنوان القضية لو ناقص (لازم للتقرير النهائي)
                existing = case_db.get_case(caso_no)
                if (result['referred'] or result['is_redistributed']) and not (existing and existing.get('title')):
                    try:
                        title = get_title_fallback(cookies, caso_no)
                        if title:
                            case_db.save_case(caso_no, title=title)
                    except Exception:
                        pass
                checked.append(caso_no)
            except Exception as e:
                # ما نخفي الخطأ: نمرّره للواجهة (error_cb) ونطبعه كمان.
                # سابقاً كان print فقط — وفي EXE بدون كونسول ما ينشاف، فتبتلع
                # الفشل بصمت وتطلع إحصائية ناقصة بدون أي تنبيه.
                print(f"run_full_scan ERROR ({caso_no}): {e}")
                if error_cb:
                    try:
                        error_cb(caso_no, e)
                    except Exception:
                        pass

        if progress_cb:
            try:
                progress_cb(idx, total, caso_no)
            except Exception:
                pass

    return checked


def build_report_data(date_from, date_to, cookies=None, current_user=''):
    """
    يقرأ من case_db (بعد ما run_full_scan يكون خلّص) ويبني 3 قوائم
    ضمن فترة [date_from, date_to] (كائنات datetime):
      referred: محالة فعلياً (تشمل المنجزة وغير المنجزة)
      completed: subset من referred اللي فيها تاريخ إنجاز
      excluded: القضايا اللي انوزعت لخبير ثاني (مستبعدة) وتاريخ آخر
        إحالة لها يقع بالفترة — كل عنصر فيه أيضاً أطراف القضية
        (plaintiff/defendant) عشان يُعرف مين هي، حسب طلب المستخدم.
    كل عنصر: dict فيه caso_no, title, referral_date, completion_date
    (وplaintiff/defendant لعناصر excluded فقط).
    """
    sf = date_from.strftime('%Y-%m-%d')
    ef = date_to.strftime('%Y-%m-%d')

    # الفحص (run_full_scan) يخزّن نتائجه دائمًا تحت my_name (الصيغة
    # المختصرة من get_my_name — نفس الاسم المستخدم فعليًا لمطابقة سجل
    # الحركة). لازم نقرأ بنفس المفتاح بالضبط هنا، وإلا ما نلقى الصفوف
    # اللي فحصها run_full_scan توّه لنفس الخبير (current_user قد يوصل
    # بصيغة مختلفة — الاسم الكامل مثلاً). لو فيه كوكيز، نحسبه حيًا
    # بنفس الطريقة لضمان التطابق دائمًا؛ وإلا نرجع لـcurrent_user كخط
    # دفاع أخير.
    expert_key = get_my_name(cookies) if cookies else (current_user or '')

    rows = case_db.get_all_checked_stats(expert_key)

    referred, completed, excluded = [], [], []

    for r in rows:
        rd = r.get('referral_date_actual') or ''
        cd = r.get('completion_date_actual') or ''
        # تاريخ الإحالة هو المرجع الأساسي للفترة. لكن ما كل قضية عندها تاريخ
        # إحالة مسجّل (باشرها الخبير وما طلع باسمه بأي كتلة توزيع) — وكانت
        # هذه تسقط بصمت من الثلاث قوائم، حتى المنجزة منها.
        # القاعدة الآن: الإحالة لها الأولوية؛ لو ما عندنا إحالة نفلتر بتاريخ
        # الإنجاز؛ لو ما عندنا الاثنين تُستبعد (ما عندها أي تاريخ).
        if rd:
            in_period = sf <= rd <= ef
        elif cd:
            in_period = sf <= cd <= ef
        else:
            continue
        if not in_period:
            continue

        entry = {
            'caso_no': r['caso_no'],
            'title': r.get('title') or '',
            'referral_date': rd,
            'completion_date': cd,
            # True يعني: ما فيه تاريخ إحالة مسجّل — معروض تاريخ الإنجاز مع علامة
            'referral_date_inferred': not rd,
        }

        if r.get('is_redistributed') == '1':
            if cookies:
                pl, df = get_case_parties(cookies, r['caso_no'], current_user)
                entry['plaintiff'] = pl
                entry['defendant'] = df
            else:
                entry['plaintiff'] = entry['defendant'] = '—'
            excluded.append(entry)
        else:
            referred.append(entry)
            if entry['completion_date']:
                completed.append(entry)

    referred.sort(key=lambda x: x['referral_date'])
    completed.sort(key=lambda x: x['completion_date'])
    excluded.sort(key=lambda x: x['referral_date'])

    return referred, completed, excluded


def _disp_date(d):
    try:
        return datetime.strptime(d, '%Y-%m-%d').strftime('%Y/%m/%d')
    except Exception:
        return d or '—'


def build_full_stats_report_html(referred, completed, excluded, date_from, date_to, expert_name):
    """
    يبني تقرير HTML واحد قابل للطباعة (نفس أسلوب weekly_report.py):
    قسم 'القضايا المحالة' كامل، وقسم 'القضايا المنجزة' (subset منها)،
    وفي الآخر قسم 'القضايا المستبعدة' (المعاد توزيعها) مع أطرافها.
    يرجع مسار ملف HTML المُنشأ.
    """
    def esc(t):
        return html_lib.escape(str(t or ''))

    def referred_rows():
        if not referred:
            return '<tr><td colspan="5" class="empty">لا توجد قضايا محالة ضمن هذه الفترة</td></tr>'
        out = ''
        for i, c in enumerate(referred, start=1):
            status = 'منجزة' if c['completion_date'] else 'غير منجزة'
            status_cls = 'ok' if c['completion_date'] else 'pending'
            # تاريخ الإحالة غير مسجّل في النظام → معروض تاريخ الإنجاز مع علامة *
            disp = c['referral_date'] or c.get('completion_date') or ''
            mark = '*' if c.get('referral_date_inferred') else ''
            out += (
                '<tr>'
                f'<td class="c">{i}</td>'
                f'<td class="c">{esc(_disp_date(disp))}{mark}</td>'
                f'<td class="c"><b>{esc(c["caso_no"])}</b></td>'
                f'<td class="e">{esc(c["title"]) or "—"}</td>'
                f'<td class="c {status_cls}">{status}</td>'
                '</tr>'
            )
        return out

    def referred_note():
        """حاشية توضّح علامة * — قضايا ما توفّر لها تاريخ إحالة مسجّل"""
        if not any(c.get('referral_date_inferred') for c in referred):
            return ''
        return ('<p class="note">* تاريخ الإحالة غير مسجّل في النظام لهذه القضايا '
                '— المعروض هو تاريخ الإنجاز.</p>')

    def completed_rows():
        if not completed:
            return '<tr><td colspan="4" class="empty">لا توجد قضايا منجزة ضمن هذه الفترة</td></tr>'
        out = ''
        for i, c in enumerate(completed, start=1):
            out += (
                '<tr>'
                f'<td class="c">{i}</td>'
                f'<td class="c">{esc(_disp_date(c["completion_date"]))}</td>'
                f'<td class="c"><b>{esc(c["caso_no"])}</b></td>'
                f'<td class="e">{esc(c["title"]) or "—"}</td>'
                '</tr>'
            )
        return out

    def excluded_rows():
        if not excluded:
            return '<tr><td colspan="5" class="empty">لا توجد قضايا مستبعدة (معاد توزيعها) ضمن هذه الفترة</td></tr>'
        out = ''
        for i, c in enumerate(excluded, start=1):
            out += (
                '<tr>'
                f'<td class="c">{i}</td>'
                f'<td class="c"><b>{esc(c["caso_no"])}</b></td>'
                f'<td class="e">{esc(c.get("plaintiff", "—"))}</td>'
                f'<td class="e">{esc(c.get("defendant", "—"))}</td>'
                f'<td class="c">{esc(_disp_date(c["referral_date"]))}</td>'
                '</tr>'
            )
        return out

    period_disp = f"{date_from.strftime('%Y/%m/%d')} — {date_to.strftime('%Y/%m/%d')}"
    generated_at = datetime.now().strftime('%Y/%m/%d %H:%M')

    html_doc = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>الإحصائية</title>
<style>
  @page {{ size: A4 portrait; margin: 14mm 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
    direction: rtl; color: #1e2535; margin: 0; padding: 0;
  }}
  .header {{ text-align: center; border-bottom: 4px solid #1e2535; padding-bottom: 12px; margin-bottom: 20px; }}
  .header h1 {{ font-size: 26px; margin: 0 0 8px; }}
  .header .sub {{ font-size: 15px; color: #5a6a80; }}
  .meta {{ display: flex; justify-content: space-between; font-size: 14px; margin-bottom: 16px; }}
  .meta b {{ color: #1e2535; }}
  h2.section {{ font-size: 17px; margin: 26px 0 10px; padding-right: 10px; border-right: 5px solid #1e2535; }}
  h2.section.excluded {{ border-right-color: #e74c3c; color: #c0392b; }}
  table {{ width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 12.5px; border: 2.5px solid #1e2535; }}
  th {{ background: #1e2535; color: #fff; padding: 8px 6px; text-align: center; border: 2px solid #1e2535; font-size: 12.5px; }}
  td {{ border: 2px solid #1e2535; padding: 6px; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word; }}
  td.c {{ text-align: center; white-space: nowrap; }}
  td.e {{ text-align: right; white-space: normal; }}
  td.ok {{ color: #178a63; font-weight: 700; }}
  td.pending {{ color: #b8860b; font-weight: 700; }}
  tr:nth-child(even) td {{ background: #f7f9fc; }}
  .empty {{ text-align: center; color: #94a3b8; padding: 24px; font-size: 13px; }}
  .note {{ font-size: 11px; color: #94a3b8; margin: 6px 0 0; }}
  .excluded-table {{ border-color: #e74c3c; }}
  .excluded-table th {{ background: #c0392b; }}
  .footer {{ margin-top: 22px; font-size: 11px; color: #94a3b8; text-align: center; }}
  @media print {{ .no-print {{ display: none; }} }}
</style>
</head>
<body onload="window.print()">
  <div class="header">
    <h1>الإحصائية</h1>
    <div class="sub">وزارة العدل — نظام جلسات الخبراء</div>
  </div>
  <div class="meta">
    <div>الخبير: <b>{esc(expert_name)}</b></div>
    <div>الفترة: <b>{esc(period_disp)}</b></div>
    <div>تاريخ الإصدار: <b>{esc(generated_at)}</b></div>
  </div>

  <h2 class="section">القضايا المحالة ({len(referred)})</h2>
  <table>
    <thead>
      <tr>
        <th style="width:6%">م</th>
        <th style="width:14%">تاريخ الإحالة</th>
        <th style="width:16%">رقم الخبرة</th>
        <th style="width:50%">القضية</th>
        <th style="width:14%">الحالة</th>
      </tr>
    </thead>
    <tbody>{referred_rows()}</tbody>
  </table>
  {referred_note()}

  <h2 class="section">القضايا المنجزة ({len(completed)})</h2>
  <table>
    <thead>
      <tr>
        <th style="width:6%">م</th>
        <th style="width:16%">تاريخ الإنجاز</th>
        <th style="width:18%">رقم الخبرة</th>
        <th style="width:60%">القضية</th>
      </tr>
    </thead>
    <tbody>{completed_rows()}</tbody>
  </table>

  <h2 class="section excluded">القضايا المستبعدة — أُعيد توزيعها ({len(excluded)})</h2>
  <table class="excluded-table">
    <thead>
      <tr>
        <th style="width:14%">رقم الخبرة</th>
        <th style="width:32%">المدعي</th>
        <th style="width:32%">المدعى عليه</th>
        <th style="width:16%">تاريخ آخر إحالة لك</th>
      </tr>
    </thead>
    <tbody>{excluded_rows()}</tbody>
  </table>

  <div class="footer">
    ⚠️ "القضايا المستبعدة" هي قضايا انوزعت عليك ثم أُعيد توزيعها لخبير
    آخر قبل إنجازك لها — لا تُحتسب ضمن المحالة أو المنجزة.
  </div>
</body>
</html>"""

    out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "الإحصائية")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"الاحصائية_{date_from.strftime('%Y-%m-%d')}_الى_{date_to.strftime('%Y-%m-%d')}.html"
    path = os.path.join(out_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    return path
