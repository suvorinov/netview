"""Общие утилиты NetView.

Функции, которые используются и в маршрутах, и в шаблонных фильтрах:
форматирование размеров и сортировка списков словарей.
"""

from typing import Any


def human_size(b: Any) -> str:
    """Преобразовать размер в байтах в человекочитаемый вид.

    Args:
        b: Размер в байтах (число или строка).

    Returns:
        Строка вида "512 B", "3.4 MB". Для некорректных значений —
        исходная строка.
    """
    if b is None:
        return "—"
    try:
        b = int(b)
    except (TypeError, ValueError):
        return str(b)
    if b < 0:
        return str(b)
    if b < 1024:
        return f"{b} B"
    for unit in ("KB", "MB", "GB", "TB", "PB"):
        b /= 1024
        if b < 1024:
            if b >= 100:
                return f"{b:.0f} {unit}"
            return f"{b:.1f} {unit}"
    return f"{b:.1f} EB"


def format_duration(seconds: Any) -> str:
    """Преобразовать длительность в секундах в "м:сс" или "ч:мм:сс".

    Args:
        seconds: Длительность в секундах (число или строка).

    Returns:
        Строка вида "2:30" или "1:05:12". Для некорректных значений — "—".
    """
    if seconds is None:
        return "—"
    try:
        seconds = int(float(seconds))
    except (TypeError, ValueError):
        return "—"
    if seconds < 0:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _is_number(value: Any) -> bool:
    """Проверить, что строка является числом (например, "75.5")."""
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def sort_items(
    items: list[dict[str, Any]],
    sort_by: str,
    order: str = "asc",
    sort_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Отсортировать список словарей по полю из карты сортировки.

    Числовые поля (включая числовые строки) сортируются как числа,
    остальные — как строки без учёта регистра. Неизвестное поле
    сортировки возвращает список без изменений. Пустые значения
    всегда уходят в конец списка (аналог NULLS LAST).

    Args:
        items: Список словарей.
        sort_by: Ключ из sort_map (например, "cpu").
        order: Направление: "asc" или "desc".
        sort_map: Словарь {ключ: поле в данных}.

    Returns:
        Отсортированный список.
    """
    field = (sort_map or {}).get(sort_by)
    if not field or not items:
        return items

    reverse = order == "desc"

    def raw(item: dict) -> Any:
        value = item.get(field)
        return value if value is not None else ""

    def is_empty(item: dict) -> bool:
        return raw(item) == ""

    # Пустые значения отсортировать нечем — отделяем их в конец.
    empty, non_empty = [], []
    for item in items:
        (empty if is_empty(item) else non_empty).append(item)
    if not non_empty:
        return items

    first = raw(non_empty[0])
    # Числовая сортировка: числа и числовые строки сравниваются как float.
    if isinstance(first, int | float) or (isinstance(first, str) and _is_number(first)):
        def num_key(item: dict) -> float:
            try:
                return float(raw(item))
            except (TypeError, ValueError):
                return 0.0

        return sorted(non_empty, key=num_key, reverse=reverse) + empty

    # Строковая сортировка: без учёта регистра.
    return sorted(
        non_empty, key=lambda i: str(raw(i)).lower(), reverse=reverse
    ) + empty
