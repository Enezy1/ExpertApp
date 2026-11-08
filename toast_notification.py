# ===== toast_notification.py — إشعار صغير يطلع من زاوية الشاشة ويختفي تلقائيًا =====
import tkinter as tk
import customtkinter as ctk

FONT = "Arial"

BG     = "#171a23"
BORDER = "#262b38"
TXT    = "#f1f3f8"
SUB    = "#8b93a7"
KIND_COLORS = {"success": "#3ddc84", "warning": "#f5c542", "error": "#ff5c5c"}

MARGIN = 18
GAP = 10
_active = []   # التوستات الظاهرة حاليًا — عشان تتكدس فوق بعض بدل ما تتراكب


def _work_area(widget):
    """منطقة العمل الفعلية (بدون شريط المهام) بالبكسل الحقيقي. على ويندوز
    winfo_screenwidth يرجع قيمة مقسومة على تكبير الشاشة (مثلاً 1707 بدل
    2560 عند 150%) بينما geometry() يتعامل بالبكسل الفعلي — فنسأل ويندوز مباشرة."""
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        return rect.right, rect.bottom
    except Exception:
        return widget.winfo_screenwidth(), widget.winfo_screenheight() - 48


def F(s, b=False):
    return (FONT, s, "bold") if b else (FONT, s)


class Toast(tk.Toplevel):
    # tk.Toplevel عمدًا (مو CTkToplevel): CTk يعيد تحجيم geometry بمعامل DPI
    # بشكل غير ثابت للنوافذ بدون إطار، فالأبعاد هنا بالبكسل الفعلي مباشرة
    def __init__(self, parent, title, message, kind="success",
                 action_text=None, action=None, duration_ms=6000):
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(bg=BORDER)
        try:
            self.attributes("-topmost", True)
            self.attributes("-alpha", 0.0)
        except Exception:
            pass
        accent = KIND_COLORS.get(kind, KIND_COLORS["success"])
        self._alpha = 0.0
        self._closing = False
        self._hover = False
        self._remaining = duration_ms

        inner = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        ctk.CTkFrame(inner, fg_color=accent, width=4, height=1, corner_radius=0).pack(side="right", fill="y")

        body = ctk.CTkFrame(inner, fg_color="transparent")
        body.pack(side="right", fill="both", expand=True, padx=14, pady=12)

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text=title, font=F(13, True), text_color=TXT,
                     anchor="e").pack(side="right")
        ctk.CTkButton(head, text="✕", width=22, height=22, fg_color="transparent",
                      hover_color=BORDER, text_color=SUB, font=F(11),
                      command=self.close).pack(side="left")

        ctk.CTkLabel(body, text=message, font=F(12), text_color=SUB, anchor="e",
                     justify="right", wraplength=300).pack(fill="x", pady=(4, 0))

        if action_text and action:
            def _do():
                self.close()
                action()
            ctk.CTkButton(body, text=action_text, font=F(12, True), height=30,
                          corner_radius=8, fg_color=accent, hover_color=accent,
                          text_color=BG, command=_do).pack(anchor="w", pady=(10, 0))

        self.bind("<Enter>", lambda e: setattr(self, "_hover", True))
        self.bind("<Leave>", lambda e: setattr(self, "_hover", False))

        self.update_idletasks()
        self._tw = self.winfo_reqwidth()
        self._th = self.winfo_reqheight()
        _active.append(self)
        self._place()
        self._fade_in()
        self.after(100, self._countdown)

    def _place(self):
        sw, sh = _work_area(self)
        y = sh - MARGIN  # فوق شريط المهام
        for t in _active:
            y -= t._th
            if t is self:
                break
            y -= GAP
        self.geometry(f"{self._tw}x{self._th}+{sw - self._tw - MARGIN}+{y}")

    def _fade_in(self):
        if self._closing:
            return
        self._alpha = min(0.97, self._alpha + 0.12)
        try:
            self.attributes("-alpha", self._alpha)
        except Exception:
            return
        if self._alpha < 0.97:
            self.after(25, self._fade_in)

    def _countdown(self):
        if self._closing:
            return
        if not self._hover:
            self._remaining -= 100
        if self._remaining <= 0:
            self.close()
        else:
            self.after(100, self._countdown)

    def close(self):
        if self._closing:
            return
        self._closing = True
        self._fade_out()

    def _fade_out(self):
        self._alpha -= 0.15
        if self._alpha > 0:
            try:
                self.attributes("-alpha", self._alpha)
                self.after(25, self._fade_out)
                return
            except Exception:
                pass
        if self in _active:
            _active.remove(self)
        try:
            self.destroy()
        except Exception:
            pass
        for t in _active:
            try:
                t._place()
            except Exception:
                pass


def show_toast(parent, title, message, kind="success", action_text=None,
               action=None, duration_ms=6000):
    return Toast(parent, title, message, kind, action_text, action, duration_ms)
