"""Разбор выписки банка (CSV/Excel) для массового импорта операций.

Работает полностью локально — файл нигде не отправляется. Пытается
угадать колонки с датой, суммой и описанием по заголовку; если не
получилось, вызывающий код (диалог импорта в app.py) должен спросить
пользователя явно и передать номера колонок.
"""

import csv
import os
from datetime import datetime

try:
    import openpyxl

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

DATE_HEADER_HINTS = ["дата операции", "дата платежа", "дата", "date"]
AMOUNT_HEADER_HINTS = [
    "сумма в валюте счёта", "сумма операции", "сумма платежа", "сумма", "amount",
]
NOTE_HEADER_HINTS = [
    "описание", "назначение платежа", "назначение", "комментарий",
    "категория", "операция", "note", "description",
]

DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y", "%Y/%m/%d"]


class BankImportError(Exception):
    """Ошибка разбора файла — сообщение уже готово для показа пользователю."""


def read_table(path):
    """Возвращает (заголовки, строки) — все ячейки как строки."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        if not HAS_OPENPYXL:
            raise BankImportError("Для чтения .xlsx нужен пакет openpyxl.")
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows = [[("" if c is None else str(c)) for c in row] for row in ws.iter_rows(values_only=True)]
            wb.close()
        except Exception as e:
            raise BankImportError(f"Не удалось прочитать Excel-файл: {e}")
    else:
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
                except csv.Error:
                    dialect = csv.excel
                    dialect.delimiter = ";" if sample.count(";") >= sample.count(",") else ","
                rows = list(csv.reader(f, dialect))
        except OSError as e:
            raise BankImportError(f"Не удалось открыть файл: {e}")

    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        raise BankImportError("Файл пуст или не удалось его прочитать.")
    return rows[0], rows[1:]


def guess_column(headers, hints):
    lowered = [(h or "").strip().lower() for h in headers]
    for hint in hints:
        for i, h in enumerate(lowered):
            if hint in h:
                return i
    return None


def parse_amount(raw):
    s = str(raw).strip().replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    s = s.replace(",", ".")
    s = "".join(ch for ch in s if ch.isdigit() or ch in ".-")
    if not s or s in ("-", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(raw):
    s = str(raw).strip().split(" ")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def guess_columns(headers):
    """Возвращает (date_col, amount_col, note_col) — любой может быть None."""
    return (
        guess_column(headers, DATE_HEADER_HINTS),
        guess_column(headers, AMOUNT_HEADER_HINTS),
        guess_column(headers, NOTE_HEADER_HINTS),
    )


def parse_rows(rows, date_col, amount_col, note_col):
    """Разбирает уже прочитанные строки по заданным номерам колонок."""
    if date_col is None or amount_col is None:
        raise BankImportError("Не выбраны колонки с датой и суммой.")
    parsed = []
    skipped = 0
    for row in rows:
        if date_col >= len(row) or amount_col >= len(row):
            skipped += 1
            continue
        date_val = parse_date(row[date_col])
        amount_val = parse_amount(row[amount_col])
        if date_val is None or amount_val is None or amount_val == 0:
            skipped += 1
            continue
        note_val = row[note_col].strip() if note_col is not None and note_col < len(row) else ""
        parsed.append({"date": date_val, "amount": amount_val, "note": note_val})
    if not parsed:
        raise BankImportError("Не удалось разобрать ни одной операции — проверьте выбранные колонки.")
    return parsed, skipped
