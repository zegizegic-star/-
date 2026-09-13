import os
import sys
import shutil
import subprocess
import threading
import calendar
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
from datetime import date, datetime
import csv

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from PIL import Image, ImageDraw, ImageFilter, ImageTk

from database import Database
import receipts
import authlock
import update_check
import bank_import

try:
    import openpyxl
    from openpyxl.styles import Font as XLFont

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

# ---------------- палитра ----------------
BG = "#0B0D12"
SURFACE = "#151822"
SURFACE2 = "#1C202B"
LINE = "#242835"
INK = "#F3F4F7"
INK_DIM = "#8A90A3"
INK_FAINT = "#565D6E"
ACCENT = "#6C8CFF"
ACCENT_SOFT = "#1B2036"
INCOME = "#34D399"
EXPENSE = "#FF6B6B"
GOLD = "#F2B84B"
DANGER = EXPENSE

PALETTE = ["#8AA2E8", "#F2B84B", "#7FC4C0", "#E8899A", "#BD6357",
           "#8AA9A5", "#D8C468", "#B992C9", "#7FA3C0", "#A78BFA"]

FONT_UI = "Segoe UI"
FONT_MONO = "Consolas"

MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
             "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_SHORT = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
                 "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]

APP_VERSION = update_check.APP_VERSION


def resource_path(filename):
    """Путь к вложенному файлу (например, иконке) — как при запуске из исходников,
    так и из собранного PyInstaller-ом .exe (в том числе из папки с кириллицей в пути)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


def fmt_money(n):
    sign = "-" if n < 0 else ""
    return f"{sign}{abs(n):,.0f}".replace(",", " ") + " ₽"


def month_key(d: date):
    return f"{d.year}-{d.month:02d}"


def shift_month(key, delta):
    y, m = map(int, key.split("-"))
    m += delta
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return f"{y}-{m:02d}"


def month_label(key):
    y, m = map(int, key.split("-"))
    return f"{MONTHS_RU[m - 1]} {y}"


def _rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """Рисует на canvas прямоугольник со скруглёнными углами радиуса r."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kwargs)


def _lighten(hex_color, amount=22):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (min(255, c + amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend(hex_a, hex_b, t):
    """Смешивает два цвета: t=0 — чистый hex_a, t=1 — чистый hex_b."""
    a, b = hex_a.lstrip("#"), hex_b.lstrip("#")
    ar, ag, ab = (int(a[i:i + 2], 16) for i in (0, 2, 4))
    br, bg_, bb = (int(b[i:i + 2], 16) for i in (0, 2, 4))
    r, g, bl = (round(x + (y - x) * t) for x, y in ((ar, br), (ag, bg_), (ab, bb)))
    return f"#{r:02x}{g:02x}{bl:02x}"


def _widget_bg(widget, default=BG):
    """Пытается узнать фон родителя, чтобы скруглённый виджет слился с ним по углам."""
    try:
        return widget.cget("bg")
    except tk.TclError:
        return default


def icon_badge(parent, icon, color, size=40, radius=12, parent_bg=None):
    """Цветная скруглённая плашка с эмодзи-иконкой (для карточек-метрик)."""
    parent_bg = parent_bg if parent_bg is not None else _widget_bg(parent)
    tint = _blend(SURFACE2, color, 0.35)
    c = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bg=parent_bg, bd=0)
    _rounded_rect(c, 0, 0, size, size, radius, fill=tint, outline="")
    c.create_text(size / 2, size / 2, text=icon, font=(FONT_UI, int(size * 0.42)))
    return c


def make_bar(parent, value, maximum, color, width=220, height=8):
    """Небольшая цветная полоса прогресса со скруглёнными краями, нарисованная на Canvas."""
    bg = parent.cget("bg") if "bg" in parent.keys() else SURFACE
    c = tk.Canvas(parent, width=width, height=height, bg=bg, highlightthickness=0)
    pct = 0 if maximum <= 0 else min(1.0, value / maximum)
    over = maximum > 0 and value > maximum
    fill = DANGER if over else color
    r = height / 2
    _rounded_rect(c, 0, 0, width, height, r, fill=SURFACE2, outline="")
    fill_w = max(height, width * pct)
    if pct > 0:
        _rounded_rect(c, 0, 0, fill_w, height, r, fill=fill, outline="")
    return c


def draw_glyph(canvas, kind, color, size=16):
    """Простая монохромная line-иконка, нарисованная на Canvas (без эмодзи и внешних файлов)."""
    canvas.delete("glyph")
    s = size
    o = {"fill": "", "outline": color, "width": max(1, round(s * 0.11)), "tags": "glyph"}
    lo = {"fill": color, "outline": "", "tags": "glyph"}
    ln = {"fill": color, "width": max(1, round(s * 0.11)), "tags": "glyph", "capstyle": "round"}
    if kind == "dashboard":
        for x, y in ((0.06, 0.06), (0.56, 0.06), (0.06, 0.56), (0.56, 0.56)):
            canvas.create_rectangle(s * x, s * y, s * (x + 0.38), s * (y + 0.38), **o)
    elif kind == "transactions":
        canvas.create_rectangle(s * 0.08, s * 0.2, s * 0.92, s * 0.8, **o)
        canvas.create_line(s * 0.2, s * 0.42, s * 0.8, s * 0.42, **ln)
        canvas.create_line(s * 0.2, s * 0.6, s * 0.5, s * 0.6, **ln)
    elif kind == "accounts":
        canvas.create_rectangle(s * 0.08, s * 0.22, s * 0.92, s * 0.78, **o)
        canvas.create_rectangle(s * 0.08, s * 0.34, s * 0.92, s * 0.46, **lo)
    elif kind == "categories":
        for i, w in enumerate((0.8, 0.6, 0.68)):
            y = s * (0.22 + i * 0.28)
            canvas.create_line(s * 0.1, y, s * (0.1 + w), y, **ln)
    elif kind == "savings":
        canvas.create_oval(s * 0.12, s * 0.3, s * 0.88, s * 0.9, **o)
        canvas.create_line(s * 0.5, s * 0.06, s * 0.5, s * 0.26, **ln)
        canvas.create_oval(s * 0.4, s * 0.02, s * 0.6, s * 0.14, **lo)
    elif kind == "recurring":
        canvas.create_arc(s * 0.12, s * 0.12, s * 0.88, s * 0.88, start=20, extent=280,
                           style="arc", outline=color, width=o["width"], tags="glyph")
        canvas.create_polygon(s * 0.86, s * 0.1, s * 0.98, s * 0.28, s * 0.74, s * 0.3,
                               fill=color, outline="", tags="glyph")
    elif kind == "receipts":
        canvas.create_polygon(s * 0.16, s * 0.06, s * 0.84, s * 0.06, s * 0.84, s * 0.94,
                               s * 0.68, s * 0.82, s * 0.5, s * 0.94, s * 0.32, s * 0.82,
                               s * 0.16, s * 0.94, **o)
        for y in (0.32, 0.48, 0.62):
            canvas.create_line(s * 0.3, s * y, s * 0.7, s * y, **ln)
    elif kind == "yearreport":
        canvas.create_rectangle(s * 0.1, s * 0.16, s * 0.9, s * 0.9, **o)
        canvas.create_line(s * 0.1, s * 0.36, s * 0.9, s * 0.36, **ln)
        canvas.create_line(s * 0.32, s * 0.04, s * 0.32, s * 0.2, **ln)
        canvas.create_line(s * 0.68, s * 0.04, s * 0.68, s * 0.2, **ln)
    elif kind == "income":
        canvas.create_line(s * 0.5, s * 0.85, s * 0.5, s * 0.15, **ln)
        canvas.create_line(s * 0.25, s * 0.42, s * 0.5, s * 0.15, **ln)
        canvas.create_line(s * 0.75, s * 0.42, s * 0.5, s * 0.15, **ln)
    elif kind == "expense":
        canvas.create_line(s * 0.5, s * 0.15, s * 0.5, s * 0.85, **ln)
        canvas.create_line(s * 0.25, s * 0.58, s * 0.5, s * 0.85, **ln)
        canvas.create_line(s * 0.75, s * 0.58, s * 0.5, s * 0.85, **ln)
    elif kind == "balance":
        canvas.create_line(s * 0.5, s * 0.08, s * 0.5, s * 0.86, **ln)
        canvas.create_line(s * 0.18, s * 0.28, s * 0.82, s * 0.28, **ln)
        canvas.create_oval(s * 0.06, s * 0.28, s * 0.34, s * 0.42, **o)
        canvas.create_oval(s * 0.66, s * 0.28, s * 0.94, s * 0.42, **o)
        canvas.create_line(s * 0.22, s * 0.86, s * 0.78, s * 0.86, **ln)
    elif kind == "lock":
        canvas.create_rectangle(s * 0.22, s * 0.46, s * 0.78, s * 0.9, **o)
        canvas.create_arc(s * 0.3, s * 0.1, s * 0.7, s * 0.56, start=0, extent=180,
                           style="arc", outline=color, width=o["width"], tags="glyph")
    elif kind == "forecast":
        canvas.create_line(s * 0.1, s * 0.75, s * 0.38, s * 0.42, s * 0.58, s * 0.6, s * 0.9, s * 0.2,
                            smooth=True, **ln)
    return canvas


def make_icon_canvas(parent, kind, color, size=18, parent_bg=None):
    parent_bg = parent_bg if parent_bg is not None else _widget_bg(parent)
    c = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bg=parent_bg, bd=0)
    draw_glyph(c, kind, color, size)
    return c


_shadow_cache = {}


def _shadow_image(w, h, radius, blur=7, alpha=90, pad=None):
    """Готовит (с кэшем по размеру) мягкую размытую тень через PIL — Canvas сам этого не умеет."""
    key = (w, h, radius, blur, alpha)
    cached = _shadow_cache.get(key)
    if cached is not None:
        return cached
    pad = pad if pad is not None else blur * 2
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([pad, pad, pad + w, pad + h], radius=radius, fill=(0, 0, 0, alpha))
    img = img.filter(ImageFilter.GaussianBlur(blur))
    if len(_shadow_cache) > 200:
        _shadow_cache.clear()
    result = (img, pad)
    _shadow_cache[key] = result
    return result


class RoundedCard(tk.Frame):
    """Карточка со скруглёнными углами и мягкой тенью. Дочерние виджеты кладите в card.body."""

    def __init__(self, parent, bg=SURFACE, border=LINE, radius=16, pad=14, corner_bg=None,
                 shadow=True, **kwargs):
        corner_bg = corner_bg if corner_bg is not None else _widget_bg(parent)
        super().__init__(parent, bg=corner_bg, highlightthickness=0, **kwargs)
        self._fill = bg
        self._outline = border
        self._radius = radius
        self._shadow = shadow
        self._shadow_photo = None
        self._canvas = tk.Canvas(self, highlightthickness=0, bg=corner_bg, bd=0)
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)
        self._canvas.bind("<Configure>", self._redraw)

    def _redraw(self, event=None):
        c = self._canvas
        c.delete("card")
        c.delete("shadow")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 4 or h < 4:
            return
        if self._shadow:
            img, pad = _shadow_image(max(1, w - 2), max(1, h - 2), self._radius)
            self._shadow_photo = ImageTk.PhotoImage(img)
            c.create_image(1 - pad, 3 - pad, image=self._shadow_photo, anchor="nw", tags="shadow")
        _rounded_rect(c, 1, 1, w - 1, h - 1, self._radius, fill=self._fill, outline=self._outline,
                       width=1, tags="card")


