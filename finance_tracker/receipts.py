"""Распознавание чеков через OpenAI (GPT).

Пользователь загружает фото чека — оно один раз, только в этот момент,
отправляется в OpenAI вместе с его собственным API-ключом, чтобы получить
сумму, дату, магазин и подходящую категорию. Всё остальное в программе
(операции, категории, копилки) по-прежнему хранится и обрабатывается
только локально.
"""

import base64
import io
import json
import os

import requests
from PIL import Image

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-5.6-sol"
MAX_IMAGE_SIDE = 1568  # с запасом хватает для чёткого чтения чека, но не раздувает запрос

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
    """Отправляет фото чека в OpenAI (GPT) и возвращает разобранные поля.

    category_names — список названий категорий пользователя (обычно расходных),
    чтобы модель выбирала строго из них и не придумывала новые.
    Возвращает dict: amount (float|None), date (str|None, YYYY-MM-DD),
    merchant (str), category (str, гарантированно из category_names или "Прочее"),
    note (str).
    Бросает ReceiptError с понятным русским сообщением при любой проблеме.
    """
    if not api_key:
        raise ReceiptError("Не указан API-ключ OpenAI. Откройте «Настройки распознавания» и вставьте ключ.")
    if not os.path.exists(image_path):
        raise ReceiptError("Файл изображения не найден.")

    media_type, image_b64 = _encode_image(image_path)

    categories_list = ", ".join(category_names) if category_names else "Прочее"
    prompt = (
        "Перед тобой фотография кассового чека из российского магазина или заведения. "
        "Извлеки из него данные о покупке и запиши их вызовом функции record_receipt.\n"
        f"Категория обязательно должна быть одной из этого списка (дословно): {categories_list}. "
        "Если ничего не подходит — выбери «Прочее», если оно есть в списке, иначе первую из списка.\n"
        "Сумму укажи как итоговую сумму к оплате (обычно строка «ИТОГ», «Итого» или «К оплате»), "
        "числом с точкой в качестве разделителя, без пробелов и знака валюты.\n"
        "Дату переведи в формат ГГГГ-ММ-ДД. Если дату разобрать не удалось — не указывай её."
    )

    tool_schema = {
        "type": "function",
        "function": {
            "name": "record_receipt",
            "description": "Записать данные, извлечённые из чека.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "Итоговая сумма чека"},
                    "date": {"type": "string", "description": "Дата покупки в формате ГГГГ-ММ-ДД, если распознана"},
                    "merchant": {"type": "string", "description": "Название магазина или заведения"},
                    "category": {"type": "string", "description": "Одна из предложенных категорий, дословно"},
                },
                "required": ["amount", "category"],
            },
        },
    }

    payload = {
        "model": model or DEFAULT_MODEL,
        "max_completion_tokens": 512,
        "tools": [tool_schema],
        "tool_choice": {"type": "function", "function": {"name": "record_receipt"}},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
                ],
            }
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=timeout)
    except requests.exceptions.Timeout:
        raise ReceiptError("Сервер не ответил вовремя. Проверьте интернет-соединение и попробуйте снова.")
    except requests.exceptions.RequestException as e:
        raise ReceiptError(f"Не удалось соединиться с сервером распознавания: {e}")

    if resp.status_code == 401:
        raise ReceiptError("Неверный API-ключ OpenAI. Проверьте его в «Настройках распознавания».")
    if resp.status_code == 429:
        raise ReceiptError("Превышен лимит запросов к API. Подождите немного и попробуйте снова.")
    if resp.status_code != 200:
        raise ReceiptError(f"Сервер вернул ошибку ({resp.status_code}): {resp.text[:300]}")

    try:
        data = resp.json()
    except ValueError:
        raise ReceiptError("Сервер вернул некорректный ответ.")

    try:
        tool_calls = data["choices"][0]["message"].get("tool_calls") or []
    except (KeyError, IndexError, TypeError):
        raise ReceiptError("Не удалось разобрать чек — модель вернула неожиданный ответ.")

    tool_call = next((c for c in tool_calls if c.get("function", {}).get("name") == "record_receipt"), None)
    if not tool_call:
        raise ReceiptError("Не удалось разобрать чек — модель не вернула структурированный ответ.")

    try:
        fields = json.loads(tool_call["function"]["arguments"])
    except (KeyError, ValueError):
        raise ReceiptError("Не удалось разобрать чек — не получилось прочитать ответ модели.")

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
