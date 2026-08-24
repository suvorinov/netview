"""Общие утилиты NetView.

Функции, которые используются и в маршрутах, и в шаблонных фильтрах:
форматирование размеров и сортировка списков словарей.
"""

from datetime import UTC, datetime, timedelta
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


# Маркеры вендоров, которые производят сетевое оборудование
# (домашние роутеры, точки доступа, коммутаторы). ASUSTek — отдельно:
# их материнские платы массово стоят в ПК, поэтому помечаются только
# при неразрешённом hostname (вероятный роутер ASUS, а не ПК).
ROUTER_VENDOR_MARKERS: tuple[str, ...] = (
    "TP-LINK", "D-LINK", "MERCUSYS", "XIAOMI", "ROUTERBOARD",
    "MIKROTIK", "HUAWEI", "ZYXEL", "TENDA", "NETGEAR", "UBIQUITI",
    "EDIMAX", "SAGEMCOM", "H3C", "ARUBA", "CISCO",
)

UNKNOWN_HOSTNAME = "Неизвестное устройство"


def is_router_vendor(vendor: str, hostname_unknown: bool = False) -> bool:
    """Производитель ли это сетевого оборудования (вероятный роутер/AP).

    Args:
        vendor: Название производителя из NetCerber.
        hostname_unknown: hostname устройства не разрешился
            ("Неизвестное устройство").

    Returns:
        True, если вендор входит в список производителей сетевого
        оборудования. ASUSTek — только при неразрешённом hostname
        (иначе это почти наверняка материнская плата ПК).
    """
    v = (vendor or "").upper()
    if "ASUSTEK" in v:
        return hostname_unknown
    return any(m in v for m in ROUTER_VENDOR_MARKERS)


def is_unknown_device(device: dict[str, Any]) -> bool:
    """Устройство без разрешённого hostname (не нашлось в DNS/AD)."""
    hostname = (device.get("hostname") or "").strip()
    return not hostname or hostname == UNKNOWN_HOSTNAME


def is_new_device(device: dict[str, Any], days: int = 7) -> bool:
    """Устройство, впервые обнаруженное за последние N дней.

    Args:
        device: Данные устройства NetCerber (поле first_seen ISO-8601).
        days: Окно «новизны» в днях.

    Returns:
        True, если first_seen не старше days дней.
    """
    first_seen = device.get("first_seen")
    if not first_seen:
        return False
    try:
        seen = datetime.fromisoformat(str(first_seen))
    except ValueError:
        return False
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    return seen >= datetime.now(UTC) - timedelta(days=days)


def ip_to_int(ip: Any) -> int | None:
    """IPv4-адрес в целое число для сравнения диапазонов.

    Returns:
        Числовое представление или None, если адрес некорректен.
    """
    try:
        parts = [int(p) for p in str(ip).split(".")]
    except (TypeError, ValueError):
        return None
    if len(parts) != 4 or any(not 0 <= p <= 255 for p in parts):
        return None
    return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]


def parse_dhcp_pool(value: str | None) -> tuple[str, str] | None:
    """Разобрать конфиг DHCP-пула "start,end" в пару адресов.

    Returns:
        (начало, конец) или None, если диапазон не задан/некорректен.
    """
    if not value:
        return None
    try:
        start, end = (part.strip() for part in str(value).split(","))
    except ValueError:
        return None
    if ip_to_int(start) is None or ip_to_int(end) is None:
        return None
    return start, end


def is_in_dhcp_pool(ip: Any, pool: tuple[str, str] | None) -> bool:
    """IP-адрес входит в диапазон DHCP-пула.

    Args:
        ip: IP-адрес устройства.
        pool: (начало, конец) пула или None (признак выключен).

    Returns:
        True, если адрес внутри диапазона.
    """
    if not pool:
        return False
    value = ip_to_int(ip)
    start = ip_to_int(pool[0])
    end = ip_to_int(pool[1])
    if value is None or start is None or end is None:
        return False
    return start <= value <= end


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

    Note:
        Тип колонки определяется по ПЕРВОМУ непустому значению.
        Если в колонке смешаны типы (например, числа и строки
        "N/A"), вся колонка сортируется как строки. Для таблиц
        панели это приемлемо: значения внутри колонок однородны.

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