class RoundedButton(tk.Canvas):
    """Кнопка со скруглёнными углами и hover-эффектом, нарисованная на Canvas."""

    _KINDS = {
        # kind: (fill, fg, hover_fg)
        "primary": (ACCENT, BG, BG),
        "ghost": (SURFACE2, INK_DIM, INK),
        "danger": (DANGER, "white", "white"),
    }

    def __init__(self, parent, text, command=None, kind="primary", width=None, height=32,
                 radius=12, hpad=18, font=None, parent_bg=None):
        bg, fg, hover_fg = self._KINDS.get(kind, self._KINDS["primary"])
        self._bg = bg
        self._hover_bg = _lighten(bg)
        self._disabled_bg = SURFACE2
        self._fg = fg
        self._hover_fg = hover_fg
        self._font = font or (FONT_UI, 10, "bold")
        self._text = text
        self._radius = radius
        self._state = "normal"
        self._hovering = False
        self.command = command
        self._hpad = hpad
        self._auto_width = width is None

        if width is None:
            width = tkfont.Font(font=self._font).measure(text) + hpad * 2

        parent_bg = parent_bg if parent_bg is not None else _widget_bg(parent)
        super().__init__(parent, width=width, height=height, highlightthickness=0, bg=parent_bg, bd=0)
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _draw(self):
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        r = min(self._radius, w // 2, h // 2)
        if self._state == "disabled":
            fill, fg = self._disabled_bg, INK_DIM
        elif self._hovering:
            fill, fg = self._hover_bg, self._hover_fg
        else:
            fill, fg = self._bg, self._fg
        _rounded_rect(self, 0, 0, w, h, r, fill=fill, outline="")
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._font)

    def _on_enter(self, event):
        if self._state != "disabled":
            self._hovering = True
            self._draw()
            self.configure(cursor="hand2")

    def _on_leave(self, event):
        self._hovering = False
        self._draw()

    def _on_click(self, event):
        if self._state != "disabled" and self.command:
            self.command()

    def configure(self, **kwargs):
        redraw = False
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            redraw = True
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            if self._auto_width:
                new_width = tkfont.Font(font=self._font).measure(self._text) + self._hpad * 2
                super().configure(width=new_width)
            redraw = True
        if "command" in kwargs:
            self.command = kwargs.pop("command")
        if kwargs:
            super().configure(**kwargs)
        if redraw:
            self._draw()

    config = configure

    def set_kind(self, kind):
        """Меняет цветовую схему кнопки на лету (например, активный/неактивный сегмент)."""
        bg, fg, hover_fg = self._KINDS.get(kind, self._KINDS["primary"])
        self._bg = bg
        self._hover_bg = _lighten(bg)
        self._fg = fg
        self._hover_fg = hover_fg
        self._draw()

    def cget(self, key):
        if key == "state":
            return self._state
        if key == "text":
            return self._text
        return super().cget(key)

    __getitem__ = cget


def rbtn(parent, text, command=None, kind="primary", **kwargs):
    """Короткий помощник для создания RoundedButton с автоопределением фона родителя."""
    return RoundedButton(parent, text, command=command, kind=kind, **kwargs)


def icon_button(parent, symbol, command=None, kind="ghost", size=28, font=None, **kwargs):
    """Круглая кнопка-иконка (для ✎, 🗑, ◀, ▶ и т.п.)."""
    return RoundedButton(parent, symbol, command=command, kind=kind, width=size, height=size,
                          radius=size // 2, hpad=0, font=font or (FONT_UI, 11), **kwargs)


class SegmentToggle(tk.Frame):
    """Переключатель из нескольких скруглённых кнопок (например, Расход/Доход)."""

    def __init__(self, parent, options, variable, command=None, parent_bg=None, orient="horizontal"):
        parent_bg = parent_bg if parent_bg is not None else _widget_bg(parent)
        super().__init__(parent, bg=parent_bg)
        self.variable = variable
        self.command = command
        self._buttons = {}
        side = "left" if orient == "horizontal" else "top"
        pad = {"padx": (0, 6)} if orient == "horizontal" else {"pady": (0, 4)}
        for value, label in options:
            btn = rbtn(self, label, command=lambda v=value: self._select(v), kind="ghost",
                       parent_bg=parent_bg)
            btn.pack(side=side, **pad)
            self._buttons[value] = btn
        self._refresh()

    def _select(self, value):
        self.variable.set(value)
        self._refresh()
        if self.command:
            self.command()

    def _refresh(self):
        current = self.variable.get()
        for value, btn in self._buttons.items():
            btn.set_kind("primary" if value == current else "ghost")


class NavItem(tk.Frame):
    """Пункт бокового меню: иконка + подпись, с подсветкой активного состояния."""

    def __init__(self, parent, icon_kind, text, command):
        super().__init__(parent, bg=BG, cursor="hand2")
        self.command = command
        self._active = False
        self.icon = make_icon_canvas(self, icon_kind, INK_DIM, size=17, parent_bg=BG)
        self.icon.pack(side="left", padx=(12, 10), pady=10)
        self.label = tk.Label(self, text=text, bg=BG, fg=INK_DIM, font=(FONT_UI, 10, "bold"), anchor="w")
        self.label.pack(side="left", fill="x", expand=True, pady=10, padx=(0, 10))
        self._icon_kind = icon_kind
        for w in (self, self.icon, self.label):
            w.bind("<Button-1>", lambda e: self.command())
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    def _on_enter(self, e):
        if not self._active:
            self._set_bg(SURFACE2)

    def _on_leave(self, e):
        if not self._active:
            self._set_bg(BG)

    def _set_bg(self, color):
        self.configure(bg=color)
        self.icon.configure(bg=color)
        self.label.configure(bg=color)

    def set_active(self, active):
        self._active = active
        if active:
            self._set_bg(ACCENT_SOFT)
            self.label.configure(fg=INK)
            draw_glyph(self.icon, self._icon_kind, ACCENT)
        else:
            self._set_bg(BG)
            self.label.configure(fg=INK_DIM)
            draw_glyph(self.icon, self._icon_kind, INK_DIM)


# =================================================================
# Диалоги
# =================================================================

class CategoryDialog(tk.Toplevel):
    def __init__(self, master, app, category=None, fixed_type=None):
        super().__init__(master)
        self.app = app
        self.category = category
        self.result = False
        self.title("Категория")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        pad = {"padx": 14, "pady": 6}
        ttk.Label(self, text="Название", style="Card.TLabel").pack(anchor="w", **pad)
        self.name_var = tk.StringVar(value=category["name"] if category else "")
        ttk.Entry(self, textvariable=self.name_var, width=30).pack(padx=14)

        self.type_var = tk.StringVar(value=(category["type"] if category else (fixed_type or "expense")))
        if not category and not fixed_type:
            row = tk.Frame(self, bg=SURFACE)
            row.pack(**pad)
            ttk.Radiobutton(row, text="Расход", variable=self.type_var, value="expense").pack(side="left", padx=4)
            ttk.Radiobutton(row, text="Доход", variable=self.type_var, value="income").pack(side="left", padx=4)

        self.limit_var = tk.StringVar(value=str(int(category["limit_amount"])) if category else "0")
        if self.type_var.get() == "expense":
            ttk.Label(self, text="Лимит в месяц, ₽ (0 — без лимита)", style="Card.TLabel").pack(anchor="w", **pad)
            ttk.Entry(self, textvariable=self.limit_var, width=30).pack(padx=14)

        ttk.Label(self, text="Цвет", style="Card.TLabel").pack(anchor="w", **pad)
        self.color_var = tk.StringVar(value=category["color"] if category else PALETTE[0])
        swatch_row = tk.Frame(self, bg=SURFACE)
        swatch_row.pack(padx=14, pady=4)
        for i, c in enumerate(PALETTE):
            b = tk.Canvas(swatch_row, width=20, height=20, bg=c, highlightthickness=2,
                          highlightbackground=SURFACE)
            b.grid(row=0, column=i, padx=2)
            b.bind("<Button-1>", lambda e, c=c: self.color_var.set(c))

        btn_row = tk.Frame(self, bg=SURFACE)
        btn_row.pack(pady=14)
        rbtn(btn_row, "Сохранить", command=self.save, kind="primary").pack(side="left", padx=6)
        rbtn(btn_row, "Отмена", command=self.destroy, kind="ghost").pack(side="left", padx=6)

    def save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Проверка", "Введите название категории")
            return
        try:
            limit_amount = float(self.limit_var.get() or 0)
        except ValueError:
            limit_amount = 0
        db = self.app.db
        if self.category:
            db.update_category(self.category["id"], name=name, color=self.color_var.get(), limit_amount=limit_amount)
        else:
            db.add_category(name, self.type_var.get(), self.color_var.get(), limit_amount)
        self.result = True
        self.destroy()
        self.app.refresh_all()


class GoalDialog(tk.Toplevel):
    def __init__(self, master, app, goal=None):
        super().__init__(master)
        self.app = app
        self.goal = goal
        self.title("Копилка")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        pad = {"padx": 14, "pady": 6}
        ttk.Label(self, text="Название цели", style="Card.TLabel").pack(anchor="w", **pad)
        self.name_var = tk.StringVar(value=goal["name"] if goal else "")
        ttk.Entry(self, textvariable=self.name_var, width=30).pack(padx=14)

        ttk.Label(self, text="Целевая сумма, ₽", style="Card.TLabel").pack(anchor="w", **pad)
        self.target_var = tk.StringVar(value=str(int(goal["target"])) if goal else "")
        ttk.Entry(self, textvariable=self.target_var, width=30).pack(padx=14)

        ttk.Label(self, text="Дата цели, ГГГГ-ММ-ДД (необязательно)", style="Card.TLabel").pack(anchor="w", **pad)
        self.date_var = tk.StringVar(value=(goal["target_date"] or "") if goal else "")
        ttk.Entry(self, textvariable=self.date_var, width=30).pack(padx=14)

        btn_row = tk.Frame(self, bg=SURFACE)
        btn_row.pack(pady=14)
        rbtn(btn_row, "Сохранить", command=self.save, kind="primary").pack(side="left", padx=6)
        rbtn(btn_row, "Отмена", command=self.destroy, kind="ghost").pack(side="left", padx=6)

    def save(self):
        name = self.name_var.get().strip()
        try:
            target = float(self.target_var.get())
        except ValueError:
            target = 0
        if not name or target <= 0:
            messagebox.showwarning("Проверка", "Укажите название и сумму больше нуля")
            return
        target_date = self.date_var.get().strip() or None
        if target_date:
            try:
                datetime.strptime(target_date, "%Y-%m-%d")
            except ValueError:
                messagebox.showwarning("Проверка", "Дата цели должна быть в формате ГГГГ-ММ-ДД")
                return
        db = self.app.db
        if self.goal:
            db.update_saving(self.goal["id"], name=name, target=target, target_date=target_date,
                              clear_target_date=not target_date)
        else:
            db.add_saving(name, target, target_date=target_date)
        self.destroy()
        self.app.refresh_all()


class ContributeDialog(tk.Toplevel):
    def __init__(self, master, app, goal):
        super().__init__(master)
        self.app = app
        self.goal = goal
        self.title(f"Пополнить «{goal['name']}»")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        ttk.Label(self, text="Сумма пополнения, ₽", style="Card.TLabel").pack(anchor="w", padx=14, pady=(14, 6))
        self.amount_var = tk.StringVar()
        entry = ttk.Entry(self, textvariable=self.amount_var, width=25)
        entry.pack(padx=14)
        entry.focus()

        btn_row = tk.Frame(self, bg=SURFACE)
        btn_row.pack(pady=14)
        rbtn(btn_row, "Пополнить", command=self.save, kind="primary").pack(side="left", padx=6)
        rbtn(btn_row, "Отмена", command=self.destroy, kind="ghost").pack(side="left", padx=6)

    def save(self):
        try:
            amount = float(self.amount_var.get())
        except ValueError:
            amount = 0
        if amount <= 0:
            messagebox.showwarning("Проверка", "Сумма должна быть больше нуля")
            return
        self.app.db.contribute_saving(self.goal["id"], amount, date.today().isoformat())
        self.destroy()
        self.app.refresh_all()


class AccountDialog(tk.Toplevel):
    def __init__(self, master, app, account=None):
        super().__init__(master)
        self.app = app
        self.account = account
        self.title("Счёт")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        pad = {"padx": 14, "pady": 6}
        ttk.Label(self, text="Название счёта", style="Card.TLabel").pack(anchor="w", **pad)
        self.name_var = tk.StringVar(value=account["name"] if account else "")
        ttk.Entry(self, textvariable=self.name_var, width=30).pack(padx=14)

        ttk.Label(self, text="Цвет", style="Card.TLabel").pack(anchor="w", **pad)
        self.color_var = tk.StringVar(value=account["color"] if account else PALETTE[0])
        swatch_row = tk.Frame(self, bg=SURFACE)
        swatch_row.pack(padx=14, pady=4)
        for i, c in enumerate(PALETTE):
            b = tk.Canvas(swatch_row, width=20, height=20, bg=c, highlightthickness=2,
                          highlightbackground=SURFACE)
            b.grid(row=0, column=i, padx=2)
            b.bind("<Button-1>", lambda e, c=c: self.color_var.set(c))

        btn_row = tk.Frame(self, bg=SURFACE)
        btn_row.pack(pady=14)
        rbtn(btn_row, "Сохранить", command=self.save, kind="primary").pack(side="left", padx=6)
        rbtn(btn_row, "Отмена", command=self.destroy, kind="ghost").pack(side="left", padx=6)

    def save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Проверка", "Введите название счёта")
            return
        db = self.app.db
        if self.account:
            db.update_account(self.account["id"], name=name, color=self.color_var.get())
        else:
            db.add_account(name, self.color_var.get())
        self.destroy()
        self.app.refresh_all()


class TransferDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Перевод между счетами")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        accounts = app.db.get_accounts()
        self._acc_map = {a["name"]: a["id"] for a in accounts}
        names = list(self._acc_map.keys())

        pad = {"padx": 14, "pady": 6}
        ttk.Label(self, text="Со счёта", style="Card.TLabel").pack(anchor="w", **pad)
        self.from_var = tk.StringVar(value=names[0] if names else "")
        ttk.Combobox(self, textvariable=self.from_var, values=names, state="readonly", width=28).pack(padx=14)

        ttk.Label(self, text="На счёт", style="Card.TLabel").pack(anchor="w", **pad)
        self.to_var = tk.StringVar(value=names[1] if len(names) > 1 else (names[0] if names else ""))
        ttk.Combobox(self, textvariable=self.to_var, values=names, state="readonly", width=28).pack(padx=14)

        ttk.Label(self, text="Сумма, ₽", style="Card.TLabel").pack(anchor="w", **pad)
        self.amount_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.amount_var, width=30).pack(padx=14)

        ttk.Label(self, text="Дата, ГГГГ-ММ-ДД", style="Card.TLabel").pack(anchor="w", **pad)
        self.date_var = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(self, textvariable=self.date_var, width=30).pack(padx=14)

        ttk.Label(self, text="Заметка", style="Card.TLabel").pack(anchor="w", **pad)
        self.note_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.note_var, width=30).pack(padx=14)

        btn_row = tk.Frame(self, bg=SURFACE)
        btn_row.pack(pady=14)
        rbtn(btn_row, "Перевести", command=self.save, kind="primary").pack(side="left", padx=6)
        rbtn(btn_row, "Отмена", command=self.destroy, kind="ghost").pack(side="left", padx=6)

    def save(self):
        from_id = self._acc_map.get(self.from_var.get())
        to_id = self._acc_map.get(self.to_var.get())
        try:
            amount = float(self.amount_var.get())
        except ValueError:
            amount = 0
        d = self.date_var.get().strip()
        if not from_id or not to_id or amount <= 0 or not d:
            messagebox.showwarning("Проверка", "Заполните оба счёта, сумму больше нуля и дату")
            return
        if from_id == to_id:
            messagebox.showwarning("Проверка", "Счета перевода должны отличаться")
            return
        self.app.db.add_transfer(from_id, to_id, amount, d, self.note_var.get().strip())
        self.destroy()
        self.app.refresh_all()


