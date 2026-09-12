import os
import sys
import shutil
import subprocess
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
from datetime import date, datetime
import csv

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from database import Database
import receipts

try:
    import openpyxl
    from openpyxl.styles import Font as XLFont

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

# ---------------- палитра (тема "гроссбух") ----------------
BG = "#1B1F1D"
SURFACE = "#232823"
SURFACE2 = "#2B312B"
LINE = "#394038"
INK = "#ECE9DD"
INK_DIM = "#9BA398"
INCOME = "#8FBF9F"
EXPENSE = "#C1705B"
GOLD = "#D2A65A"
DANGER = "#D4574A"

PALETTE = ["#8FBF9F", "#D2A65A", "#7C93AA", "#B98CA0", "#BD6357",
           "#8AA9A5", "#C9B458", "#9C8AA5", "#7FA3C0", "#A78BFA"]

MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
             "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_SHORT = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
                 "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]


def resource_path(filename):
    """Путь к вложенному файлу (например, иконке) — как при запуске из исходников,
    так и из собранного PyInstaller-ом .exe (в том числе из папки с кириллицей в пути)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


def fmt_money(n):
    return f"{n:,.0f}".replace(",", " ") + " ₽"


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


def _widget_bg(widget, default=BG):
    """Пытается узнать фон родителя, чтобы скруглённый виджет слился с ним по углам."""
    try:
        return widget.cget("bg")
    except tk.TclError:
        return default


class RoundedCard(tk.Frame):
    """Карточка со скруглёнными углами. Дочерние виджеты кладите в card.body, как в обычный Frame."""

    def __init__(self, parent, bg=SURFACE, border=LINE, radius=14, pad=12, corner_bg=None, **kwargs):
        corner_bg = corner_bg if corner_bg is not None else _widget_bg(parent)
        super().__init__(parent, bg=corner_bg, highlightthickness=0, **kwargs)
        self._fill = bg
        self._outline = border
        self._radius = radius
        self._canvas = tk.Canvas(self, highlightthickness=0, bg=corner_bg, bd=0)
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)
        self._canvas.bind("<Configure>", self._redraw)

    def _redraw(self, event=None):
        c = self._canvas
        c.delete("card")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 4 or h < 4:
            return
        _rounded_rect(c, 1, 1, w - 1, h - 1, self._radius, fill=self._fill, outline=self._outline,
                       width=1, tags="card")


class RoundedButton(tk.Canvas):
    """Кнопка со скруглёнными углами и hover-эффектом, нарисованная на Canvas."""

    _KINDS = {
        # kind: (fill, fg, hover_fg)
        "primary": (GOLD, BG, BG),
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
        self._font = font or ("Segoe UI", 10, "bold")
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
                          radius=size // 2, hpad=0, font=font or ("Segoe UI", 11), **kwargs)


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
        db = self.app.db
        if self.goal:
            db.update_saving(self.goal["id"], name=name, target=target)
        else:
            db.add_saving(name, target)
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
        tx_id = self.app.db.add_transaction(self.type_var.get(), amount, cat_id, d, note)
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

        # сводка
        self.summary_frame = tk.Frame(outer, bg=BG)
        self.summary_frame.pack(fill="x", pady=(6, 10))

        self.alltime_label = ttk.Label(outer, text="", background=BG, foreground=INK_DIM, font=("Segoe UI", 9))
        self.alltime_label.pack(pady=(0, 10))

        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        # бюджеты
        self.budget_card = RoundedCard(body, radius=16)
        self.budget_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=6)
        ttk.Label(self.budget_card.body, text="Бюджет по категориям", style="Card.TLabel",
                  font=("Georgia", 12, "bold")).pack(anchor="w", pady=(0, 8))
        self.budget_rows = tk.Frame(self.budget_card.body, bg=SURFACE)
        self.budget_rows.pack(fill="x")

        # круговая диаграмма
        pie_card = RoundedCard(body, radius=16)
        pie_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=6)
        ttk.Label(pie_card.body, text="Расходы по категориям", style="Card.TLabel",
                  font=("Georgia", 12, "bold")).pack(anchor="w")
        self.pie_fig = Figure(figsize=(4, 3), dpi=90, facecolor=SURFACE)
        self.pie_ax = self.pie_fig.add_subplot(111)
        self.pie_canvas = FigureCanvasTkAgg(self.pie_fig, master=pie_card.body)
        self.pie_canvas.get_tk_widget().pack(fill="both", expand=True)

        # тренд
        trend_card = RoundedCard(outer, radius=16)
        trend_card.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(trend_card.body, text="Динамика за 6 месяцев", style="Card.TLabel",
                  font=("Georgia", 12, "bold")).pack(anchor="w")
        self.trend_fig = Figure(figsize=(6, 2.6), dpi=90, facecolor=SURFACE)
        self.trend_ax = self.trend_fig.add_subplot(111)
        self.trend_canvas = FigureCanvasTkAgg(self.trend_fig, master=trend_card.body)
        self.trend_canvas.get_tk_widget().pack(fill="both", expand=True)

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

        for w in self.summary_frame.winfo_children():
            w.destroy()
        cards = [("💰", "Доход", income, INCOME), ("💸", "Расход", expense, EXPENSE),
                 ("⚖", "Баланс", balance, GOLD if balance >= 0 else DANGER)]
        for i, (icon, label, value, color) in enumerate(cards):
            card = RoundedCard(self.summary_frame, radius=16, pad=14)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.summary_frame.columnconfigure(i, weight=1)
            head = tk.Frame(card.body, bg=SURFACE)
            head.pack(anchor="w", fill="x")
            ttk.Label(head, text=icon, background=SURFACE, font=("Segoe UI", 13)).pack(side="left", padx=(0, 6))
            ttk.Label(head, text=label, style="Card.TLabel", foreground=INK_DIM,
                      font=("Segoe UI", 9)).pack(side="left")
            ttk.Label(card.body, text=fmt_money(value), background=SURFACE, foreground=color,
                      font=("Consolas", 17, "bold")).pack(anchor="w", pady=(4, 0))

        self.alltime_label.configure(
            text=f"Баланс за всё время: {fmt_money(alltime_balance)}   ·   В копилках: {fmt_money(total_saved)}"
        )

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
            ttk.Label(head, text=f"{fmt_money(spent)} / {fmt_money(c['limit_amount'])}", style="Card.TLabel",
                      foreground=INK_DIM, font=("Consolas", 9)).pack(side="right")
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
        self._build()

    def _build(self):
        form_card = RoundedCard(self, radius=16)
        form_card.pack(fill="x", pady=(6, 10))
        form = form_card.body

        top = tk.Frame(form, bg=SURFACE)
        top.pack(fill="x", pady=(0, 6))

        self.type_var = tk.StringVar(value="expense")
        seg = tk.Frame(top, bg=SURFACE)
        seg.pack(side="left")
        self.expense_btn = tk.Radiobutton(seg, text="Расход", variable=self.type_var, value="expense",
                                           command=self._reload_categories, indicatoron=False,
                                           bg=SURFACE2, fg=EXPENSE, selectcolor=SURFACE2,
                                           activebackground=SURFACE2, borderwidth=0, padx=14, pady=6)
        self.expense_btn.pack(side="left", padx=(0, 4))
        self.income_btn = tk.Radiobutton(seg, text="Доход", variable=self.type_var, value="income",
                                          command=self._reload_categories, indicatoron=False,
                                          bg=SURFACE2, fg=INCOME, selectcolor=SURFACE2,
                                          activebackground=SURFACE2, borderwidth=0, padx=14, pady=6)
        self.income_btn.pack(side="left")

        fields = tk.Frame(form, bg=SURFACE)
        fields.pack(fill="x", pady=6)

        ttk.Label(fields, text="Сумма, ₽", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.amount_var = tk.StringVar()
        amount_entry = ttk.Entry(fields, textvariable=self.amount_var, width=16)
        amount_entry.grid(row=1, column=0, padx=(0, 10), sticky="w")

        ttk.Label(fields, text="Дата (ГГГГ-ММ-ДД)", style="Card.TLabel").grid(row=0, column=1, sticky="w")
        self.date_var = tk.StringVar(value=date.today().isoformat())
        date_entry = ttk.Entry(fields, textvariable=self.date_var, width=14)
        date_entry.grid(row=1, column=1, padx=(0, 10), sticky="w")

        ttk.Label(fields, text="Категория", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(fields, textvariable=self.category_var, width=20, state="readonly")
        self.category_combo.grid(row=1, column=2, padx=(0, 10), sticky="w")

        ttk.Label(fields, text="Заметка", style="Card.TLabel").grid(row=0, column=3, sticky="w")
        self.note_var = tk.StringVar()
        note_entry = ttk.Entry(fields, textvariable=self.note_var, width=24)
        note_entry.grid(row=1, column=3, sticky="w")

        # Enter в любом поле формы — добавить операцию (или сохранить изменения при редактировании)
        for widget in (amount_entry, date_entry, self.category_combo, note_entry):
            widget.bind("<Return>", lambda e: self.submit())

        btn_row = tk.Frame(form, bg=SURFACE)
        btn_row.pack(fill="x", pady=(6, 0))
        self.submit_btn = rbtn(btn_row, "+ Добавить", command=self.submit, kind="primary")
        self.submit_btn.pack(side="left")
        self.cancel_edit_btn = rbtn(btn_row, "Отменить изменение", command=self.cancel_edit, kind="ghost")

        # поиск
        search_row = tk.Frame(self, bg=BG)
        search_row.pack(fill="x", pady=(0, 6))
        ttk.Label(search_row, text="Поиск по заметке или категории:", background=BG, foreground=INK_DIM).pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.search_var, width=30)
        search_entry.pack(side="left", padx=8)
        search_entry.bind("<KeyRelease>", lambda e: self.refresh())
        rbtn(search_row, "Экспорт в Excel/CSV", command=self.export, kind="ghost").pack(side="right")

        # список
        columns = ("date", "type", "category", "amount", "note")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=14)
        headings = {"date": "Дата", "type": "Тип", "category": "Категория", "amount": "Сумма", "note": "Заметка"}
        widths = {"date": 90, "type": 70, "category": 130, "amount": 100, "note": 220}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.load_selected_for_edit())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())

        list_btns = tk.Frame(self, bg=BG)
        list_btns.pack(fill="x", pady=8)
        rbtn(list_btns, "Изменить выбранное", command=self.load_selected_for_edit, kind="ghost").pack(side="left")
        rbtn(list_btns, "Удалить выбранное", command=self.delete_selected, kind="danger").pack(side="left", padx=8)

        self._reload_categories()

    def _reload_categories(self):
        cats = self.app.db.get_categories(self.type_var.get())
        self._cat_map = {c["name"]: c["id"] for c in cats}
        self.category_combo["values"] = list(self._cat_map.keys())
        if self._cat_map:
            self.category_var.set(next(iter(self._cat_map)))
        else:
            self.category_var.set("")

    def submit(self):
        try:
            amount = float(self.amount_var.get())
        except ValueError:
            messagebox.showwarning("Проверка", "Введите корректную сумму")
            return
        cat_id = self._cat_map.get(self.category_var.get())
        d = self.date_var.get().strip()
        if amount <= 0 or not cat_id or not d:
            messagebox.showwarning("Проверка", "Заполните сумму, категорию и дату")
            return
        note = self.note_var.get().strip()
        db = self.app.db
        if self.editing_id:
            db.update_transaction(self.editing_id, self.type_var.get(), amount, cat_id, d, note)
            self.cancel_edit()
        else:
            db.add_transaction(self.type_var.get(), amount, cat_id, d, note)
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
        for row in self.tree.get_children():
            self.tree.delete(row)
        txs = self.app.db.get_transactions(month=self.app.current_month, search=self.search_var.get().strip() or None)
        for t in txs:
            sign = "+" if t["type"] == "income" else "−"
            self.tree.insert("", "end", iid=str(t["id"]), values=(
                t["date"], "Доход" if t["type"] == "income" else "Расход",
                t["category_name"] or "Без категории", f"{sign}{fmt_money(t['amount'])}", t["note"] or ""
            ))


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
                  font=("Georgia", 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.expense_rows = tk.Frame(self.expense_card.body, bg=SURFACE)
        self.expense_rows.pack(fill="both", expand=True)

        self.income_card = RoundedCard(cols, radius=16)
        self.income_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(self.income_card.body, text="Доходы", style="Card.TLabel",
                  font=("Georgia", 12, "bold")).pack(anchor="w", pady=(0, 6))
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
            ttk.Label(info, text=sub, style="Card.TLabel", foreground=INK_DIM, font=("Consolas", 8)).pack(anchor="w")
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
        self.total_label = ttk.Label(top, text="", background=BG, foreground=GOLD, font=("Consolas", 13, "bold"))
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
            ttk.Label(head, text=g["name"], style="Card.TLabel", font=("Georgia", 12, "bold")).pack(side="left")
            icon_button(head, "🗑", command=lambda g=g: self.delete(g["id"]), kind="danger").pack(side="right", padx=(6, 0))
            rbtn(head, "✎ цель", command=lambda g=g: GoalDialog(self, self.app, g), kind="ghost").pack(side="right")
            make_bar(body, g["current"], g["target"], GOLD, width=520, height=10).pack(fill="x")
            nums = tk.Frame(body, bg=SURFACE)
            nums.pack(fill="x", pady=(6, 0))
            ttk.Label(nums, text=f"{fmt_money(g['current'])} из {fmt_money(g['target'])}",
                      style="Card.TLabel", foreground=INK_DIM, font=("Consolas", 9)).pack(side="left")
            rbtn(nums, "Пополнить", command=lambda g=g: ContributeDialog(self, self.app, g),
                 kind="primary").pack(side="right")

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
        seg = tk.Frame(row, bg=SURFACE)
        seg.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        tk.Radiobutton(seg, text="Расход", variable=self.type_var, value="expense", command=self._reload_categories,
                       indicatoron=False, bg=SURFACE2, fg=EXPENSE, selectcolor=SURFACE2, borderwidth=0,
                       padx=10, pady=6).pack(side="top", pady=1)
        tk.Radiobutton(seg, text="Доход", variable=self.type_var, value="income", command=self._reload_categories,
                       indicatoron=False, bg=SURFACE2, fg=INCOME, selectcolor=SURFACE2, borderwidth=0,
                       padx=10, pady=6).pack(side="top", pady=1)

        ttk.Label(row, text="Сумма, ₽", style="Card.TLabel").grid(row=0, column=1, sticky="w")
        self.amount_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.amount_var, width=12).grid(row=1, column=1, padx=(0, 10), sticky="w")

        ttk.Label(row, text="День месяца", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.day_var = tk.StringVar(value="1")
        ttk.Entry(row, textvariable=self.day_var, width=6).grid(row=1, column=2, padx=(0, 10), sticky="w")

        ttk.Label(row, text="Категория", style="Card.TLabel").grid(row=0, column=3, sticky="w")
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(row, textvariable=self.category_var, width=18, state="readonly")
        self.category_combo.grid(row=1, column=3, padx=(0, 10), sticky="w")

        ttk.Label(row, text="Заметка", style="Card.TLabel").grid(row=0, column=4, sticky="w")
        self.note_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.note_var, width=20).grid(row=1, column=4, sticky="w")

        rbtn(row, "+ Добавить", command=self.submit, kind="primary").grid(row=1, column=5, padx=(12, 0))

        columns = ("type", "amount", "day", "category", "note")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=10)
        headings = {"type": "Тип", "amount": "Сумма", "day": "День", "category": "Категория", "note": "Заметка"}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=120, anchor="w")
        self.tree.pack(fill="both", expand=True)

        rbtn(self, "Удалить выбранное", command=self.delete_selected, kind="danger").pack(anchor="w", pady=8)

        self._reload_categories()

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
        self.app.db.add_recurring(self.type_var.get(), amount, cat_id, day, self.note_var.get().strip())
        self.amount_var.set("")
        self.note_var.set("")
        self.app.refresh_all()

    def delete_selected(self):
        sel = self.tree.selection()
        if sel and messagebox.askyesno("Удаление", "Удалить регулярный платёж?"):
            self.app.db.delete_recurring(int(sel[0]))
            self.app.refresh_all()

    def refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for r in self.app.db.get_recurring():
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                "Доход" if r["type"] == "income" else "Расход", fmt_money(r["amount"]), r["day_of_month"],
                r["category_name"] or "—", r["note"] or ""
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
                  font=("Georgia", 12, "bold")).pack(anchor="w", pady=(0, 6))
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
            ttk.Label(row, text=f, style="Card.TLabel", font=("Consolas", 9)).pack(side="left")
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
        ttk.Label(nav, textvariable=self.year_var, font=("Consolas", 12),
                  background=BG, foreground=INK_DIM, width=10, anchor="center").pack(side="left", padx=8)
        icon_button(nav, "▶", command=lambda: self.change_year(1), kind="ghost").pack(side="left")

        # сводка за год
        self.summary_frame = tk.Frame(outer, bg=BG)
        self.summary_frame.pack(fill="x", pady=(0, 10))

        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        # расходы по категориям за год
        self.category_card = RoundedCard(body, radius=16)
        self.category_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=6)
        ttk.Label(self.category_card.body, text="Расходы по категориям за год", style="Card.TLabel",
                  font=("Georgia", 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.category_rows = tk.Frame(self.category_card.body, bg=SURFACE)
        self.category_rows.pack(fill="both", expand=True)

        # круговая диаграмма за год
        pie_card = RoundedCard(body, radius=16)
        pie_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=6)
        ttk.Label(pie_card.body, text="Доля расходов за год", style="Card.TLabel",
                  font=("Georgia", 12, "bold")).pack(anchor="w")
        self.pie_fig = Figure(figsize=(4, 3), dpi=90, facecolor=SURFACE)
        self.pie_ax = self.pie_fig.add_subplot(111)
        self.pie_canvas = FigureCanvasTkAgg(self.pie_fig, master=pie_card.body)
        self.pie_canvas.get_tk_widget().pack(fill="both", expand=True)

        # доходы/расходы по месяцам за весь год
        chart_card = RoundedCard(outer, radius=16)
        chart_card.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(chart_card.body, text="Доходы и расходы по месяцам", style="Card.TLabel",
                  font=("Georgia", 12, "bold")).pack(anchor="w")
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
            ("💰", "Доход за год", income, INCOME),
            ("💸", "Расход за год", expense, EXPENSE),
            ("⚖", "Баланс за год", balance, GOLD if balance >= 0 else DANGER),
            ("📊", "Средний расход в месяц", expense / 12, INK_DIM),
        ]
        for i, (icon, label, value, color) in enumerate(cards):
            card = RoundedCard(self.summary_frame, radius=16, pad=14)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.summary_frame.columnconfigure(i, weight=1)
            head = tk.Frame(card.body, bg=SURFACE)
            head.pack(anchor="w", fill="x")
            ttk.Label(head, text=icon, background=SURFACE, font=("Segoe UI", 12)).pack(side="left", padx=(0, 6))
            ttk.Label(head, text=label, style="Card.TLabel", foreground=INK_DIM,
                      font=("Segoe UI", 9)).pack(side="left")
            ttk.Label(card.body, text=fmt_money(value), background=SURFACE, foreground=color,
                      font=("Consolas", 15, "bold")).pack(anchor="w", pady=(4, 0))

        # расходы по категориям за год
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
                      foreground=INK_DIM, font=("Consolas", 9)).pack(side="right")
            make_bar(row, spent, expense if expense > 0 else 1, c["color"], width=280, height=7).pack(
                fill="x", pady=(4, 0))

        # круговая диаграмма
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

        # доходы/расходы по месяцам за год
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
# Главное окно
# =================================================================

class FinanceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Мои финансы")
        self.geometry("1040x700")
        self.minsize(900, 600)
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

    def receipts_dir(self):
        return os.path.join(self.receipts_base_dir, "receipts")

    def _set_app_icon(self):
        """Заменяет стандартную иконку Tk на иконку приложения (icon.ico)."""
        icon_path = resource_path("icon.ico")
        try:
            if os.path.exists(icon_path):
                self.iconbitmap(default=icon_path)
        except tk.TclError:
            # На некоторых платформах (не Windows) iconbitmap может не принимать .ico —
            # это не критично, приложение продолжает работать со стандартной иконкой.
            pass

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=INK, fieldbackground=SURFACE2,
                        font=("Segoe UI", 10), borderwidth=0)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Card.TLabel", background=SURFACE, foreground=INK)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=SURFACE, foreground=INK_DIM,
                        padding=(16, 10), font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", SURFACE2)], foreground=[("selected", INK)])
        style.configure("TButton", background=GOLD, foreground=BG, padding=8,
                        font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.map("TButton", background=[("active", "#E0B96E")])
        style.configure("Ghost.TButton", background=SURFACE2, foreground=INK_DIM, padding=8, borderwidth=0)
        style.map("Ghost.TButton", background=[("active", SURFACE2)], foreground=[("active", INK)])
        style.configure("Danger.TButton", background=DANGER, foreground="white", padding=6, borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#E06A5C")])
        style.configure("TEntry", fieldbackground=SURFACE2, foreground=INK, insertcolor=INK, borderwidth=0)
        style.configure("TCombobox", fieldbackground=SURFACE2, foreground=INK, background=SURFACE2, arrowcolor=INK)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE2)])
        style.configure("Treeview", background=SURFACE2, fieldbackground=SURFACE2, foreground=INK,
                        rowheight=26, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background=SURFACE, foreground=INK_DIM,
                        font=("Segoe UI", 9, "bold"), borderwidth=0)
        style.map("Treeview", background=[("selected", GOLD)], foreground=[("selected", BG)])

    def _build_layout(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=20, pady=(16, 8))
        ttk.Label(header, text="Мои финансы", font=("Georgia", 20, "bold"),
                  background=BG, foreground=INK).pack(side="left")

        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x", padx=20, pady=(0, 10))
        icon_button(nav, "◀", command=lambda: self.change_month(-1), kind="ghost").pack(side="left")
        self.month_var = tk.StringVar(value=month_label(self.current_month))
        ttk.Label(nav, textvariable=self.month_var, font=("Consolas", 12),
                  background=BG, foreground=INK_DIM, width=20, anchor="center").pack(side="left", padx=8)
        icon_button(nav, "▶", command=lambda: self.change_month(1), kind="ghost").pack(side="left")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self.tab_dashboard = DashboardTab(self.notebook, self)
        self.tab_transactions = TransactionsTab(self.notebook, self)
        self.tab_categories = CategoriesTab(self.notebook, self)
        self.tab_savings = SavingsTab(self.notebook, self)
        self.tab_recurring = RecurringTab(self.notebook, self)
        self.tab_receipts = ReceiptsTab(self.notebook, self)
        self.tab_yearreport = YearReportTab(self.notebook, self)

        self.notebook.add(self.tab_dashboard, text="  Дашборд  ")
        self.notebook.add(self.tab_transactions, text="  Операции  ")
        self.notebook.add(self.tab_categories, text="  Категории  ")
        self.notebook.add(self.tab_savings, text="  Копилки  ")
        self.notebook.add(self.tab_recurring, text="  Регулярные платежи  ")
        self.notebook.add(self.tab_receipts, text="  Чеки  ")
        self.notebook.add(self.tab_yearreport, text="  Годовой отчёт  ")

    def change_month(self, delta):
        self.current_month = shift_month(self.current_month, delta)
        self.month_var.set(month_label(self.current_month))
        self.refresh_all()

    def refresh_all(self):
        self.tab_dashboard.refresh()
        self.tab_transactions.refresh()
        self.tab_categories.refresh()
        self.tab_savings.refresh()
        self.tab_recurring.refresh()
        self.tab_receipts.refresh()
        self.tab_yearreport.refresh()


if __name__ == "__main__":
    app = FinanceApp()
    app.mainloop()
