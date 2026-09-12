"""Распознавание чеков через Claude API (Anthropic).

Пользователь загружает фото чека — оно один раз, только в этот момент,
отправляется в Anthropic вместе с его собственным API-ключом, чтобы
получить сумму, дату, магазин и подходящую категорию. Всё остальное
в программе (операции, категории, копилки) по-прежнему хранится и
обрабатывается только локально.
"""

import base64
import io
import json
import os

import requests
from PIL import Image

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"
MAX_IMAGE_SIDE = 1568  # рекомендация Anthropic для оптимального баланса качества/цены

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


class ReceiptError(Exception):
    """Ошибка распознавания чека — сообщение уже готово для показа пользователю."""


def get_config_path(base_dir):
    return os.path.join(base_dir, "receipt_config.json")


def load_config(base_dir):
    path = get_config_path(base_dir)
    if not os.path.exists(path):
        return {"api_key": "", "model": DEFAULT_MODEL}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"api_key": "", "model": DEFAULT_MODEL}
    return {
        "api_key": data.get("api_key", ""),
        "model": data.get("model") or DEFAULT_MODEL,
    }


def save_config(base_dir, api_key, model):
    path = get_config_path(base_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"api_key": api_key.strip(), "model": (model or DEFAULT_MODEL).strip()}, f, ensure_ascii=False)


def _encode_image(image_path):
    """Уменьшает фото при необходимости и кодирует его в base64 (JPEG)."""
    try:
        img = Image.open(image_path)
        img = img.convert("RGB")
    except Exception as e:
        raise ReceiptError(f"Не удалось открыть изображение: {e}")

    w, h = img.size
    longest = max(w, h)
    if longest > MAX_IMAGE_SIDE:
        scale = MAX_IMAGE_SIDE / longest
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    return "image/jpeg", data


def analyze_receipt(image_path, category_names, api_key, model=None, timeout=60):
    """Отправляет фото чека в Claude и возвращает разобранные поля.

    category_names — список названий категорий пользователя (обычно расходных),
    чтобы модель выбирала строго из них и не придумывала новые.
    Возвращает dict: amount (float|None), date (str|None, YYYY-MM-DD),
    merchant (str), category (str, гарантированно из category_names или "Прочее"),
    note (str).
    Бросает ReceiptError с понятным русским сообщением при любой проблеме.
    """
    if not api_key:
        raise ReceiptError("Не указан API-ключ Anthropic. Откройте «Настройки распознавания» и вставьте ключ.")
    if not os.path.exists(image_path):
        raise ReceiptError("Файл изображения не найден.")

    media_type, image_b64 = _encode_image(image_path)

    categories_list = ", ".join(category_names) if category_names else "Прочее"
    prompt = (
        "Перед тобой фотография кассового чека из российского магазина или заведения. "
        "Извлеки из него данные о покупке и запиши их вызовом инструмента record_receipt.\n"
        f"Категория обязательно должна быть одной из этого списка (дословно): {categories_list}. "
        "Если ничего не подходит — выбери «Прочее», если оно есть в списке, иначе первую из списка.\n"
        "Сумму укажи как итоговую сумму к оплате (обычно строка «ИТОГ», «Итого» или «К оплате»), "
        "числом с точкой в качестве разделителя, без пробелов и знака валюты.\n"
        "Дату переведи в формат ГГГГ-ММ-ДД. Если дату разобрать не удалось — не указывай её."
    )

    tool_schema = {
        "name": "record_receipt",
        "description": "Записать данные, извлечённые из чека.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Итоговая сумма чека"},
                "date": {"type": "string", "description": "Дата покупки в формате ГГГГ-ММ-ДД, если распознана"},
                "merchant": {"type": "string", "description": "Название магазина или заведения"},
                "category": {"type": "string", "description": "Одна из предложенных категорий, дословно"},
            },
            "required": ["amount", "category"],
        },
    }

    payload = {
        "model": model or DEFAULT_MODEL,
        "max_tokens": 512,
        "tools": [tool_schema],
        "tool_choice": {"type": "tool", "name": "record_receipt"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=timeout)
    except requests.exceptions.Timeout:
        raise ReceiptError("Сервер не ответил вовремя. Проверьте интернет-соединение и попробуйте снова.")
    except requests.exceptions.RequestException as e:
        raise ReceiptError(f"Не удалось соединиться с сервером распознавания: {e}")

    if resp.status_code == 401:
        raise ReceiptError("Неверный API-ключ Anthropic. Проверьте его в «Настройках распознавания».")
    if resp.status_code == 429:
        raise ReceiptError("Превышен лимит запросов к API. Подождите немного и попробуйте снова.")
    if resp.status_code != 200:
        raise ReceiptError(f"Сервер вернул ошибку ({resp.status_code}): {resp.text[:300]}")

    try:
        data = resp.json()
    except ValueError:
        raise ReceiptError("Сервер вернул некорректный ответ.")

    tool_use = next((b for b in data.get("content", []) if b.get("type") == "tool_use"), None)
    if not tool_use:
        raise ReceiptError("Не удалось разобрать чек — модель не вернула структурированный ответ.")

    fields = tool_use.get("input", {})
    amount = fields.get("amount")
    try:
        amount = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount = None

    category = fields.get("category") or ""
    if category_names and category not in category_names:
        category = "Прочее" if "Прочее" in category_names else category_names[0]

    date_str = fields.get("date") or None
    merchant = (fields.get("merchant") or "").strip()

    return {
        "amount": amount,
        "date": date_str,
        "merchant": merchant,
        "category": category,
        "note": merchant,
    }
