# ===== app_paths.py — مجلد السجلات وملفات الحالة (2026-10-25) =====
# السجلات (gemini_connection.log، ai_calls.log، claim_summary.log) وملفات الحالة (عدّاد الحصص، طابور الملخصات، قائمة
# النماذج وما يتيحه المفتاح) في %LOCALAPPDATA%\ExpertApp — أو في المجلد الذي يحدده متغير البيئة EXPERTAPP_LOG_DIR.
# الاختبارات (python -m unittest / test_*.py) تعمل على مجلد مؤقت تلقائياً عبر المتغير نفسه، فلا تظهر مدخلات اختبارية
# (مثل MyProv) في السجلات الحقيقية ولا تُستهلك عدّادات المفتاح الحقيقي.
import os
import sys
import tempfile

ENV = 'EXPERTAPP_LOG_DIR'


def under_tests():
    argv0 = os.path.basename(str((sys.argv or [''])[0])).lower()
    return 'unittest' in argv0 or argv0.startswith('test_') or 'pytest' in argv0 or 'unittest' in ' '.join(
        sys.argv[:1]).lower()


def data_dir():
    d = os.environ.get(ENV)
    if not d and under_tests():
        d = tempfile.mkdtemp(prefix='expertapp_test_logs_')
        os.environ[ENV] = d
    return d or os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'ExpertApp')


def path(name):
    return os.path.join(data_dir(), name)
