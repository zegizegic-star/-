import sqlite3
import os
import sys
import shutil
import glob
from datetime import datetime

BACKUP_DIR_NAME = "backups"
MAX_BACKUPS = 5

DEFAULT_CATEGORIES = [
    ("Продукты", "expense", "#8FBF9F", 25000),
    ("Транспорт", "expense", "#D2A65A", 6000),
    ("Жильё", "expense", "#7C93AA", 30000),
    ("Развлечения", "expense", "#B98CA0", 8000),
    ("Здоровье", "expense", "#BD6357", 5000),
    ("Одежда", "expense", "#8AA9A5", 5000),
    ("Прочее", "expense", "#C9B458", 5000),
    ("Зарплата", "income", "#9C8AA5", 0),
    ("Подработка", "income", "#7FA3C0", 0),
    ("Прочий доход", "income", "#A78BFA", 0),
]


def get_base_dir():
    """Папка, где лежит exe (или скрипт при запуске из исходников) — туда же кладём базу данных."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DB_PATH = os.path.join(get_base_dir(), "finance_data.db")


def backup_database(db_path, keep=MAX_BACKUPS):
    """Создаёт резервную копию БД при запуске программы и хранит только последние `keep` копий.

    Работает и с путями, содержащими кириллицу (Python 3 обрабатывает такие
    пути как обычные Unicode-строки на всех платформах, включая Windows).
    Если базы ещё не существует (первый запуск) или копирование не удалось
    (нет прав, диск переполнен) — просто ничего не делает.
    """
    if not os.path.exists(db_path):
        return None
    base_dir = os.path.dirname(db_path)
    backup_dir = os.path.join(base_dir, BACKUP_DIR_NAME)
    db_name = os.path.splitext(os.path.basename(db_path))[0]
    try:
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"{db_name}_{stamp}.db")
        shutil.copy2(db_path, backup_path)
        _prune_old_backups(backup_dir, db_name, keep)
        return backup_path
    except OSError:
        return None


def _prune_old_backups(backup_dir, db_name, keep=MAX_BACKUPS):
    pattern = os.path.join(backup_dir, f"{db_name}_*.db")
    backups = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    for old_backup in backups[keep:]:
        try:
            os.remove(old_backup)
        except OSError:
            pass


class Database:
    def __init__(self, path=DB_PATH):
        self.path = path
        self.last_backup_path = backup_database(self.path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('expense','income')),
                color TEXT NOT NULL,
                limit_amount REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK(type IN ('expense','income')),
                amount REAL NOT NULL,
                category_id INTEGER,
                date TEXT NOT NULL,
                note TEXT DEFAULT '',
                FOREIGN KEY(category_id) REFERENCES categories(id)
            );
            CREATE TABLE IF NOT EXISTS savings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                target REAL NOT NULL,
                current REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS savings_contributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                savings_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                FOREIGN KEY(savings_id) REFERENCES savings(id)
            );
            CREATE TABLE IF NOT EXISTS recurring (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK(type IN ('expense','income')),
                amount REAL NOT NULL,
                category_id INTEGER,
                day_of_month INTEGER NOT NULL,
                note TEXT DEFAULT '',
                last_applied TEXT
            );
            """
        )
        self.conn.commit()
        cur.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            cur.executemany(
                "INSERT INTO categories (name, type, color, limit_amount) VALUES (?, ?, ?, ?)",
                DEFAULT_CATEGORIES,
            )
            self.conn.commit()

    # ---------------- categories ----------------
    def get_categories(self, type_=None):
        cur = self.conn.cursor()
        if type_:
            cur.execute("SELECT * FROM categories WHERE type=? ORDER BY name", (type_,))
        else:
            cur.execute("SELECT * FROM categories ORDER BY type, name")
        return cur.fetchall()

    def get_category(self, cat_id):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM categories WHERE id=?", (cat_id,))
        return cur.fetchone()

    def add_category(self, name, type_, color, limit_amount=0):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO categories (name, type, color, limit_amount) VALUES (?,?,?,?)",
            (name, type_, color, limit_amount),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_category(self, cat_id, name=None, color=None, limit_amount=None):
        cat = self.get_category(cat_id)
        if not cat:
            return
        name = name if name is not None else cat["name"]
        color = color if color is not None else cat["color"]
        limit_amount = limit_amount if limit_amount is not None else cat["limit_amount"]
        self.conn.execute(
            "UPDATE categories SET name=?, color=?, limit_amount=? WHERE id=?",
            (name, color, limit_amount, cat_id),
        )
        self.conn.commit()

    def delete_category(self, cat_id):
        self.conn.execute("UPDATE transactions SET category_id=NULL WHERE category_id=?", (cat_id,))
        self.conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        self.conn.commit()

    # ---------------- transactions ----------------
    def get_transactions(self, month=None, search=None, category_id=None):
        query = (
            "SELECT t.*, c.name as category_name, c.color as category_color "
            "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id WHERE 1=1"
        )
        params = []
        if month:
            query += " AND substr(t.date,1,7)=?"
            params.append(month)
        if search:
            query += " AND (t.note LIKE ? OR c.name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        if category_id:
            query += " AND t.category_id=?"
            params.append(category_id)
        query += " ORDER BY t.date DESC, t.id DESC"
        cur = self.conn.cursor()
        cur.execute(query, params)
        return cur.fetchall()

    def get_transaction(self, tx_id):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM transactions WHERE id=?", (tx_id,))
        return cur.fetchone()

    def add_transaction(self, type_, amount, category_id, date_, note=""):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO transactions (type, amount, category_id, date, note) VALUES (?,?,?,?,?)",
            (type_, amount, category_id, date_, note),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_transaction(self, tx_id, type_, amount, category_id, date_, note):
        self.conn.execute(
            "UPDATE transactions SET type=?, amount=?, category_id=?, date=?, note=? WHERE id=?",
            (type_, amount, category_id, date_, note, tx_id),
        )
        self.conn.commit()

    def delete_transaction(self, tx_id):
        self.conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
        self.conn.commit()

    def get_transactions_for_year(self, year):
        """Все операции за указанный год (используется годовым отчётом)."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT t.*, c.name as category_name, c.color as category_color "
            "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
            "WHERE substr(t.date,1,4)=? ORDER BY t.date",
            (str(year),),
        )
        return cur.fetchall()

    def all_transactions(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT t.*, c.name as category_name FROM transactions t "
            "LEFT JOIN categories c ON t.category_id=c.id ORDER BY t.date"
        )
        return cur.fetchall()

    # ---------------- savings ----------------
    def get_savings(self):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM savings ORDER BY id")
        return cur.fetchall()

    def add_saving(self, name, target):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO savings (name, target, current) VALUES (?,?,0)", (name, target))
        self.conn.commit()
        return cur.lastrowid

    def contribute_saving(self, saving_id, amount, date_):
        self.conn.execute("UPDATE savings SET current = current + ? WHERE id=?", (amount, saving_id))
        self.conn.execute(
            "INSERT INTO savings_contributions (savings_id, date, amount) VALUES (?,?,?)",
            (saving_id, date_, amount),
        )
        self.conn.commit()

    def update_saving(self, saving_id, name=None, target=None):
        cur = self.conn.execute("SELECT * FROM savings WHERE id=?", (saving_id,))
        row = cur.fetchone()
        if not row:
            return
        name = name if name is not None else row["name"]
        target = target if target is not None else row["target"]
        self.conn.execute("UPDATE savings SET name=?, target=? WHERE id=?", (name, target, saving_id))
        self.conn.commit()

    def delete_saving(self, saving_id):
        self.conn.execute("DELETE FROM savings WHERE id=?", (saving_id,))
        self.conn.execute("DELETE FROM savings_contributions WHERE savings_id=?", (saving_id,))
        self.conn.commit()

    # ---------------- recurring payments ----------------
    def get_recurring(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT r.*, c.name as category_name, c.color as category_color "
            "FROM recurring r LEFT JOIN categories c ON r.category_id=c.id ORDER BY r.day_of_month"
        )
        return cur.fetchall()

    def add_recurring(self, type_, amount, category_id, day_of_month, note=""):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO recurring (type, amount, category_id, day_of_month, note) VALUES (?,?,?,?,?)",
            (type_, amount, category_id, day_of_month, note),
        )
        self.conn.commit()
        return cur.lastrowid

    def delete_recurring(self, rec_id):
        self.conn.execute("DELETE FROM recurring WHERE id=?", (rec_id,))
        self.conn.commit()

    def mark_recurring_applied(self, rec_id, month):
        self.conn.execute("UPDATE recurring SET last_applied=? WHERE id=?", (month, rec_id))
        self.conn.commit()

    def apply_due_recurring(self, today_str):
        """Создаёт операции по регулярным платежам, наступившим в этом месяце и ещё не примененным."""
        month = today_str[:7]
        day = int(today_str[8:10])
        created = []
        for r in self.get_recurring():
            if r["last_applied"] == month:
                continue
            if day >= r["day_of_month"]:
                tx_date = f"{month}-{str(r['day_of_month']).zfill(2)}"
                self.add_transaction(
                    r["type"], r["amount"], r["category_id"], tx_date, r["note"] or "Регулярный платёж"
                )
                self.mark_recurring_applied(r["id"], month)
                created.append(r)
        return created

    def close(self):
        self.conn.close()
