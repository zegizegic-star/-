"""Необязательная проверка обновлений через GitHub Releases.

Работает, только когда в репозитории есть хотя бы один релиз с тегом
вида vX.Y.Z; если релизов ещё нет, нет интернета или GitHub недоступен —
тихо ничего не делает (никогда не мешает работе программы и не
скачивает/устанавливает ничего сама — только показывает ссылку).
"""

import requests

APP_VERSION = "1.4.0"
REPO = "zegizegic-star/-"


def _parse_version(v):
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_for_update(timeout=5):
    """Возвращает (новая_версия, url) если найден более новый релиз, иначе None.

    Никогда не бросает исключение наружу — любая сетевая или похожая
    проблема просто трактуется как «обновлений нет».
    """
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        tag = (data.get("tag_name") or "").lstrip("vV")
        url = data.get("html_url") or ""
        if not tag:
            return None
        if _parse_version(tag) > _parse_version(APP_VERSION):
            return tag, url
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError):
        pass
    return None