class SecurityDialog(tk.Toplevel):
    """Настройка PIN-кода запуска приложения."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Защита входа")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        enabled = authlock.is_enabled(app.receipts_base_dir)
        pad = {"padx": 14, "pady": 6}
        ttk.Label(
            self,
            text=("PIN-код нужно будет вводить при каждом запуске программы.\n"
                  "Это не шифрование — если забудете PIN, удалите файл\n"
                  "app_lock.json рядом с программой, чтобы снять защиту."),
            style="Card.TLabel", foreground=INK_DIM, justify="left",
        ).pack(anchor="w", **pad)

        ttk.Label(self, text="Новый PIN (пусто — оставить как есть)", style="Card.TLabel").pack(anchor="w", **pad)
        self.pin_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.pin_var, show="•", width=24).pack(padx=14)

        ttk.Label(self, text="Повторите PIN", style="Card.TLabel").pack(anchor="w", **pad)
        self.pin2_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.pin2_var, show="•", width=24).pack(padx=14)

        btn_row = tk.Frame(self, bg=SURFACE)
        btn_row.pack(pady=14)
        rbtn(btn_row, "Сохранить PIN", command=self.save, kind="primary").pack(side="left", padx=6)
        if enabled:
            rbtn(btn_row, "Убрать защиту", command=self.remove, kind="danger").pack(side="left", padx=6)
        rbtn(btn_row, "Отмена", command=self.destroy, kind="ghost").pack(side="left", padx=6)

    def save(self):
        pin = self.pin_var.get().strip()
        pin2 = self.pin2_var.get().strip()
        if not pin:
            messagebox.showwarning("Проверка", "Введите PIN-код")
            return
        if pin != pin2:
            messagebox.showwarning("Проверка", "PIN-коды не совпадают")
            return
        authlock.set_pin(self.app.receipts_base_dir, pin)
        messagebox.showinfo("Готово", "PIN-код установлен. Он потребуется при следующем запуске.")
        self.destroy()

    def remove(self):
        authlock.remove_pin(self.app.receipts_base_dir)
        messagebox.showinfo("Готово", "Защита входа отключена.")
        self.destroy()


class BankImportDialog(tk.Toplevel):
    """Импорт выписки банка (CSV/Excel) с автоподбором категорий по истории заметок."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Импорт выписки")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.path = None
        self.headers = []
        self.rows = []
        self.parsed = None

        pad = {"padx": 14, "pady": 6}
        ttk.Label(
            self,
            text="Выберите CSV или Excel-файл выписки. Программа попробует сама\n"
                 "найти колонки с датой и суммой; если не получится — выберите их вручную.",
            style="Card.TLabel", foreground=INK_DIM, justify="left",
        ).pack(anchor="w", **pad)

        file_row = tk.Frame(self, bg=SURFACE)
        file_row.pack(fill="x", padx=14, pady=4)
        self.file_label = ttk.Label(file_row, text="Файл не выбран", style="Card.TLabel", foreground=INK_DIM)
        self.file_label.pack(side="left")
        rbtn(file_row, "Выбрать файл…", command=self.pick_file, kind="ghost").pack(side="right")

        self.map_frame = tk.Frame(self, bg=SURFACE)
        self.map_frame.pack(fill="x", padx=14, pady=6)
        self.date_var = tk.StringVar()
        self.amount_var = tk.StringVar()
        self.note_var = tk.StringVar()
        for i, (label, var) in enumerate((("Колонка даты", self.date_var),
                                           ("Колонка суммы", self.amount_var),
                                           ("Колонка описания", self.note_var))):
            ttk.Label(self.map_frame, text=label, style="Card.TLabel").grid(row=0, column=i, sticky="w", padx=4)
            cb = ttk.Combobox(self.map_frame, textvariable=var, state="readonly", width=20)
            cb.grid(row=1, column=i, padx=4)
            setattr(self, f"_combo_{i}", cb)

        opts_row = tk.Frame(self, bg=SURFACE)
        opts_row.pack(fill="x", padx=14, pady=6)
        self.negative_is_expense = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts_row, text="Отрицательные суммы — это расход",
                        variable=self.negative_is_expense).pack(side="left")

        acc_row = tk.Frame(self, bg=SURFACE)
        acc_row.pack(fill="x", padx=14, pady=6)
        ttk.Label(acc_row, text="Зачислить на счёт:", style="Card.TLabel").pack(side="left")
        accounts = app.db.get_accounts()
        self._acc_map = {a["name"]: a["id"] for a in accounts}
        self.account_var = tk.StringVar(value=next(iter(self._acc_map), ""))
        ttk.Combobox(acc_row, textvariable=self.account_var, values=list(self._acc_map.keys()),
                     state="readonly", width=22).pack(side="left", padx=8)

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, style="Card.TLabel", foreground=GOLD).pack(
            anchor="w", padx=14, pady=(0, 6))

        btn_row = tk.Frame(self, bg=SURFACE)
        btn_row.pack(pady=10)
        rbtn(btn_row, "Разобрать файл", command=self.parse, kind="ghost").pack(side="left", padx=6)
        self.import_btn = rbtn(btn_row, "Импортировать", command=self.do_import, kind="primary")
        self.import_btn.pack(side="left", padx=6)
        self.import_btn.configure(state="disabled")
        rbtn(btn_row, "Отмена", command=self.destroy, kind="ghost").pack(side="left", padx=6)

    def pick_file(self):
        path = filedialog.askopenfilename(
            title="Выберите файл выписки",
            filetypes=[("Выписка", "*.csv *.xlsx *.xlsm"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        self.path = path
        self.file_label.configure(text=os.path.basename(path))
        try:
            self.headers, self.rows = bank_import.read_table(path)
        except bank_import.BankImportError as e:
            messagebox.showerror("Ошибка", str(e))
            return
        values = self.headers
        for combo_attr in ("_combo_0", "_combo_1", "_combo_2"):
            getattr(self, combo_attr)["values"] = values
        dcol, acol, ncol = bank_import.guess_columns(self.headers)
        self.date_var.set(self.headers[dcol] if dcol is not None else "")
        self.amount_var.set(self.headers[acol] if acol is not None else "")
        self.note_var.set(self.headers[ncol] if ncol is not None else "")
        self.status_var.set(f"Загружено строк: {len(self.rows)}. Проверьте колонки и нажмите «Разобрать файл».")

    def parse(self):
        if not self.rows:
            messagebox.showwarning("Проверка", "Сначала выберите файл")
            return
        try:
            dcol = self.headers.index(self.date_var.get())
        except ValueError:
            dcol = None
        try:
            acol = self.headers.index(self.amount_var.get())
        except ValueError:
            acol = None
        ncol = self.headers.index(self.note_var.get()) if self.note_var.get() in self.headers else None
        try:
            parsed, skipped = bank_import.parse_rows(self.rows, dcol, acol, ncol)
        except bank_import.BankImportError as e:
            messagebox.showerror("Ошибка", str(e))
            return
        self.parsed = parsed
        self.status_var.set(f"Разобрано операций: {len(parsed)}, пропущено строк: {skipped}.")
        self.import_btn.configure(state="normal")

    def do_import(self):
        if not self.parsed:
            return
        account_id = self._acc_map.get(self.account_var.get()) or self.app.db.default_account_id()
        neg_is_expense = self.negative_is_expense.get()
        db = self.app.db
        misc_expense = next((c for c in db.get_categories("expense") if c["name"] == "Прочее"), None)
        misc_income = next((c for c in db.get_categories("income") if c["name"] == "Прочий доход"), None)
        imported = 0
        for row in self.parsed:
            amount = row["amount"]
            is_expense = (amount < 0) if neg_is_expense else (amount > 0)
            type_ = "expense" if is_expense else "income"
            amount = abs(amount)
            cat_id = db.get_category_for_note(row["note"], type_)
            if not cat_id:
                fallback = misc_expense if type_ == "expense" else misc_income
                cat_id = fallback["id"] if fallback else None
            db.add_transaction(type_, amount, cat_id, row["date"], row["note"], account_id=account_id)
            imported += 1
        self.destroy()
        self.app.refresh_all()
        messagebox.showinfo("Готово", f"Импортировано операций: {imported}")


class ReceiptSettingsDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Настройки распознавания чеков")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        cfg = receipts.load_config(app.receipts_base_dir)

        pad = {"padx": 14, "pady": 6}
        ttk.Label(self, text="API-ключ OpenAI (GPT)", style="Card.TLabel").pack(anchor="w", **pad)
        self.key_var = tk.StringVar(value=cfg["api_key"])
        ttk.Entry(self, textvariable=self.key_var, width=44, show="•").pack(padx=14)

        ttk.Label(self, text="Модель", style="Card.TLabel").pack(anchor="w", **pad)
        self.model_var = tk.StringVar(value=cfg["model"])
        ttk.Entry(self, textvariable=self.model_var, width=44).pack(padx=14)

        ttk.Label(
            self,
            text="Ключ можно получить на platform.openai.com/api-keys. Он хранится только на этом "
                 "компьютере, в файле receipt_config.json рядом с программой, и никуда, кроме "
                 "запросов к OpenAI, не отправляется. Фото чека уходит на сервер распознавания "
                 "только при нажатии «Загрузить чек».",
            style="Card.TLabel", foreground=INK_DIM, wraplength=380, justify="left",
        ).pack(padx=14, pady=(10, 6))

        btn_row = tk.Frame(self, bg=SURFACE)
        btn_row.pack(pady=14)
        rbtn(btn_row, "Сохранить", command=self.save, kind="primary").pack(side="left", padx=6)
        rbtn(btn_row, "Отмена", command=self.destroy, kind="ghost").pack(side="left", padx=6)

    def save(self):
        receipts.save_config(self.app.receipts_base_dir, self.key_var.get(), self.model_var.get())
        self.destroy()
        messagebox.showinfo("Готово", "Настройки сохранены.")


class ReceiptReviewDialog(tk.Toplevel):
    """Показывает распознанные данные чека и даёт их поправить перед сохранением."""

    def __init__(self, master, app, parsed, image_path):
        super().__init__(master)
        self.app = app
        self.image_path = image_path
        self.title("Проверьте данные чека")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        pad = {"padx": 14, "pady": 6}

        self.type_var = tk.StringVar(value="expense")
        row = tk.Frame(self, bg=SURFACE)
        row.pack(**pad)
        ttk.Radiobutton(row, text="Расход", variable=self.type_var, value="expense",
                         command=self._reload_categories).pack(side="left", padx=4)
        ttk.Radiobutton(row, text="Доход", variable=self.type_var, value="income",
                         command=self._reload_categories).pack(side="left", padx=4)

        ttk.Label(self, text="Сумма, ₽", style="Card.TLabel").pack(anchor="w", **pad)
        amount = parsed.get("amount")
        self.amount_var = tk.StringVar(value=(f"{amount:g}" if amount else ""))
        ttk.Entry(self, textvariable=self.amount_var, width=30).pack(padx=14)

        ttk.Label(self, text="Дата (ГГГГ-ММ-ДД)", style="Card.TLabel").pack(anchor="w", **pad)
        self.date_var = tk.StringVar(value=parsed.get("date") or date.today().isoformat())
        ttk.Entry(self, textvariable=self.date_var, width=30).pack(padx=14)

        ttk.Label(self, text="Категория", style="Card.TLabel").pack(anchor="w", **pad)
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(self, textvariable=self.category_var, width=28, state="readonly")
        self.category_combo.pack(padx=14)

        accounts = app.db.get_accounts()
        self._acc_map = {a["name"]: a["id"] for a in accounts}
        ttk.Label(self, text="Счёт", style="Card.TLabel").pack(anchor="w", **pad)
        self.account_var = tk.StringVar(value=next(iter(self._acc_map), ""))
        ttk.Combobox(self, textvariable=self.account_var, values=list(self._acc_map.keys()),
                     state="readonly", width=28).pack(padx=14)

        ttk.Label(self, text="Заметка", style="Card.TLabel").pack(anchor="w", **pad)
        self.note_var = tk.StringVar(value=parsed.get("note") or "")
        ttk.Entry(self, textvariable=self.note_var, width=30).pack(padx=14)

        self._reload_categories(preselect=parsed.get("category"))

        btn_row = tk.Frame(self, bg=SURFACE)
        btn_row.pack(pady=14)
        rbtn(btn_row, "Добавить операцию", command=self.save, kind="primary").pack(side="left", padx=6)
        rbtn(btn_row, "Отмена", command=self.destroy, kind="ghost").pack(side="left", padx=6)

    def _reload_categories(self, preselect=None):
        cats = self.app.db.get_categories(self.type_var.get())
        self._cat_map = {c["name"]: c["id"] for c in cats}
        self.category_combo["values"] = list(self._cat_map.keys())
        if preselect and preselect in self._cat_map:
            self.category_var.set(preselect)
        elif self._cat_map:
            self.category_var.set(next(iter(self._cat_map)))
        else:
            self.category_var.set("")

    def save(self):
        try:
            amount = float(str(self.amount_var.get()).replace(",", "."))
        except ValueError:
            messagebox.showwarning("Проверка", "Введите корректную сумму")
            return
        cat_id = self._cat_map.get(self.category_var.get())
        d = self.date_var.get().strip()
        if amount <= 0 or not cat_id or not d:
            messagebox.showwarning("Проверка", "Заполните сумму, категорию и дату")
            return
        note = self.note_var.get().strip()
        account_id = self._acc_map.get(self.account_var.get())
        tx_id = self.app.db.add_transaction(self.type_var.get(), amount, cat_id, d, note, account_id=account_id)
        self._save_receipt_copy(tx_id, note)
        self.destroy()
        self.app.refresh_all()

    def _save_receipt_copy(self, tx_id, note):
        """Копирует фото чека в receipts/, привязывая его к операции через id в имени файла."""
        try:
            receipts_dir = self.app.receipts_dir()
            os.makedirs(receipts_dir, exist_ok=True)
            ext = os.path.splitext(self.image_path)[1].lower() or ".jpg"
            safe_note = "".join(c for c in note if c.isalnum() or c in " _-").strip()[:30]
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = f"_{safe_note}" if safe_note else ""
            dest = os.path.join(receipts_dir, f"{tx_id}_{stamp}{suffix}{ext}")
            shutil.copy2(self.image_path, dest)
        except OSError:
            pass  # операция уже сохранена — если чек не скопировался, это не критично


# =================================================================
# Вкладка "Дашборд"
# =================================================================

class DashboardTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self._build()

    def _build(self):
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)

        self.hero_row = tk.Frame(outer, bg=BG)
        self.hero_row.pack(fill="x", pady=(0, 10))
        self.hero_row.columnconfigure(0, weight=3)
        self.hero_row.columnconfigure(1, weight=2)

        self.hero_card = RoundedCard(self.hero_row, radius=18, pad=18)
        self.hero_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.side_stats = tk.Frame(self.hero_row, bg=BG)
        self.side_stats.grid(row=0, column=1, sticky="nsew")

        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        self.budget_card = RoundedCard(body, radius=16)
        self.budget_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=6)
        ttk.Label(self.budget_card.body, text="Бюджет по категориям", style="Card.TLabel",
                  font=(FONT_UI, 12, "bold")).pack(anchor="w", pady=(0, 8))
        self.budget_rows = tk.Frame(self.budget_card.body, bg=SURFACE)
        self.budget_rows.pack(fill="x")

        pie_card = RoundedCard(body, radius=16)
        pie_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=6)
        ttk.Label(pie_card.body, text="Расходы по категориям", style="Card.TLabel",
                  font=(FONT_UI, 12, "bold")).pack(anchor="w")
        self.pie_fig = Figure(figsize=(4, 3), dpi=90, facecolor=SURFACE)
        self.pie_ax = self.pie_fig.add_subplot(111)
        self.pie_canvas = FigureCanvasTkAgg(self.pie_fig, master=pie_card.body)
        self.pie_canvas.get_tk_widget().pack(fill="both", expand=True)

        trend_card = RoundedCard(outer, radius=16)
        trend_card.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(trend_card.body, text="Динамика за 6 месяцев", style="Card.TLabel",
                  font=(FONT_UI, 12, "bold")).pack(anchor="w")
        self.trend_fig = Figure(figsize=(6, 2.6), dpi=90, facecolor=SURFACE)
        self.trend_ax = self.trend_fig.add_subplot(111)
        self.trend_canvas = FigureCanvasTkAgg(self.trend_fig, master=trend_card.body)
        self.trend_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _build_hero(self, income, expense, balance, alltime_balance, total_saved, forecast_text, spark_values):
        for w in self.hero_card.body.winfo_children():
            w.destroy()
        top = tk.Frame(self.hero_card.body, bg=SURFACE)
        top.pack(fill="x")
        ttk.Label(top, text="Баланс за месяц", style="Card.TLabel", foreground=INK_DIM,
                  font=(FONT_UI, 10)).pack(side="left")
        color = INCOME if balance >= 0 else EXPENSE
        ttk.Label(self.hero_card.body, text=fmt_money(balance), background=SURFACE, foreground=INK,
                  font=(FONT_UI, 28, "bold")).pack(anchor="w", pady=(6, 0))
        ttk.Label(self.hero_card.body,
                  text=f"за всё время {fmt_money(alltime_balance)} · в копилках {fmt_money(total_saved)}",
                  style="Card.TLabel", foreground=INK_FAINT, font=(FONT_MONO, 9)).pack(anchor="w", pady=(4, 0))
        if forecast_text:
            ttk.Label(self.hero_card.body, text=forecast_text, style="Card.TLabel", foreground=GOLD,
                      font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(4, 0))

        spark = tk.Canvas(self.hero_card.body, height=54, bg=SURFACE, highlightthickness=0)
        spark.pack(fill="x", pady=(10, 0))

        def draw_spark(event=None):
            spark.delete("all")
            w = spark.winfo_width()
            h = 54
            if w < 10 or len(spark_values) < 2:
                return
            lo, hi = min(spark_values), max(spark_values)
            span = (hi - lo) or 1
            n = len(spark_values)
            pts = []
            for i, v in enumerate(spark_values):
                x = i / (n - 1) * (w - 8) + 4
                y = h - 8 - (v - lo) / span * (h - 16)
                pts.extend([x, y])
            spark.create_line(*pts, fill=ACCENT, width=2, smooth=True, capstyle="round")

        spark.bind("<Configure>", draw_spark)

    def refresh(self):
        db = self.app.db
        month = self.app.current_month
        txs = db.get_transactions(month=month)
        income = sum(t["amount"] for t in txs if t["type"] == "income")
        expense = sum(t["amount"] for t in txs if t["type"] == "expense")
        balance = income - expense
        all_tx = db.all_transactions()
        alltime_balance = sum(t["amount"] if t["type"] == "income" else -t["amount"] for t in all_tx)
        total_saved = sum(g["current"] for g in db.get_savings())

        forecast_text = ""
        today = date.today()
        if month == month_key(today):
            days_in_month = calendar.monthrange(today.year, today.month)[1]
            days_passed = today.day
            daily_avg = expense / days_passed if days_passed else 0
            remaining_days = days_in_month - days_passed
            due_later = db.get_recurring_due_later(today.isoformat())
            recurring_left = sum(r["amount"] for r in due_later)
            projected_expense = expense + daily_avg * remaining_days + recurring_left
            projected_balance = income - projected_expense
            forecast_text = f"Прогноз к концу месяца: {fmt_money(projected_balance)} при текущем темпе"

        day_sorted = sorted(txs, key=lambda t: t["date"])
        running = 0.0
        spark_values = [0.0]
        for t in day_sorted:
            running += t["amount"] if t["type"] == "income" else -t["amount"]
            spark_values.append(running)
        if len(spark_values) < 2:
            spark_values = [0.0, balance]

        self._build_hero(income, expense, balance, alltime_balance, total_saved, forecast_text, spark_values)

        for w in self.side_stats.winfo_children():
            w.destroy()
        prev_month = shift_month(month, -1)
        prev_txs = db.get_transactions(month=prev_month)
        prev_income = sum(t["amount"] for t in prev_txs if t["type"] == "income")
        prev_expense = sum(t["amount"] for t in prev_txs if t["type"] == "expense")

        def pct_delta(cur, prev):
            if prev <= 0:
                return None
            return (cur - prev) / prev * 100

        for icon, label, value, color, prev in (
            ("income", "Доход", income, INCOME, prev_income),
            ("expense", "Расход", expense, EXPENSE, prev_expense),
        ):
            card = RoundedCard(self.side_stats, radius=16, pad=14)
            card.pack(fill="both", expand=True, pady=(0 if icon == "income" else 8, 8 if icon == "income" else 0))
            head = tk.Frame(card.body, bg=SURFACE)
            head.pack(fill="x")
            icon_badge(head, "▲" if icon == "income" else "▼", color, size=26).pack(side="left", padx=(0, 8))
            ttk.Label(head, text=label, style="Card.TLabel", foreground=INK_DIM, font=(FONT_UI, 9)).pack(side="left")
            bottom = tk.Frame(card.body, bg=SURFACE)
            bottom.pack(fill="x", pady=(6, 0))
            ttk.Label(bottom, text=fmt_money(value), background=SURFACE, foreground=color,
                      font=(FONT_UI, 15, "bold")).pack(side="left")
            delta = pct_delta(value, prev)
            if delta is not None:
                arrow = "▲" if delta >= 0 else "▼"
                dcolor = INCOME if (delta >= 0) == (icon == "income") else EXPENSE
                ttk.Label(bottom, text=f"{arrow} {abs(delta):.0f}%", background=SURFACE, foreground=dcolor,
                          font=(FONT_MONO, 9, "bold")).pack(side="right")

        # бюджеты по категориям
        for w in self.budget_rows.winfo_children():
            w.destroy()
        expense_cats = [c for c in db.get_categories("expense") if c["limit_amount"] > 0]
        spent_map = {}
        for t in txs:
            if t["type"] == "expense" and t["category_id"]:
                spent_map[t["category_id"]] = spent_map.get(t["category_id"], 0) + t["amount"]
        if not expense_cats:
            ttk.Label(self.budget_rows, text="Задайте лимиты в разделе «Категории», чтобы видеть бюджет здесь.",
                      style="Card.TLabel", foreground=INK_DIM, wraplength=260).pack(anchor="w", pady=8)
        for c in expense_cats:
            spent = spent_map.get(c["id"], 0)
            row = tk.Frame(self.budget_rows, bg=SURFACE)
            row.pack(fill="x", pady=5)
            head = tk.Frame(row, bg=SURFACE)
            head.pack(fill="x")
            dot = tk.Canvas(head, width=10, height=10, bg=SURFACE, highlightthickness=0)
            dot.create_oval(0, 0, 10, 10, fill=c["color"], outline="")
            dot.pack(side="left", padx=(0, 6))
            ttk.Label(head, text=c["name"], style="Card.TLabel").pack(side="left")
            over = spent > c["limit_amount"] > 0
            fig_color = DANGER if over else INK_DIM
            ttk.Label(head, text=f"{fmt_money(spent)} / {fmt_money(c['limit_amount'])}", style="Card.TLabel",
                      foreground=fig_color, font=(FONT_MONO, 9)).pack(side="right")
            make_bar(row, spent, c["limit_amount"], c["color"], width=280, height=7).pack(fill="x", pady=(4, 0))

        # круговая диаграмма
        self.pie_ax.clear()
        self.pie_ax.set_facecolor(SURFACE)
        pie_data = [(c["name"], spent_map.get(c["id"], 0), c["color"])
                    for c in db.get_categories("expense") if spent_map.get(c["id"], 0) > 0]
        if pie_data:
            labels, values, colors = zip(*pie_data)
            wedges, _ = self.pie_ax.pie(values, colors=colors, startangle=90,
                                         wedgeprops=dict(width=0.42, edgecolor=SURFACE))
            self.pie_ax.legend(wedges, [f"{l} — {fmt_money(v)}" for l, v in zip(labels, values)],
                                loc="center left", bbox_to_anchor=(1, 0.5), fontsize=8,
                                facecolor=SURFACE, labelcolor=INK, frameon=False)
        else:
            self.pie_ax.text(0.5, 0.5, "Нет расходов за месяц", ha="center", va="center",
                              color=INK_DIM, fontsize=10, transform=self.pie_ax.transAxes)
        self.pie_ax.axis("equal")
        self.pie_fig.tight_layout()
        self.pie_canvas.draw()

        # тренд
        self.trend_ax.clear()
        self.trend_ax.set_facecolor(SURFACE)
        months = [shift_month(month, -i) for i in range(5, -1, -1)]
        inc_vals, exp_vals, labels = [], [], []
        for mk in months:
            mtx = db.get_transactions(month=mk)
            inc_vals.append(sum(t["amount"] for t in mtx if t["type"] == "income"))
            exp_vals.append(sum(t["amount"] for t in mtx if t["type"] == "expense"))
            labels.append(MONTHS_SHORT[int(mk.split("-")[1]) - 1])
        x = range(len(months))
        width = 0.35
        self.trend_ax.bar([i - width / 2 for i in x], inc_vals, width, label="Доход", color=INCOME)
        self.trend_ax.bar([i + width / 2 for i in x], exp_vals, width, label="Расход", color=EXPENSE)
        self.trend_ax.set_xticks(list(x))
        self.trend_ax.set_xticklabels(labels, color=INK_DIM, fontsize=9)
        self.trend_ax.tick_params(axis="y", colors=INK_DIM, labelsize=8)
        for spine in self.trend_ax.spines.values():
            spine.set_color(LINE)
        self.trend_ax.legend(facecolor=SURFACE, labelcolor=INK, frameon=False, fontsize=8, loc="upper left")
        self.trend_ax.grid(axis="y", color=LINE, linewidth=0.5, alpha=0.6)
        self.trend_fig.subplots_adjust(left=0.12, right=0.98, top=0.92, bottom=0.15)
        self.trend_canvas.draw()


