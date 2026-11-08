# ===== report_pipeline.py — منفّذ مراحل تقرير الخبرة + الاستئناف (المرحلة 2ب) =====
# كل مرحلة دالة مستقلة run(ctx) -> رسالة نجاح اختيارية. فشل مرحلة يُسجَّل في case.json
# برسالة واضحة ولا يوقف المراحل التالية، إلا المراحل التي تعتمد عليها (تصبح blocked).
# التقدم يُحفظ في case.json بعد كل تغيير حالة؛ عند إعادة التشغيل تُتخطّى المراحل المكتملة،
# والمرحلة التي بقيت running (أُغلق البرنامج أثناءها) تُعاد من أولها.
# مرحلة بلا دالة (run=None) تُسجَّل unavailable «قيد التنفيذ» — هذا وضع المراحل بعد 2ب حالياً.
from dataclasses import dataclass, field
from typing import Callable, Optional

import case_model as cm
import case_workspace as cw


@dataclass
class Stage:
    key: str
    label: str
    run: Optional[Callable] = None
    depends: tuple = field(default_factory=tuple)


STATE_TEXT = dict(cm.STATE_TEXT, unavailable='قيد التنفيذ')


def default_stages():
    """الخطوات السبع. دوالها الفعلية تأتي في 2ح…2م؛ الاعتماد من case_model.DEPENDS."""
    return [Stage(k, cm.STEP_LABELS[k], depends=tuple(cm.DEPENDS.get(k, {}))) for k in cm.STEP_KEYS]


class Pipeline:
    def __init__(self, base, data, stages, on_update=None):
        self.base = base
        self.data = data
        self.stages = stages
        self.on_update = on_update or (lambda key, rec: None)
        self._recover_interrupted()

    def state(self, key):
        return self.data['steps'].get(key, {}).get('state', 'pending')

    def _set(self, key, state, message=''):
        rec = self.data['steps'].setdefault(key, cm.new_step())
        if state == 'running':
            rec['attempts'] = rec.get('attempts', 0) + 1
        rec.update(state=state, message=message, at=cw._now())
        cw.write_case_json(self.base, self.data)
        self.on_update(key, rec)

    def _recover_interrupted(self):
        if cm.recover_interrupted(self.data):
            cw.write_case_json(self.base, self.data)

    def run(self, ctx=None, retry_failed=True):
        """يشغّل المراحل غير المكتملة بالترتيب. يرجع dict {key: state} النهائي."""
        for st in self.stages:
            cur = self.state(st.key)
            if cur in cm.OK_STATES:
                continue
            if cur == 'failed' and not retry_failed:
                continue
            if st.key in cm.DEPENDS:
                reasons = cm.unmet(self.data, st.key)
            else:
                bad = [d for d in st.depends if self.state(d) not in cm.OK_STATES]
                names = '، '.join(s.label for s in self.stages if s.key in bad)
                reasons = [f'تحتاج اكتمال: {names}'] if bad else []
            if reasons:
                self._set(st.key, 'blocked', '؛ '.join(reasons))
                continue
            if st.run is None:
                self._set(st.key, 'unavailable', 'هذه المرحلة لم تُبنَ بعد')
                continue
            self._set(st.key, 'running')
            try:
                msg = st.run(ctx if ctx is not None else self)
                self._set(st.key, 'done', msg or '')
            except Exception as e:
                self._set(st.key, 'failed', str(e) or e.__class__.__name__)
        return {s.key: self.state(s.key) for s in self.stages}
