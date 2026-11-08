# ===== progress_widget.py — نافذة تقدم استخراج بيانات القضية (تصميم داكن) =====
"""
نافذة CTkToplevel داكنة تعرض مراحل ExtractionTask الخمس بشكل حي:
  ✓ أخضر = خلصت · سبينر أصفر دوّار = جارية · دائرة فارغة = بالانتظار
  ✕ أحمر = خطأ · — رمادي = تم تخطيها (مثلاً ما فيه حكم إحالة بالنظام)

فوقها شخصية متحركة بسيطة مرسومة بـCanvas (ورقة حكم + عدسة مكبّرة
تتحرك عليها + خط مسح + نقاط تدور) — بدون أي مكتبة إضافية. حلقة
after() وحدة (كل FRAME_MS) تحرّك الشخصية والسبينرات مع بعض.

النافذة "عرض" فقط للمهمة: إغلاقها/تصغيرها ما يأثر على الـthread.
"""
import math
import tkinter as tk
import customtkinter as ctk

from extraction_tasks import STAGES, PENDING, IN_PROGRESS, DONE, ERROR, SKIPPED

FONT = "Arial"
FRAME_MS = 60

BG_WIN   = "#0f1117"
BG_CARD  = "#171a23"
BORDER   = "#262b38"
TXT_MAIN = "#f1f3f8"
TXT_SUB  = "#8b93a7"
TXT_DIM  = "#596075"
GREEN    = "#3ddc84"
YELLOW   = "#f5c542"
RED      = "#ff5c5c"
CIRCLE   = "#3a4050"
PAPER    = "#e9edf5"
PAPER_LN = "#b8c0d0"
LENS     = "#7cc4ff"

ICON = 24


def F(s, b=False):
    return (FONT, s, "bold") if b else (FONT, s)