# =================================================================
# Вкладка "Операции"
# =================================================================

class TransactionsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self.editing_id = None
        self._autofill_job = None
        self._build()

    def _build(self):
        form_card = RoundedCard(self, radius=16)
        form_card.pack(fill="x", pady=(6, 10))
        form = form_card.body

        top = tk.Frame(form, bg=SURFACE)
        top.pack(fill="x", pady=(0, 6))

        self.type_var = tk.StringVar(value="expense")
        seg = SegmentToggle(top, [("expense", "Расход"), ("income", "Доход")], self.type_var,
                             command=self._reload_categories, parent_bg=SURFACE)
        seg.pack(side="left")

        fields = tk.Frame(form, bg=SURFACE)
        fields.pack(fill="x", pady=6)

        ttk.Label(fields, text="Сумма, ₽", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.amount_var = tk.StringVar()
        amount_entry = ttk.Entry(fields, textvariable=self.amount_var, width=14)
        amount_entry.grid(row=1, column=0, padx=(0, 10), sticky="w")

        ttk.Label(fields, text="Дата (ГГГГ-ММ-ДД)", style="Card.TLabel").grid(row=0, column=1, sticky="w")
        self.date_var = tk.StringVar(value=date.today().isoformat())
        date_entry = ttk.Entry(fields, textvariable=self.date_var, width=13)
        date_entry.grid(row=1, column=1, padx=(0, 10), sticky="w")

        ttk.Label(fields, text="Категория", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(fields, textvariable=self.category_var, width=17, state="readonly")
        self.category_combo.grid(row=1, column=2, padx=(0, 10), sticky="w")

        ttk.Label(fields, text="Счёт", style="Card.TLabel").grid(row=0, column=3, sticky="w")
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(fields, textvariable=self.account_var, width=15, state="readonly")
        self.account_combo.grid(row=1, column=3, padx=(0, 10), sticky="w")

        ttk.Label(fields, text="Заметка", style="Card.TLabel").grid(row=0, column=4, sticky="w")
        self.note_var = tk.StringVar()
        note_entry = ttk.Entry(fields, textvariable=self.note_var, width=20)
        note_entry.grid(row=1, column=4, sticky="w")
        note_entry.bind("<KeyRelease>", self._on_note_typed)

        # Enter в любом поле формы — добавить операцию (или сохранить изменения при редактировании)
        for widget in (amount_entry, date_entry, self.category_combo, self.account_combo, note_entry):
            widget.bind("<Return>", lambda e: self.submit())

        btn_row = tk.Frame(form, bg=SURFACE)
        btn_row.pack(fill="x", pady=(6, 0))
        self.submit_btn = rbtn(btn_row, "+ Добавить", command=self.submit, kind="primary")
        self.submit_btn.pack(side="left")
        self.cancel_edit_btn = rbtn(btn_row, "Отменить изменение", command=self.cancel_edit, kind="ghost")

        # поиск
        search_row = tk.Frame(self, bg=BG)
        search_row.pack(fill="x", pady=(0, 6))
        ttk.Label(search_row, text="Поиск:", background=BG, foreground=INK_DIM).pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.search_var, width=26)
        search_entry.pack(side="left", padx=8)
        search_entry.bind("<KeyRelease>", lambda e: self.refresh())
        self.search_all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_row, text="искать за всё время", variable=self.search_all_var,
                        command=self.refresh).pack(side="left", padx=(0, 12))
        rbtn(search_row, "Импорт выписки", command=self.open_import, kind="ghost").pack(side="right", padx=(8, 0))
        rbtn(search_row, "Экспорт в Excel/CSV", command=self.export, kind="ghost").pack(side="right")

        # список
        columns = ("date", "type", "category", "account", "amount", "note")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=13)
        headings = {"date": "Дата", "type": "Тип", "category": "Категория", "account": "Счёт",
                    "amount": "Сумма", "note": "Заметка"}
        widths = {"date": 85, "type": 65, "category": 110, "account": 100, "amount": 95, "note": 190}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.load_selected_for_edit())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())

        list_btns = tk.Frame(self, bg=BG)
        list_btns.pack(fill="x", pady=8)
        rbtn(list_btns, "Изменить выбранное", command=self.load_selected_for_edit, kind="ghost").pack(side="left")
        rbtn(list_btns, "Прикрепить фото", command=self.attach_photo, kind="ghost").pack(side="left", padx=8)
        rbtn(list_btns, "Удалить выбранное", command=self.delete_selected, kind="danger").pack(side="left")

        self._reload_accounts()
        self._reload_categories()

    def _reload_accounts(self):
        accounts = self.app.db.get_accounts()
        self._acc_map = {a["name"]: a["id"] for a in accounts}
        self.account_combo["values"] = list(self._acc_map.keys())
        if self._acc_map and not self.account_var.get():
            self.account_var.set(next(iter(self._acc_map)))

    def _reload_categories(self):
        cats = self.app.db.get_categories(self.type_var.get())
        self._cat_map = {c["name"]: c["id"] for c in cats}
        self.category_combo["values"] = list(self._cat_map.keys())
        if self._cat_map:
            self.category_var.set(next(iter(self._cat_map)))
        else:
            self.category_var.set("")

    def _on_note_typed(self, event):
        if self._autofill_job:
            self.after_cancel(self._autofill_job)
        self._autofill_job = self.after(400, self._try_autofill_category)

    def _try_autofill_category(self):
        note = self.note_var.get().strip()
        if len(note) < 2:
            return
        cat_id = self.app.db.get_category_for_note(note, self.type_var.get())
        if not cat_id:
            return
        cat = self.app.db.get_category(cat_id)
        if cat and cat["name"] in self._cat_map:
            self.category_var.set(cat["name"])

    def submit(self):
        try:
            amount = float(self.amount_var.get())
        except ValueError:
            messagebox.showwarning("Проверка", "Введите корректную сумму")
            return
        cat_id = self._cat_map.get(self.category_var.get())
        account_id = self._acc_map.get(self.account_var.get())
        d = self.date_var.get().strip()
        if amount <= 0 or not cat_id or not d or not account_id:
            messagebox.showwarning("Проверка", "Заполните сумму, категорию, счёт и дату")
            return
        note = self.note_var.get().strip()
        db = self.app.db

        if self.type_var.get() == "expense":
            cat = db.get_category(cat_id)
            if cat and cat["limit_amount"] > 0:
                month = d[:7]
                spent = sum(
                    t["amount"] for t in db.get_transactions(month=month, category_id=cat_id)
                    if t["id"] != self.editing_id
                )
                if spent + amount > cat["limit_amount"]:
                    over = spent + amount - cat["limit_amount"]
                    if not messagebox.askyesno(
                        "Превышение лимита",
                        f"С этой операцией расход по категории «{cat['name']}» за {month} составит "
                        f"{fmt_money(spent + amount)} — это на {fmt_money(over)} больше лимита "
                        f"{fmt_money(cat['limit_amount'])}.\nВсё равно добавить?",
                    ):
                        return

        if self.editing_id:
            db.update_transaction(self.editing_id, self.type_var.get(), amount, cat_id, d, note, account_id)
            self.cancel_edit()
        else:
            db.add_transaction(self.type_var.get(), amount, cat_id, d, note, account_id=account_id)
        self.amount_var.set("")
        self.note_var.set("")
        self.app.refresh_all()

    def load_selected_for_edit(self):
        sel = self.tree.selection()
        if not sel:
            return
        tx_id = int(sel[0])
        tx = self.app.db.get_transaction(tx_id)
        if not tx:
            return
        self.editing_id = tx_id
        self.type_var.set(tx["type"])
        self._reload_categories()
        cat = self.app.db.get_category(tx["category_id"]) if tx["category_id"] else None
        if cat:
            self.category_var.set(cat["name"])
        acc = self.app.db.get_account(tx["account_id"]) if tx["account_id"] else None
        if acc:
            self.account_var.set(acc["name"])
        self.amount_var.set(str(tx["amount"]))
        self.date_var.set(tx["date"])
        self.note_var.set(tx["note"] or "")
        self.submit_btn.configure(text="Сохранить изменения")
        self.cancel_edit_btn.pack(side="left", padx=8)

    def cancel_edit(self):
        self.editing_id = None
        self.submit_btn.configure(text="+ Добавить")
        self.cancel_edit_btn.pack_forget()
        self.amount_var.set("")
        self.note_var.set("")
        self.date_var.set(date.today().isoformat())

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        if messagebox.askyesno("Удаление", "Удалить выбранную операцию?"):
            self.app.db.delete_transaction(int(sel[0]))
            self.app.refresh_all()

    def attach_photo(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Прикрепить фото", "Сначала выберите операцию в списке.")
            return
        tx_id = int(sel[0])
        path = filedialog.askopenfilename(
            title="Выберите фото чека",
            filetypes=[("Изображения", "*.jpg *.jpeg *.png *.webp")],
        )
        if not path:
            return
        try:
            receipts_dir = self.app.receipts_dir()
            os.makedirs(receipts_dir, exist_ok=True)
            ext = os.path.splitext(path)[1].lower() or ".jpg"
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(receipts_dir, f"{tx_id}_{stamp}{ext}")
            shutil.copy2(path, dest)
            messagebox.showinfo("Готово", "Фото прикреплено к операции.")
            self.app.refresh_all()
        except OSError as e:
            messagebox.showerror("Ошибка", f"Не удалось скопировать файл:\n{e}")

    def open_import(self):
        BankImportDialog(self, self.app)

    def export(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx" if HAS_OPENPYXL else ".csv",
            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")] if HAS_OPENPYXL else [("CSV", "*.csv")],
            title="Сохранить отчёт",
        )
        if not path:
            return
        txs = self.app.db.all_transactions()
        rows = [("Дата", "Тип", "Категория", "Сумма", "Заметка")]
        for t in txs:
            rows.append((t["date"], "Доход" if t["type"] == "income" else "Расход",
                         t["category_name"] or "Без категории", t["amount"], t["note"] or ""))
        if path.endswith(".xlsx") and HAS_OPENPYXL:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Операции"
            for r in rows:
                ws.append(r)
            for cell in ws[1]:
                cell.font = XLFont(bold=True)
            wb.save(path)
        else:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerows(rows)
        messagebox.showinfo("Готово", f"Отчёт сохранён:\n{path}")

    def refresh(self):
        self._reload_accounts()
        for row in self.tree.get_children():
            self.tree.delete(row)
        month = None if self.search_all_var.get() else self.app.current_month
        txs = self.app.db.get_transactions(month=month, search=self.search_var.get().strip() or None)
        for t in txs:
            sign = "+" if t["type"] == "income" else "−"
            acc = self.app.db.get_account(t["account_id"]) if t["account_id"] else None
            self.tree.insert("", "end", iid=str(t["id"]), values=(
                t["date"], "Доход" if t["type"] == "income" else "Расход",
                t["category_name"] or "Без категории", acc["name"] if acc else "—",
                f"{sign}{fmt_money(t['amount'])}", t["note"] or ""
            ))


# =================================================================
# Вкладка "Счета"
# =================================================================

class AccountsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self._build()

    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", pady=(6, 10))
        self.total_label = ttk.Label(top, text="", background=BG, foreground=ACCENT, font=(FONT_MONO, 13, "bold"))
        self.total_label.pack(side="left")
        rbtn(top, "Перевести между счетами", command=lambda: TransferDialog(self, self.app),
             kind="ghost").pack(side="right", padx=(8, 0))
        rbtn(top, "+ Новый счёт", command=lambda: AccountDialog(self, self.app), kind="primary").pack(side="right")

        self.list_frame = tk.Frame(self, bg=BG)
        self.list_frame.pack(fill="both", expand=True)

    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        db = self.app.db
        accounts = db.get_accounts()
        total = sum(db.account_balance(a["id"]) for a in accounts)
        self.total_label.configure(text=f"Всего на счетах: {fmt_money(total)}")

        for a in accounts:
            balance = db.account_balance(a["id"])
            card = RoundedCard(self.list_frame, radius=16)
            card.pack(fill="x", pady=6)
            head = tk.Frame(card.body, bg=SURFACE)
            head.pack(fill="x")
            dot = tk.Canvas(head, width=12, height=12, bg=SURFACE, highlightthickness=0)
            dot.create_oval(0, 0, 12, 12, fill=a["color"], outline="")
            dot.pack(side="left", padx=(0, 8))
            ttk.Label(head, text=a["name"], style="Card.TLabel", font=(FONT_UI, 12, "bold")).pack(side="left")
            icon_button(head, "🗑", command=lambda a=a: self.delete(a["id"]), kind="danger").pack(
                side="right", padx=(6, 0))
            rbtn(head, "✎", command=lambda a=a: AccountDialog(self, self.app, a), kind="ghost",
                 width=34, hpad=0).pack(side="right")
            ttk.Label(card.body, text=fmt_money(balance), background=SURFACE,
                      foreground=INCOME if balance >= 0 else EXPENSE,
                      font=(FONT_UI, 18, "bold")).pack(anchor="w", pady=(6, 0))

        transfers = db.get_transfers()[:8]
        if transfers:
            hist_card = RoundedCard(self.list_frame, radius=16)
            hist_card.pack(fill="both", expand=True, pady=(6, 0))
            ttk.Label(hist_card.body, text="Последние переводы", style="Card.TLabel",
                      font=(FONT_UI, 11, "bold")).pack(anchor="w", pady=(0, 6))
            for t in transfers:
                row = tk.Frame(hist_card.body, bg=SURFACE)
                row.pack(fill="x", pady=3)
                ttk.Label(row, text=f"{t['date']}  {t['from_name']} → {t['to_name']}",
                          style="Card.TLabel", font=(FONT_MONO, 9)).pack(side="left")
                ttk.Label(row, text=fmt_money(t["amount"]), style="Card.TLabel", foreground=ACCENT,
                          font=(FONT_MONO, 9, "bold")).pack(side="right")

    def delete(self, account_id):
        if not messagebox.askyesno("Удаление", "Удалить счёт?"):
            return
        if not self.app.db.delete_account(account_id):
            messagebox.showwarning(
                "Нельзя удалить",
                "На этом счёте есть операции или переводы (или это последний оставшийся счёт) — "
                "сначала перенесите операции на другой счёт.",
            )
            return
        self.app.refresh_all()


# =================================================================
# Вкладка "Категории"
# =================================================================

class CategoriesTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self._build()

    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", pady=(6, 10))
        rbtn(top, "+ Новая категория расходов", command=lambda: self.open_dialog("expense"),
             kind="primary").pack(side="left")
        rbtn(top, "+ Новая категория дохода", command=lambda: self.open_dialog("income"),
             kind="ghost").pack(side="left", padx=8)

        cols = tk.Frame(self, bg=BG)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)

        self.expense_card = RoundedCard(cols, radius=16)
        self.expense_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(self.expense_card.body, text="Расходы", style="Card.TLabel",
                  font=(FONT_UI, 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.expense_rows = tk.Frame(self.expense_card.body, bg=SURFACE)
        self.expense_rows.pack(fill="both", expand=True)

        self.income_card = RoundedCard(cols, radius=16)
        self.income_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(self.income_card.body, text="Доходы", style="Card.TLabel",
                  font=(FONT_UI, 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.income_rows = tk.Frame(self.income_card.body, bg=SURFACE)
        self.income_rows.pack(fill="both", expand=True)

    def open_dialog(self, fixed_type, category=None):
        CategoryDialog(self, self.app, category=category, fixed_type=fixed_type)

    def _row(self, parent, category, spent):
        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x", pady=4)
        dot = tk.Canvas(row, width=10, height=10, bg=SURFACE, highlightthickness=0)
        dot.create_oval(0, 0, 10, 10, fill=category["color"], outline="")
        dot.pack(side="left", padx=(0, 8))
        info = tk.Frame(row, bg=SURFACE)
        info.pack(side="left", fill="x", expand=True)
        ttk.Label(info, text=category["name"], style="Card.TLabel").pack(anchor="w")
        if category["type"] == "expense":
            sub = f"{fmt_money(spent)} из {fmt_money(category['limit_amount'])}" if category["limit_amount"] > 0 else "лимит не задан"
            ttk.Label(info, text=sub, style="Card.TLabel", foreground=INK_DIM, font=(FONT_MONO, 8)).pack(anchor="w")
        icon_button(row, "🗑", command=lambda: self.delete(category["id"]), kind="danger").pack(side="right", padx=2)
        icon_button(row, "✎", command=lambda: self.open_dialog(category["type"], category),
                    kind="ghost").pack(side="right", padx=2)

    def delete(self, cat_id):
        if messagebox.askyesno("Удаление", "Удалить категорию? Операции с ней останутся без категории."):
            self.app.db.delete_category(cat_id)
            self.app.refresh_all()

    def refresh(self):
        for w in self.expense_rows.winfo_children():
            w.destroy()
        for w in self.income_rows.winfo_children():
            w.destroy()
        db = self.app.db
        txs = db.get_transactions(month=self.app.current_month)
        spent_map = {}
        for t in txs:
            if t["type"] == "expense" and t["category_id"]:
                spent_map[t["category_id"]] = spent_map.get(t["category_id"], 0) + t["amount"]
        for c in db.get_categories("expense"):
            self._row(self.expense_rows, c, spent_map.get(c["id"], 0))
        for c in db.get_categories("income"):
            self._row(self.income_rows, c, 0)


# =================================================================
# Вкладка "Копилки"
# =================================================================

class SavingsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self._build()

    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", pady=(6, 10))
        self.total_label = ttk.Label(top, text="", background=BG, foreground=GOLD, font=(FONT_MONO, 13, "bold"))
        self.total_label.pack(side="left")
        rbtn(top, "+ Новая копилка", command=lambda: GoalDialog(self, self.app), kind="primary").pack(side="right")

        self.list_frame = tk.Frame(self, bg=BG)
        self.list_frame.pack(fill="both", expand=True)

    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        savings = self.app.db.get_savings()
        total = sum(g["current"] for g in savings)
        self.total_label.configure(text=f"Всего в копилках: {fmt_money(total)}")
        if not savings:
            ttk.Label(self.list_frame, text="Пока нет накоплений — создайте первую цель выше.",
                      background=BG, foreground=INK_DIM).pack(pady=20)
        for g in savings:
            card = RoundedCard(self.list_frame, radius=16)
            card.pack(fill="x", pady=6)
            body = card.body
            head = tk.Frame(body, bg=SURFACE)
            head.pack(fill="x", pady=(0, 4))
            ttk.Label(head, text=g["name"], style="Card.TLabel", font=(FONT_UI, 12, "bold")).pack(side="left")
            icon_button(head, "🗑", command=lambda g=g: self.delete(g["id"]), kind="danger").pack(side="right", padx=(6, 0))
            rbtn(head, "✎ цель", command=lambda g=g: GoalDialog(self, self.app, g), kind="ghost").pack(side="right")
            make_bar(body, g["current"], g["target"], GOLD, width=520, height=10).pack(fill="x")
            nums = tk.Frame(body, bg=SURFACE)
            nums.pack(fill="x", pady=(6, 0))
            ttk.Label(nums, text=f"{fmt_money(g['current'])} из {fmt_money(g['target'])}",
                      style="Card.TLabel", foreground=INK_DIM, font=(FONT_MONO, 9)).pack(side="left")
            rbtn(nums, "Пополнить", command=lambda g=g: ContributeDialog(self, self.app, g),
                 kind="primary").pack(side="right")
            if g["target_date"]:
                try:
                    target_date = datetime.strptime(g["target_date"], "%Y-%m-%d").date()
                    months_left = max(1, round((target_date - date.today()).days / 30))
                    remaining = max(0, g["target"] - g["current"])
                    if (target_date - date.today()).days < 0:
                        deadline_text = f"Дата цели {g['target_date']} уже прошла"
                    elif remaining <= 0:
                        deadline_text = f"Цель уже достигнута — дедлайн {g['target_date']}"
                    else:
                        per_month = remaining / months_left
                        deadline_text = (f"Нужно ~{fmt_money(per_month)}/мес., чтобы успеть "
                                          f"к {g['target_date']}")
                    ttk.Label(body, text=deadline_text, style="Card.TLabel", foreground=GOLD,
                              font=(FONT_UI, 9)).pack(anchor="w", pady=(6, 0))
                except ValueError:
                    pass

    def delete(self, goal_id):
        if messagebox.askyesno("Удаление", "Удалить копилку и историю пополнений?"):
            self.app.db.delete_saving(goal_id)
            self.app.refresh_all()


# =================================================================
# Вкладка "Регулярные платежи"
# =================================================================

class RecurringTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self._build()

    def _build(self):
        info = ttk.Label(
            self,
            text="Регулярные платежи (подписки, аренда, зарплата) автоматически добавляются в «Операции» "
                 "при запуске программы, если наступил указанный день месяца.",
            background=BG, foreground=INK_DIM, wraplength=760, justify="left",
        )
        info.pack(fill="x", pady=(6, 10))

        form_card = RoundedCard(self, radius=16)
        form_card.pack(fill="x", pady=(0, 12))
        row = tk.Frame(form_card.body, bg=SURFACE)
        row.pack(fill="x")

        self.type_var = tk.StringVar(value="expense")
        seg = SegmentToggle(row, [("expense", "Расход"), ("income", "Доход")], self.type_var,
                             command=self._reload_categories, parent_bg=SURFACE, orient="vertical")
        seg.grid(row=0, column=0, rowspan=2, padx=(0, 12))

        ttk.Label(row, text="Сумма, ₽", style="Card.TLabel").grid(row=0, column=1, sticky="w")
        self.amount_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.amount_var, width=12).grid(row=1, column=1, padx=(0, 10), sticky="w")

        ttk.Label(row, text="День месяца", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.day_var = tk.StringVar(value="1")
        ttk.Entry(row, textvariable=self.day_var, width=6).grid(row=1, column=2, padx=(0, 10), sticky="w")

        ttk.Label(row, text="Категория", style="Card.TLabel").grid(row=0, column=3, sticky="w")
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(row, textvariable=self.category_var, width=16, state="readonly")
        self.category_combo.grid(row=1, column=3, padx=(0, 10), sticky="w")

        ttk.Label(row, text="Счёт", style="Card.TLabel").grid(row=0, column=4, sticky="w")
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(row, textvariable=self.account_var, width=14, state="readonly")
        self.account_combo.grid(row=1, column=4, padx=(0, 10), sticky="w")

        ttk.Label(row, text="Заметка", style="Card.TLabel").grid(row=0, column=5, sticky="w")
        self.note_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.note_var, width=16).grid(row=1, column=5, padx=(0, 10), sticky="w")

        rbtn(row, "+ Добавить", command=self.submit, kind="primary").grid(
            row=2, column=0, columnspan=6, sticky="w", pady=(10, 0))

        columns = ("type", "amount", "day", "category", "account", "note")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=10)
        headings = {"type": "Тип", "amount": "Сумма", "day": "День", "category": "Категория",
                    "account": "Счёт", "note": "Заметка"}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=110, anchor="w")
        self.tree.pack(fill="both", expand=True)

        rbtn(self, "Удалить выбранное", command=self.delete_selected, kind="danger").pack(anchor="w", pady=8)

        self._reload_accounts()
        self._reload_categories()

    def _reload_accounts(self):
        accounts = self.app.db.get_accounts()
        self._acc_map = {a["name"]: a["id"] for a in accounts}
        self.account_combo["values"] = list(self._acc_map.keys())
        if self._acc_map and not self.account_var.get():
            self.account_var.set(next(iter(self._acc_map)))

    def _reload_categories(self):
        cats = self.app.db.get_categories(self.type_var.get())
        self._cat_map = {c["name"]: c["id"] for c in cats}
        self.category_combo["values"] = list(self._cat_map.keys())
        if self._cat_map:
            self.category_var.set(next(iter(self._cat_map)))

    def submit(self):
        try:
            amount = float(self.amount_var.get())
            day = int(self.day_var.get())
        except ValueError:
            messagebox.showwarning("Проверка", "Проверьте сумму и день месяца")
            return
        if amount <= 0 or not (1 <= day <= 28):
            messagebox.showwarning("Проверка", "Сумма > 0, день месяца от 1 до 28")
            return
        cat_id = self._cat_map.get(self.category_var.get())
        account_id = self._acc_map.get(self.account_var.get())
        self.app.db.add_recurring(self.type_var.get(), amount, cat_id, day, self.note_var.get().strip(),
                                   account_id=account_id)
        self.amount_var.set("")
        self.note_var.set("")
        self.app.refresh_all()

    def delete_selected(self):
        sel = self.tree.selection()
        if sel and messagebox.askyesno("Удаление", "Удалить регулярный платёж?"):
            self.app.db.delete_recurring(int(sel[0]))
            self.app.refresh_all()

    def refresh(self):
        self._reload_accounts()
        for row in self.tree.get_children():
            self.tree.delete(row)
        for r in self.app.db.get_recurring():
            acc = self.app.db.get_account(r["account_id"]) if r["account_id"] else None
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                "Доход" if r["type"] == "income" else "Расход", fmt_money(r["amount"]), r["day_of_month"],
                r["category_name"] or "—", acc["name"] if acc else "—", r["note"] or ""
            ))


