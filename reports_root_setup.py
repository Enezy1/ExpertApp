# ===== reports_root_setup.py — سؤال أول استخدام عن مكان حفظ تقارير الخبرة (المرحلة 2د) =====
# منطق صرف بلا واجهة: اقتراح الأماكن (المستندات، سطح المكتب، OneDrive) وحفظ الاختيار.
# الواجهة (RootChoiceDialog) في qt_expert_reports.py. الحفظ عبر expert_settings.save_reports_root.
import os

import case_workspace

FOLDER_NAME = 'تقارير الخبراء'


def _onedrive_dirs(env, exists):
    """مجلدات OneDrive (شخصي ثم عمل) من متغيرات البيئة، بلا تكرار، الموجود فعلاً فقط."""
    out, seen = [], set()
    for var, label in (('OneDrive', 'OneDrive'), ('OneDriveCommercial', 'OneDrive (العمل)')):
        p = (env.get(var) or '').strip()
        if p and exists(p) and os.path.normcase(os.path.normpath(p)) not in seen:
            seen.add(os.path.normcase(os.path.normpath(p)))
            out.append((label, p))
    return out


def suggest_roots(env=None, home=None, exists=os.path.isdir):
    """قائمة (التسمية، المسار الكامل للجذر) بترتيب العرض."""
    env = os.environ if env is None else env
    home = home or os.path.expanduser('~')
    out = []
    docs = os.path.join(home, 'Documents')
    desk = os.path.join(home, 'Desktop')
    out.append(('المستندات', os.path.join(docs, FOLDER_NAME)))
    out.append(('سطح المكتب', os.path.join(desk, FOLDER_NAME)))
    for label, p in _onedrive_dirs(env, exists):
        out.append((label, os.path.join(p, FOLDER_NAME)))
    return out


def has_saved_root(load=None):
    if load is None:
        from expert_settings import load_reports_root as load
    try:
        return bool((load() or '').strip())
    except Exception:
        return False


def validate_root(root):
    """يرفع WorkspaceError برسالة عربية إن كان الجذر غير صالح (فارغ أو مساره طويل)."""
    root = (root or '').strip()
    if not root:
        raise case_workspace.WorkspaceError("لم يُختر مجلد.")
    # رقم خبرة نموذجي لقياس الطول
    case_workspace.check_path_lengths(case_workspace.case_dir('0000000000', root))
    return root


def save_choice(root, save=None):
    """يتحقق من الجذر ثم يحفظه (ولا ينشئ مجلداً: ينشأ عند أول قضية)."""
    if save is None:
        from expert_settings import save_reports_root as save
    root = validate_root(root)
    save(root)
    return root
