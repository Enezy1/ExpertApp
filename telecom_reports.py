# ===== telecom_reports.py — قضايا الخبير المتداولة التي مدعيتها شركة اتصالات =====
# منطق بلا واجهة. المدعية تُحدَّد بهذا الترتيب:
#   1) الجزء الذي قبل «ضد» في العنوان  2) case_db (إن كانت محفوظة)  3) api.parse_case_info (بالتتابع).
# 2026-10-25: الجلب مرة واحدة (fetch_all) — كل المتداولة مع تحديد المدعية لكل قضية (العنوان ثم المحفوظ فوراً، ثم
# parse_case_info للغامض واحدة واحدة مع on_case فتظهر القضية فور تحديدها) — والتبديل بين «كل القضايا» و«نزاعات الاتصالات
# فقط» تصفية محلية فورية (filter_cases) بلا أي طلب. لا كاش على القرص: النتيجة في ذاكرة الصفحة للجلسة، وزر «تحديث البيانات»
# يعيد الجلب. لا تاريخ انتهاء على مستوى القضية.
import telecom_config


def _saved_plaintiffs(caso_no):
    try:
        import case_db
        c = case_db.get_case(caso_no)
        return (c or {}).get('plaintiffs') or []
    except Exception:
        return []


def _entry(c, company, plaintiff, defendants, source, resolved):
    return {'caso_no': c['caso_no'], 'autocase_no': c.get('autocase_no', ''), 'title': c.get('title', '') or '',
            'received_date': c.get('received_date', ''), 'company': company or '', 'plaintiff': plaintiff,
            'defendants': defendants, 'source': source, 'resolved': resolved, 'failed': False}


def fetch_all(cookies, companies=None, pending_fn=None, parse_fn=None, saved_fn=None, on_ready=None, on_case=None,
              stop=None, resolve_unclear=True):
    """كل المتداولة مرة واحدة مع تحديد المدعية لكل قضية. يرجع {'all': [قضايا]، 'total'، 'configured'}.
    on_ready(res) بعد المرحلة الأولى (العنوان والمحفوظ — بلا طلبات لكل قضية)؛ ثم on_case(قضية) لكل قضية غامضة تحدّدت
    مدعيتها من النظام (parse_case_info) أو تعذّر تحديدها (failed). resolve_unclear=False ← بلا case_db ولا النظام."""
    if companies is None:
        companies = telecom_config.load_companies()
    if pending_fn is None:
        from pending_cases import get_pending_cases as pending_fn
    if parse_fn is None:
        from api import parse_case_info as parse_fn
    saved_fn = saved_fn or _saved_plaintiffs
    pending = pending_fn(cookies) or []
    res = {'all': [], 'total': len(pending), 'configured': bool(companies)}
    unclear = []
    for c in pending:
        part = telecom_config.split_plaintiff(c.get('title', '') or '')
        company = telecom_config.match_company(part, companies) if part and companies else None
        if part or not companies or not resolve_unclear:
            res['all'].append(_entry(c, company, part, [], 'title', bool(part) or not companies))
            continue
        saved = saved_fn(c['caso_no'])
        hit = next(((p, telecom_config.match_company(p, companies)) for p in saved
                    if telecom_config.match_company(p, companies)), None)
        if hit:
            res['all'].append(_entry(c, hit[1], hit[0], [], 'saved', True))
        elif saved:
            res['all'].append(_entry(c, None, '', [], 'saved', True))     # مدعية محفوظة وليست شركة اتصالات
        else:
            e = _entry(c, None, '', [], 'title', False)
            res['all'].append(e)
            unclear.append(e)
    if on_ready:
        on_ready(res)
    for e in unclear:
        if stop and stop():
            break
        try:
            info = parse_fn(e['caso_no'], cookies)
        except Exception:
            info = None
        if not info or not info.get('plaintiffs'):
            e['failed'] = True
        else:
            e['defendants'] = info.get('defendants') or []
            for p in info['plaintiffs']:
                company = telecom_config.match_company(p, companies)
                if company:
                    e.update(company=company, plaintiff=p, source='system')
                    break
            e['resolved'] = True
        if on_case:
            on_case(dict(e))
    return res


def filter_cases(res, only_telecom=True):
    """تصفية محلية فورية (بلا طلبات) لنتيجة fetch_all: الشكل نفسه القديم {'cases','unresolved','total','configured'}."""
    res = res or {'all': [], 'total': 0, 'configured': False}
    out = {'cases': [], 'unresolved': 0, 'total': res.get('total', 0), 'configured': res.get('configured', False),
           'resolving': 0}
    if only_telecom and not out['configured']:
        return out
    for e in res.get('all') or []:
        if e.get('failed'):
            out['unresolved'] += 1
        elif not e.get('resolved'):
            out['resolving'] += 1
        if only_telecom and not e.get('company'):
            continue
        out['cases'].append({k: e[k] for k in ('caso_no', 'autocase_no', 'title', 'received_date', 'company',
                                               'plaintiff', 'defendants', 'source')})
    out['cases'].sort(key=lambda x: x['received_date'] or '9999')
    return out


def get_my_telecom_cases(cookies, companies=None, pending_fn=None, parse_fn=None, saved_fn=None,
                         only_telecom=True):
    """يرجع dict:
      cases       القضايا (الأقدم استلاماً أولاً)
      unresolved  عدد قضايا تعذّر تحديد مدعيتها (فشل الجلب)
      total       عدد المتداولة المفحوصة
      configured  هل توجد شركات في الإعدادات
    كل قضية: caso_no, autocase_no, title, received_date, company ('' إن لم تكن شركة),
    plaintiff, defendants, source.
    only_telecom=True: الفرز على المدعية فقط (الجزء قبل «ضد»؛ وإن لم يتضح الفصل فمن
    case_db ثم parse_case_info). False: كل المتداولة بلا جلب إضافي.
    (pending_fn/parse_fn/saved_fn قابلة للاستبدال للاختبار.) — fetch_all ثم filter_cases."""
    if companies is None:
        companies = telecom_config.load_companies()
    if only_telecom and not companies:
        return {'cases': [], 'unresolved': 0, 'total': 0, 'configured': False}
    res = fetch_all(cookies, companies, pending_fn, parse_fn, saved_fn, resolve_unclear=only_telecom)
    out = filter_cases(res, only_telecom)
    out.pop('resolving', None)
    return out