# =================================================================
# Вкладка "Чеки"
# =================================================================

class ReceiptsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self._build()

    def _build(self):
        info = ttk.Label(
            self,
            text="Загрузите фото или скан чека — сумма, дата, магазин и категория распознаются "
                 "автоматически через OpenAI (GPT), а перед сохранением их можно проверить и "
                 "поправить. Нужен свой API-ключ OpenAI (см. «Настройки распознавания») — "
                 "фото уходит на сервер распознавания только при нажатии «Загрузить чек», всё "
                 "остальное в программе по-прежнему хранится только на этом компьютере.",
            background=BG, foreground=INK_DIM, wraplength=760, justify="left",
        )
        info.pack(fill="x", pady=(6, 10))

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", pady=(0, 10))
        self.upload_btn = rbtn(top, "📎 Загрузить чек", command=self.upload, kind="primary")
        self.upload_btn.pack(side="left")
        rbtn(top, "⚙ Настройки распознавания", command=self.open_settings, kind="ghost").pack(side="left", padx=8)
        self.status_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.status_var, background=BG, foreground=GOLD).pack(side="left", padx=12)

        history_card = RoundedCard(self, radius=16)
        history_card.pack(fill="both", expand=True)
        ttk.Label(history_card.body, text="Загруженные чеки", style="Card.TLabel",
                  font=(FONT_UI, 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.history_rows = tk.Frame(history_card.body, bg=SURFACE)
        self.history_rows.pack(fill="both", expand=True)

        self.refresh()

    def open_settings(self):
        ReceiptSettingsDialog(self, self.app)

    def upload(self):
        path = filedialog.askopenfilename(
            title="Выберите фото чека",
            filetypes=[("Изображения", "*.jpg *.jpeg *.png *.webp")],
        )
        if not path:
            return
        cfg = receipts.load_config(self.app.receipts_base_dir)
        if not cfg["api_key"]:
            messagebox.showinfo("Нужен API-ключ",
                                 "Сначала укажите API-ключ OpenAI в «Настройках распознавания».")
            self.open_settings()
            return

        self.upload_btn.configure(state="disabled")
        self.status_var.set("Распознаём чек…")

        expense_cats = [c["name"] for c in self.app.db.get_categories("expense")]
        result_box = {}

        def worker():
            try:
                result_box["data"] = receipts.analyze_receipt(
                    path, expense_cats, cfg["api_key"], cfg["model"])
            except receipts.ReceiptError as e:
                result_box["error"] = str(e)
            except Exception as e:
                result_box["error"] = f"Неожиданная ошибка: {e}"

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.after(200, lambda: self._poll(thread, result_box, path))

    def _poll(self, thread, result_box, path):
        if thread.is_alive():
            self.after(200, lambda: self._poll(thread, result_box, path))
            return
        self.upload_btn.configure(state="normal")
        self.status_var.set("")
        if "error" in result_box:
            messagebox.showerror("Не удалось распознать чек", result_box["error"])
            parsed = {"amount": None, "date": None, "merchant": "", "category": "", "note": ""}
        else:
            parsed = result_box["data"]
        ReceiptReviewDialog(self, self.app, parsed, path)
        self.refresh()

    def refresh(self):
        for w in self.history_rows.winfo_children():
            w.destroy()
        receipts_dir = self.app.receipts_dir()
        files = []
        if os.path.isdir(receipts_dir):
            files = sorted(
                (f for f in os.listdir(receipts_dir) if os.path.isfile(os.path.join(receipts_dir, f))),
                key=lambda f: os.path.getmtime(os.path.join(receipts_dir, f)),
                reverse=True,
            )
        if not files:
            ttk.Label(self.history_rows, text="Пока нет загруженных чеков.",
                      style="Card.TLabel", foreground=INK_DIM).pack(anchor="w", pady=8)
            return
        for f in files[:50]:
            row = tk.Frame(self.history_rows, bg=SURFACE)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=f, style="Card.TLabel", font=(FONT_MONO, 9)).pack(side="left")
            rbtn(row, "Открыть", command=lambda f=f: self._open_file(os.path.join(receipts_dir, f)),
                 kind="ghost").pack(side="right")

    def _open_file(self, path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except OSError as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{e}")


# =================================================================
# Вкладка "Годовой отчёт"
# =================================================================

class YearReportTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="TFrame")
        self.app = app
        self.year = date.today().year
        self._build()

    def _build(self):
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)

        nav = tk.Frame(outer, bg=BG)
        nav.pack(fill="x", pady=(0, 10))
        icon_button(nav, "◀", command=lambda: self.change_year(-1), kind="ghost").pack(side="left")
        self.year_var = tk.StringVar(value=str(self.year))
        ttk.Label(nav, textvariable=self.year_var, font=(FONT_MONO, 12),
                  background=BG, foreground=INK_DIM, width=10, anchor="center").pack(side="left", padx=8)
        icon_button(nav, "▶", command=lambda: self.change_year(1), kind="ghost").pack(side="left")

        self.summary_frame = tk.Frame(outer, bg=BG)
        self.summary_frame.pack(fill="x", pady=(0, 10))

        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        self.category_card = RoundedCard(body, radius=16)
        self.category_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=6)
        ttk.Label(self.category_card.body, text="Расходы по категориям за год", style="Card.TLabel",
                  font=(FONT_UI, 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.category_rows = tk.Frame(self.category_card.body, bg=SURFACE)
        self.category_rows.pack(fill="both", expand=True)

        pie_card = RoundedCard(body, radius=16)
        pie_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=6)
        ttk.Label(pie_card.body, text="Доля расходов за год", style="Card.TLabel",
                  font=(FONT_UI, 12, "bold")).pack(anchor="w")
        self.pie_fig = Figure(figsize=(4, 3), dpi=90, facecolor=SURFACE)
        self.pie_ax = self.pie_fig.add_subplot(111)
        self.pie_canvas = FigureCanvasTkAgg(self.pie_fig, master=pie_card.body)
        self.pie_canvas.get_tk_widget().pack(fill="both", expand=True)

        chart_card = RoundedCard(outer, radius=16)
        chart_card.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(chart_card.body, text="Доходы и расходы по месяцам", style="Card.TLabel",
                  font=(FONT_UI, 12, "bold")).pack(anchor="w")
        self.trend_fig = Figure(figsize=(6, 2.6), dpi=90, facecolor=SURFACE)
        self.trend_ax = self.trend_fig.add_subplot(111)
        self.trend_canvas = FigureCanvasTkAgg(self.trend_fig, master=chart_card.body)
        self.trend_canvas.get_tk_widget().pack(fill="both", expand=True)

    def change_year(self, delta):
        self.year += delta
        self.year_var.set(str(self.year))
        self.refresh()

    def refresh(self):
        db = self.app.db
        txs = db.get_transactions_for_year(self.year)
        income = sum(t["amount"] for t in txs if t["type"] == "income")
        expense = sum(t["amount"] for t in txs if t["type"] == "expense")
        balance = income - expense

        for w in self.summary_frame.winfo_children():
            w.destroy()
        cards = [
            ("income", "Доход за год", income, INCOME),
            ("expense", "Расход за год", expense, EXPENSE),
            ("balance", "Баланс за год", balance, GOLD if balance >= 0 else DANGER),
            ("forecast", "Средний расход в месяц", expense / 12, INK_DIM),
        ]
        for i, (icon, label, value, color) in enumerate(cards):
            card = RoundedCard(self.summary_frame, radius=16, pad=14)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.summary_frame.columnconfigure(i, weight=1)
            row = tk.Frame(card.body, bg=SURFACE)
            row.pack(fill="x")
            icon_badge(row, "₽" if icon != "forecast" else "📊", color, size=36).pack(side="left", padx=(0, 8))
            text_col = tk.Frame(row, bg=SURFACE)
            text_col.pack(side="left", fill="x", expand=True)
            ttk.Label(text_col, text=label, style="Card.TLabel", foreground=INK_DIM,
                      font=(FONT_UI, 9)).pack(anchor="w")
            ttk.Label(text_col, text=fmt_money(value), background=SURFACE, foreground=color,
                      font=(FONT_UI, 15, "bold")).pack(anchor="w")

        for w in self.category_rows.winfo_children():
            w.destroy()
        spent_map = {}
        for t in txs:
            if t["type"] == "expense" and t["category_id"]:
                spent_map[t["category_id"]] = spent_map.get(t["category_id"], 0) + t["amount"]
        cat_by_id = {c["id"]: c for c in db.get_categories("expense")}
        sorted_items = sorted(spent_map.items(), key=lambda kv: kv[1], reverse=True)
        if not sorted_items:
            ttk.Label(self.category_rows, text="За этот год расходов ещё нет.",
                      style="Card.TLabel", foreground=INK_DIM, wraplength=260).pack(anchor="w", pady=8)
        for cat_id, spent in sorted_items:
            c = cat_by_id.get(cat_id)
            if not c:
                continue
            row = tk.Frame(self.category_rows, bg=SURFACE)
            row.pack(fill="x", pady=5)
            head = tk.Frame(row, bg=SURFACE)
            head.pack(fill="x")
            dot = tk.Canvas(head, width=10, height=10, bg=SURFACE, highlightthickness=0)
            dot.create_oval(0, 0, 10, 10, fill=c["color"], outline="")
            dot.pack(side="left", padx=(0, 6))
            ttk.Label(head, text=c["name"], style="Card.TLabel").pack(side="left")
            ttk.Label(head, text=fmt_money(spent), style="Card.TLabel",
                      foreground=INK_DIM, font=(FONT_MONO, 9)).pack(side="right")
            make_bar(row, spent, expense if expense > 0 else 1, c["color"], width=280, height=7).pack(
                fill="x", pady=(4, 0))

        self.pie_ax.clear()
        self.pie_ax.set_facecolor(SURFACE)
        pie_data = [(cat_by_id[cid]["name"], val, cat_by_id[cid]["color"])
                    for cid, val in sorted_items if cid in cat_by_id]
        if pie_data:
            labels, values, colors = zip(*pie_data)
            wedges, _ = self.pie_ax.pie(values, colors=colors, startangle=90,
                                         wedgeprops=dict(width=0.42, edgecolor=SURFACE))
            self.pie_ax.legend(wedges, [f"{l} — {fmt_money(v)}" for l, v in zip(labels, values)],
                                loc="center left", bbox_to_anchor=(1, 0.5), fontsize=8,
                                facecolor=SURFACE, labelcolor=INK, frameon=False)
        else:
            self.pie_ax.text(0.5, 0.5, "Нет расходов за год", ha="center", va="center",
                              color=INK_DIM, fontsize=10, transform=self.pie_ax.transAxes)
        self.pie_ax.axis("equal")
        self.pie_fig.tight_layout()
        self.pie_canvas.draw()

        self.trend_ax.clear()
        self.trend_ax.set_facecolor(SURFACE)
        monthly_income = [0.0] * 12
        monthly_expense = [0.0] * 12
        for t in txs:
            m = int(t["date"][5:7]) - 1
            if t["type"] == "income":
                monthly_income[m] += t["amount"]
            else:
                monthly_expense[m] += t["amount"]
        x = range(12)
        width = 0.35
        self.trend_ax.bar([i - width / 2 for i in x], monthly_income, width, label="Доход", color=INCOME)
        self.trend_ax.bar([i + width / 2 for i in x], monthly_expense, width, label="Расход", color=EXPENSE)
        self.trend_ax.set_xticks(list(x))
        self.trend_ax.set_xticklabels(MONTHS_SHORT, color=INK_DIM, fontsize=9)
        self.trend_ax.tick_params(axis="y", colors=INK_DIM, labelsize=8)
        for spine in self.trend_ax.spines.values():
            spine.set_color(LINE)
        self.trend_ax.legend(facecolor=SURFACE, labelcolor=INK, frameon=False, fontsize=8, loc="upper left")
        self.trend_ax.grid(axis="y", color=LINE, linewidth=0.5, alpha=0.6)
        self.trend_fig.subplots_adjust(left=0.08, right=0.98, top=0.92, bottom=0.15)
        self.trend_canvas.draw()


# =================================================================
# Экран входа по PIN-коду (перед созданием главного окна)
# =================================================================

def prompt_pin(base_dir):
    """Показывает окно ввода PIN. Возвращает True, если код верный или защита выключена."""
    if not authlock.is_enabled(base_dir):
        return True

    result = {"ok": False}
    win = tk.Tk()
    win.title("Мои финансы — вход")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.geometry("320x180")

    tk.Label(win, text="Введите PIN-код", bg=BG, fg=INK, font=(FONT_UI, 12, "bold")).pack(pady=(24, 10))
    pin_var = tk.StringVar()
    entry = tk.Entry(win, textvariable=pin_var, show="•", justify="center", font=(FONT_UI, 14),
                      bg=SURFACE2, fg=INK, insertbackground=INK, relief="flat")
    entry.pack(ipady=6, padx=30, fill="x")
    entry.focus_set()
    error_var = tk.StringVar(value="")
    tk.Label(win, textvariable=error_var, bg=BG, fg=EXPENSE, font=(FONT_UI, 9)).pack(pady=(6, 0))

    def try_ok(event=None):
        if authlock.check_pin(base_dir, pin_var.get()):
            result["ok"] = True
            win.destroy()
        else:
            error_var.set("Неверный PIN-код")
            pin_var.set("")

    def cancel():
        win.destroy()

    entry.bind("<Return>", try_ok)
    btn_row = tk.Frame(win, bg=BG)
    btn_row.pack(pady=16)
    rbtn(btn_row, "Войти", command=try_ok, kind="primary", parent_bg=BG).pack(side="left", padx=6)
    rbtn(btn_row, "Отмена", command=cancel, kind="ghost", parent_bg=BG).pack(side="left", padx=6)

    win.protocol("WM_DELETE_WINDOW", cancel)
    win.mainloop()
    return result["ok"]


# =================================================================
# Главное окно
# =================================================================

NAV_ITEMS = [
    ("dashboard", "dashboard", "Дашборд"),
    ("transactions", "transactions", "Операции"),
    ("accounts", "accounts", "Счета"),
    ("categories", "categories", "Категории"),
    ("savings", "savings", "Копилки"),
    ("recurring", "recurring", "Регулярные"),
    ("receipts", "receipts", "Чеки"),
    ("yearreport", "yearreport", "Годовой отчёт"),
]


class FinanceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Мои финансы")
        self.geometry("1180x740")
        self.minsize(980, 620)
        self.configure(bg=BG)
        self._set_app_icon()
        self.db = Database()
        self.receipts_base_dir = os.path.dirname(self.db.path)
        self.current_month = month_key(date.today())

        self._setup_style()
        self._build_layout()

        applied = self.db.apply_due_recurring(date.today().isoformat())
        self.refresh_all()
        if applied:
            messagebox.showinfo("Регулярные платежи", f"Автоматически добавлено операций: {len(applied)}")

        threading.Thread(target=self._check_update_async, daemon=True).start()

    def receipts_dir(self):
        return os.path.join(self.receipts_base_dir, "receipts")

    def _set_app_icon(self):
        """Заменяет стандартную иконку Tk на иконку приложения (icon.ico)."""
        icon_path = resource_path("icon.ico")
        try:
            if os.path.exists(icon_path):
                self.iconbitmap(default=icon_path)
        except tk.TclError:
            pass

    def _check_update_async(self):
        result = update_check.check_for_update()
        if result:
            self.after(0, lambda: self._show_update_banner(*result))

    def _show_update_banner(self, version, url):
        bar = tk.Frame(self, bg=ACCENT_SOFT)
        bar.pack(fill="x", side="bottom")
        tk.Label(bar, text=f"Доступна новая версия {version}", bg=ACCENT_SOFT, fg=INK,
                  font=(FONT_UI, 9, "bold")).pack(side="left", padx=12, pady=6)
        if url:
            rbtn(bar, "Открыть", command=lambda: __import__("webbrowser").open(url),
                 kind="ghost", parent_bg=ACCENT_SOFT, height=24).pack(side="left")
        rbtn(bar, "×", command=bar.destroy, kind="ghost", width=24, height=24,
             parent_bg=ACCENT_SOFT).pack(side="right", padx=8)

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=INK, fieldbackground=SURFACE2,
                        font=(FONT_UI, 10), borderwidth=0)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Card.TLabel", background=SURFACE, foreground=INK)
        style.configure("TButton", background=ACCENT, foreground=BG, padding=8,
                        font=(FONT_UI, 10, "bold"), borderwidth=0)
        style.map("TButton", background=[("active", _lighten(ACCENT))])
        style.configure("TEntry", fieldbackground=SURFACE2, foreground=INK, insertcolor=INK, borderwidth=0)
        style.configure("TCombobox", fieldbackground=SURFACE2, foreground=INK, background=SURFACE2, arrowcolor=INK)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE2)])
        style.configure("TCheckbutton", background=BG, foreground=INK_DIM)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("Treeview", background=SURFACE2, fieldbackground=SURFACE2, foreground=INK,
                        rowheight=26, borderwidth=0, font=(FONT_UI, 9))
        style.configure("Treeview.Heading", background=SURFACE, foreground=INK_DIM,
                        font=(FONT_UI, 9, "bold"), borderwidth=0)
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", BG)])

    def _build_layout(self):
        root_row = tk.Frame(self, bg=BG)
        root_row.pack(fill="both", expand=True, padx=16, pady=16)

        sidebar = tk.Frame(root_row, bg=BG, width=200)
        sidebar.pack(side="left", fill="y", padx=(0, 14))
        sidebar.pack_propagate(False)
        sidebar_card = RoundedCard(sidebar, radius=18, pad=12, shadow=False)
        sidebar_card.pack(fill="both", expand=True)
        sb = sidebar_card.body
        sidebar_card.configure(bg=BG)
        sidebar_card._canvas.configure(bg=BG)

        brand = tk.Frame(sb, bg=SURFACE)
        brand.pack(fill="x", pady=(0, 16))
        mark = tk.Canvas(brand, width=30, height=30, bg=SURFACE, highlightthickness=0)
        _rounded_rect(mark, 0, 0, 30, 30, 9, fill=ACCENT, outline="")
        mark.create_line(7, 11, 23, 11, fill=BG, width=2, capstyle="round")
        mark.create_line(7, 15, 23, 15, fill=BG, width=2, capstyle="round")
        mark.create_line(7, 19, 17, 19, fill=BG, width=2, capstyle="round")
        mark.pack(side="left")
        tk.Label(brand, text="Мои финансы", bg=SURFACE, fg=INK, font=(FONT_UI, 12, "bold")).pack(
            side="left", padx=10)

        nav_wrap = tk.Frame(sb, bg=BG)
        nav_wrap.pack(fill="x")
        self.nav_items = {}
        for key, icon_kind, label in NAV_ITEMS:
            item = NavItem(nav_wrap, icon_kind, label, command=lambda k=key: self.select_tab(k))
            item.pack(fill="x", pady=1)
            self.nav_items[key] = item

        footer = tk.Frame(sb, bg=SURFACE)
        footer.pack(fill="x", side="bottom", pady=(16, 0))
        tk.Label(footer, text="Данные хранятся локально. Фото чека уходит на распознавание "
                              "только по вашему запросу.",
                  bg=SURFACE, fg=INK_FAINT, font=(FONT_UI, 8), wraplength=160, justify="left").pack(
            anchor="w", pady=(0, 8))
        rbtn(footer, "🔒 Защита входа", command=lambda: SecurityDialog(self, self), kind="ghost",
             parent_bg=SURFACE).pack(fill="x")

        main = tk.Frame(root_row, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        header = tk.Frame(main, bg=BG)
        header.pack(fill="x", pady=(0, 10))
        icon_button(header, "◀", command=lambda: self.change_month(-1), kind="ghost").pack(side="left")
        self.month_var = tk.StringVar(value=month_label(self.current_month))
        ttk.Label(header, textvariable=self.month_var, font=(FONT_MONO, 12),
                  background=BG, foreground=INK_DIM, width=18, anchor="center").pack(side="left", padx=8)
        icon_button(header, "▶", command=lambda: self.change_month(1), kind="ghost").pack(side="left")

        self.content = tk.Frame(main, bg=BG)
        self.content.pack(fill="both", expand=True)

        self.tab_dashboard = DashboardTab(self.content, self)
        self.tab_transactions = TransactionsTab(self.content, self)
        self.tab_accounts = AccountsTab(self.content, self)
        self.tab_categories = CategoriesTab(self.content, self)
        self.tab_savings = SavingsTab(self.content, self)
        self.tab_recurring = RecurringTab(self.content, self)
        self.tab_receipts = ReceiptsTab(self.content, self)
        self.tab_yearreport = YearReportTab(self.content, self)

        self._tab_frames = {
            "dashboard": self.tab_dashboard,
            "transactions": self.tab_transactions,
            "accounts": self.tab_accounts,
            "categories": self.tab_categories,
            "savings": self.tab_savings,
            "recurring": self.tab_recurring,
            "receipts": self.tab_receipts,
            "yearreport": self.tab_yearreport,
        }
        for frame in self._tab_frames.values():
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.current_tab_key = "dashboard"
        self.select_tab("dashboard")

    def select_tab(self, key):
        for k, item in self.nav_items.items():
            item.set_active(k == key)
        self._tab_frames[key].tkraise()
        self.current_tab_key = key

    def change_month(self, delta):
        self.current_month = shift_month(self.current_month, delta)
        self.month_var.set(month_label(self.current_month))
        self.refresh_all()

    def refresh_all(self):
        self.tab_dashboard.refresh()
        self.tab_transactions.refresh()
        self.tab_accounts.refresh()
        self.tab_categories.refresh()
        self.tab_savings.refresh()
        self.tab_recurring.refresh()
        self.tab_receipts.refresh()
        self.tab_yearreport.refresh()


if __name__ == "__main__":
    _base_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    if prompt_pin(_base_dir):
        app = FinanceApp()
        app.mainloop()