class ExtractionProgressWindow(ctk.CTkToplevel):
    def __init__(self, parent, task, allow_minimize=True, auto_close_ms=700):
        super().__init__(parent)
        self.task = task
        self.allow_minimize = allow_minimize
        self.auto_close_ms = auto_close_ms
        self._tick = 0
        self._alive = True
        self._closing = False

        self.title(f"استخراج بيانات القضية — {task.caso_no}")
        self.configure(fg_color=BG_WIN)
        self.resizable(False, False)
        W, H = 440, 520
        try:
            self.transient(parent.winfo_toplevel())
            parent.update_idletasks()
            top = parent.winfo_toplevel()
            px = top.winfo_rootx() + max(0, (top.winfo_width() - W) // 2)
            py = top.winfo_rooty() + max(0, (top.winfo_height() - H) // 2)
            self.geometry(f"{W}x{H}+{px}+{py}")
        except Exception:
            self.geometry(f"{W}x{H}")

        # grab: نحفظ صاحب الـgrab السابق (مثلاً شاشة معلومات القضية) ونرجعه له عند الإغلاق
        self._prev_grab = None
        try:
            self._prev_grab = self.grab_current()
        except Exception:
            pass
        self.after(50, self._safe_grab)

        self.protocol("WM_DELETE_WINDOW",
                      self.minimize if allow_minimize else self.cancel)

        self._build()

        task.window = self
        task.minimized = False
        task.on_stage.append(self._on_stage)
        task.listeners.append(self._on_finished)
        self._refresh_all()
        self._animate()

    # ------------------------------------------------------------ بناء
    def _build(self):
        card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=16,
                            border_width=1, border_color=BORDER)
        card.pack(fill="both", expand=True, padx=14, pady=14)

        self.anim = tk.Canvas(card, width=150, height=120, bg=BG_CARD,
                              highlightthickness=0, bd=0)
        self.anim.pack(pady=(18, 4))

        ctk.CTkLabel(card, text="جاري استخراج بيانات القضية",
                     font=F(17, True), text_color=TXT_MAIN).pack()
        ctk.CTkLabel(card, text=self.task.caso_no, font=F(12),
                     text_color=TXT_SUB).pack(pady=(2, 14))

        steps = ctk.CTkFrame(card, fg_color="transparent")
        steps.pack(fill="x", padx=26)
        self.rows = []
        for name in STAGES:
            row = ctk.CTkFrame(steps, fg_color="transparent", height=36)
            row.pack(fill="x", pady=3)
            icon = tk.Canvas(row, width=ICON, height=ICON, bg=BG_CARD,
                             highlightthickness=0, bd=0)
            icon.pack(side="right")
            lbl = ctk.CTkLabel(row, text=name, font=F(13), text_color=TXT_DIM,
                               anchor="e", justify="right")
            lbl.pack(side="right", padx=(0, 12), fill="x", expand=True)
            self.rows.append((icon, lbl))

        self.note_lbl = ctk.CTkLabel(card, text="", font=F(11), text_color=TXT_SUB,
                                     wraplength=360, justify="right")
        self.note_lbl.pack(pady=(10, 0), padx=20, anchor="e")

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=22, pady=(0, 18))
        self.cancel_btn = ctk.CTkButton(
            btns, text="إلغاء", font=F(13, True), height=38, corner_radius=10,
            fg_color="#2a2f3d", hover_color="#3a2027", text_color=RED,
            command=self.cancel)
        self.cancel_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
        if self.allow_minimize:
            ctk.CTkButton(
                btns, text="⤓  تصغير — متابعة بالخلفية", font=F(13, True), height=38,
                corner_radius=10, fg_color="#24314a", hover_color="#2d3d5c",
                text_color=LENS, command=self.minimize
            ).pack(side="left", expand=True, fill="x", padx=(6, 0))

    # ------------------------------------------------------------ تحديث المراحل
    def _on_stage(self, task):
        if self._alive:
            self._refresh_all()

    def _refresh_all(self):
        for i, (icon, lbl) in enumerate(self.rows):
            st = self.task.stages[i]
            color = {DONE: TXT_MAIN, IN_PROGRESS: YELLOW, ERROR: RED,
                     SKIPPED: TXT_DIM}.get(st, TXT_DIM)
            lbl.configure(text_color=color, font=F(13, st == IN_PROGRESS))
            if st != IN_PROGRESS:
                self._draw_icon(icon, st)
        notes = [n for n in self.task.notes if n]
        self.note_lbl.configure(text=notes[-1] if notes else "")

    def _draw_icon(self, c, state, angle=0):
        c.delete("all")
        p, s = 2, ICON - 2
        if state == DONE:
            c.create_oval(p, p, s, s, fill=GREEN, outline=GREEN)
            c.create_line(7, 12.5, 10.5, 16, 17, 8.5, fill=BG_CARD, width=2.6,
                          capstyle="round", joinstyle="round")
        elif state == ERROR:
            c.create_oval(p, p, s, s, fill=RED, outline=RED)
            c.create_line(8, 8, 16, 16, fill=BG_CARD, width=2.4, capstyle="round")
            c.create_line(16, 8, 8, 16, fill=BG_CARD, width=2.4, capstyle="round")
        elif state == SKIPPED:
            c.create_oval(p, p, s, s, outline=CIRCLE, width=2)
            c.create_line(8, 12, 16, 12, fill=TXT_DIM, width=2, capstyle="round")
        elif state == IN_PROGRESS:
            c.create_oval(p + 1, p + 1, s - 1, s - 1, outline="#3b3420", width=3)
            c.create_arc(p + 1, p + 1, s - 1, s - 1, start=-angle, extent=100,
                         style="arc", outline=YELLOW, width=3)
        else:
            c.create_oval(p + 1, p + 1, s - 1, s - 1, outline=CIRCLE, width=2)

    # ------------------------------------------------------------ الحركة
    def _animate(self):
        if not self._alive:
            return
        self._tick += 1
        t = self._tick
        for i, (icon, _) in enumerate(self.rows):
            if self.task.stages[i] == IN_PROGRESS:
                self._draw_icon(icon, IN_PROGRESS, angle=(t * 18) % 360)
        self._draw_character(t)
        self.after(FRAME_MS, self._animate)

    def _draw_character(self, t):
        c = self.anim
        c.delete("all")
        cx, cy = 75, 62
        # هالة نابضة
        r = 50 + 3 * math.sin(t / 6)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#1f2a3d", width=2)
        # نقاط تدور حول الورقة
        for k in range(3):
            a = t / 9 + k * 2 * math.pi / 3
            x, y = cx + 50 * math.cos(a), cy + 50 * math.sin(a)
            c.create_oval(x - 3, y - 3, x + 3, y + 3,
                          fill=(YELLOW, LENS, GREEN)[k], outline="")
        # ورقة الحكم
        x0, y0, x1, y1 = cx - 26, cy - 34, cx + 26, cy + 34
        c.create_rectangle(x0, y0, x1, y1, fill=PAPER, outline="")
        c.create_polygon(x1 - 12, y0, x1, y0 + 12, x1 - 12, y0 + 12, fill=PAPER_LN)
        for k in range(6):
            ly = y0 + 16 + k * 8
            c.create_line(x0 + 8, ly, x1 - 8 - (12 if k % 3 == 2 else 0), ly,
                          fill=PAPER_LN, width=2)
        # خط مسح ينزل ويطلع
        sy = y0 + 4 + (y1 - y0 - 8) * (0.5 + 0.5 * math.sin(t / 8))
        c.create_line(x0 - 4, sy, x1 + 4, sy, fill=GREEN, width=2)
        # عدسة مكبّرة تتحرك بشكل ∞
        mx = cx + 16 * math.sin(t / 11)
        my = cy + 10 * math.sin(t / 5.5)
        c.create_line(mx + 9, my + 9, mx + 19, my + 19, fill="#c9d3e6", width=5,
                      capstyle="round")
        c.create_oval(mx - 12, my - 12, mx + 12, my + 12, outline=LENS, width=3)

    # ------------------------------------------------------------ أزرار/إغلاق
    def _safe_grab(self):
        try:
            if self._alive:
                self.grab_set()
                self.lift()
                self.focus_force()
        except Exception:
            pass

    def cancel(self):
        self.task.cancel()
        self._close()

    def minimize(self):
        """يقفل النافذة بس — الـthread يكمل، والـToast يطلع أول ما يخلص"""
        self.task.minimized = True
        self._close()

    def _on_finished(self, task):
        if not self._alive:
            return
        self.cancel_btn.configure(state="disabled")
        self.after(self.auto_close_ms, self._close)

    def _close(self):
        if self._closing:
            return
        self._closing = True
        self._alive = False
        try:
            self.task.on_stage.remove(self._on_stage)
        except ValueError:
            pass
        try:
            self.task.listeners.remove(self._on_finished)
        except ValueError:
            pass
        if self.task.window is self:
            self.task.window = None
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        prev = self._prev_grab
        if prev is not None:
            try:
                if prev.winfo_exists():
                    prev.grab_set()
            except Exception:
                pass
