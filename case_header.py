# ===== case_header.py — بيانات رأس القضية (الجدول الأول) بمصدر واحد للمحضر والتقرير =====
# المحضر يجمعها في qt_sessions_page ← هنا نفس المنطق حرفياً حتى لا يختلف التقرير عنه:
#   الأطراف ورقم الدعوى: بيانات القضية المحفوظة (case_db، مستخرجة من حكم الإحالة) ثم نظام الخبراء (parse_case_info).
#   الخبراء: get_experts (سجل الحركة) بترتيب المحضر نفسه. لا يُؤخذ اسم المستخدم الداخل بدلاً من الخبراء.
import case_db


def ordered_expert_names(exps):
    """أسماء الخبراء بترتيب المحضر: فرد ← اسمه؛ لجنة ثلاثية برئيس ← عضو، رئيس، عضو؛ غير ذلك بترتيب السجل."""
    if not exps:
        return []
    chairs = [x for x in exps if x['role'] == 'رئيس لجنة']
    members = [x for x in exps if x['role'] != 'رئيس لجنة']
    if len(exps) == 1:
        return [exps[0]['name']]
    if len(exps) >= 3 and chairs:
        names = [members[0]['name'], chairs[0]['name']]
        if len(members) > 1:
            names.append(members[1]['name'])
        return names
    return [x['name'] for x in exps]


def fetch_header(cookies, current_user, caso_no, case_data=None):
    """dict: info، names (الخبراء)، es (نص المحضر)، plaintiffs، defendants، court_case_number.
    بلا اتصال (cookies فارغة) تُستخدم بيانات case_db فقط. لا يرفع استثناءً."""
    from ui import get_experts, clean_spaces
    info, exps = {}, []
    if cookies:
        try:
            from api import parse_case_info
            info = parse_case_info(caso_no, cookies, current_user) or {}
        except Exception:
            info = {}
        try:
            exps = get_experts(caso_no, cookies, current_user)
        except Exception:
            exps = []
    if case_data is None:
        try:
            case_data = case_db.get_case(caso_no) or {}
        except Exception:
            case_data = {}
    names = ordered_expert_names(exps)
    es = '  ،  '.join(names) if names else current_user
    plaintiffs = case_data.get('plaintiffs') or info.get('plaintiffs', [])
    defendants = case_data.get('defendants') or info.get('defendants', [])
    return {
        'info': info, 'names': names, 'es': es,
        'plaintiffs': [clean_spaces(p) for p in plaintiffs],
        'defendants': [clean_spaces(d) for d in defendants],
        'court_case_number': case_data.get('court_case_number') or info.get('case_num', ''),
    }
