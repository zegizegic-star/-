"""Локальная защита запуска PIN-кодом.

Это не настоящая криптографическая защита данных — любой, у кого есть
физический доступ к файлам программы, может удалить app_lock.json и
снять PIN, либо открыть finance_data.db напрямую любым просмотрщиком
SQLite. PIN — это просто барьер от случайного взгляда постороннего,
взявшего в руки ваш компьютер, а не шифрование. Файл finance_data.db
самими данными не шифруется.

Если забыли PIN: удалите файл app_lock.json рядом с программой —
восстановления по email/телефону здесь нет, это не онлайн-сервис.
"""

import hashlib
import hmac
import json
import os
import secrets

LOCK_FILE_NAME = "app_lock.json"


def _lock_path(base_dir):
    return os.path.join(base_dir, LOCK_FILE_NAME)


def is_enabled(base_dir):
    return os.path.exists(_lock_path(base_dir))


def _hash_pin(pin, salt):
    return hashlib.sha256((salt + pin).encode("utf-8")).hexdigest()


def set_pin(base_dir, pin):
    salt = secrets.token_hex(16)
    data = {"salt": salt, "hash": _hash_pin(pin, salt)}
    with open(_lock_path(base_dir), "w", encoding="utf-8") as f:
        json.dump(data, f)


def check_pin(base_dir, pin):
    path = _lock_path(base_dir)
    if not os.path.exists(path):
        return True
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return True
    expected = data.get("hash", "")
    actual = _hash_pin(pin, data.get("salt", ""))
    return hmac.compare_digest(expected, actual)


def remove_pin(base_dir):
    path = _lock_path(base_dir)
    if os.path.exists(path):
        os.remove(path)
