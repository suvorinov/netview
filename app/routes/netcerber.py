"""Маршруты NetCerber — мониторинг устройств локальной сети.

Модуль содержит маршруты для просмотра устройств, управления
авторизацией, журнала сканирований и оповещений NetCerber.
"""

import logging
import re
import time
from datetime import datetime

from flask import Blueprint, Response, current_app, render_template, request
from requests import RequestException

from app.api.factories import get_logspy_client, get_netcerber_client
from app.api.opnsense import OPNsenseClient, OPNsenseError
from app.utils import (
    group_devices_by_ip,
    ip_to_int,
    is_in_dhcp_pool,
    is_new_device,
    is_protected_mac,
    is_router_vendor,
    is_unknown_device,
    is_vendor_mismatch,
    normalize_mac,
    parse_dhcp_pool,
    parse_mac_list,
    sort_items,
)

netcerber_bp = Blueprint("netcerber", __name__)

logger = logging.getLogger(__name__)

SORT_FIELDS: dict[str, str] = {
    "ip": "ip_address",
    "hostname": "hostname",
    "vendor": "vendor",
    "last_seen": "last_seen",
    "first_seen": "first_seen",
}

# Категории подозрительности для фильтра-чипов
CATEGORIES: dict[str, str] = {
    "router": "Сетевое оборудование?",
    "new": "Новые (7 дней)",
    "unknown": "Неизвестные",
    "dhcp": "В DHCP-пуле",
    "mismatch": "Расхождение данных",
    "dupes": "Дубли по IP",
}

# TTL кэша счётчиков чипов (секунды). Числа в фильтрах спокойно живут
# с лагом в десятки секунд, а кэш экономит повторную полную выборку
# устройств при каждом действии со списком.
_COUNTS_CACHE_TTL = 30.0


def _get_dhcp_pool() -> tuple[str, str] | None:
    """Диапазон DHCP-пула из конфигурации."""
    return parse_dhcp_pool(current_app.config.get("DHCP_POOL"))


def _as_bool(value: str | None) -> bool | None:
    """Преобразовать строку из query-параметра в bool.

    Flask-конвертер type=bool работает через bool("false") == True,
    поэтому разбираем вручную.
    """
    if value is None:
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


def _as_int(value: str | None, default: int) -> int:
    """Целое число из query-параметра; мусор заменяется значением по умолчанию.

    int("abc") бросает ValueError — без обёртки мусор в skip/limit
    ронял страницу с 500.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_ad(ip_address: str | None) -> dict | None:
    """Сопоставить IP с компьютером/пользователем AD (через LogSpy).

    Returns:
        {"username", "computer_name", "source"} или None, если
        сопоставление не найдено или сервис недоступен.
    """
    if not ip_address:
        return None
    try:
        return get_logspy_client().ad_resolve_ip(ip_address)
    except RequestException as e:
        # 404 — штатный ответ «этот IP не из AD», а не сбой: молча
        # в debug, чтобы не засорять журнал при каждом открытии
        # модалки для устройств вне домена.
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 404:
            logger.debug("AD resolve %s: нет сопоставления в AD", ip_address)
        else:
            logger.info("LogSpy AD resolve (%s): %s", ip_address, e)
        return None


def _scheduler_status() -> dict:
    """Статус планировщика автосканирований NetCerber.

    Добавляет interval_hours — интервал из trigger-строки
    "interval[5:00:00]" в часах (для поля формы).
    """
    try:
        status = get_netcerber_client().scheduler_status()
    except RequestException as e:
        logger.error("NetCerber API (scheduler status) error: %s", e)
        return {}
    trigger = (status.get("job") or {}).get("trigger") or ""
    m = re.fullmatch(r"interval\[(\d+):(\d+):(\d+)\]", trigger)
    if m:
        h, mi, s = (int(x) for x in m.groups())
        status["interval_hours"] = round(h + mi / 60 + s / 3600, 2)
    return status


def _device_flags(device: dict, pool: tuple[str, str] | None = None) -> dict[str, bool]:
    """Признаки подозрительности устройства.

    Возвращает словарь {router, new, unknown, dhcp, mismatch} для
    отрисовки бейджей. Признаки router и mismatch взаимоисключающие:
    «роутерный вендор + разрешённое имя ПК» — это не сетевое
    оборудование, а рассинхрон записи (IP переехал на другой хост),
    поэтому такое устройство помечается mismatch и не попадает
    в счётчик роутеров — чипы не задваиваются.
    """
    unknown = is_unknown_device(device)
    mismatch = is_vendor_mismatch(device.get("vendor", ""), not unknown)
    return {
        "router": is_router_vendor(device.get("vendor", ""), unknown)
        and not mismatch,
        "new": is_new_device(device),
        "unknown": unknown,
        "dhcp": is_in_dhcp_pool(device.get("ip_address"), pool),
        "mismatch": mismatch,
    }


def _enrich(
    devices: list[dict],
    pool: tuple[str, str] | None = None,
    blocked_macs: set[str] | None = None,
) -> list[dict]:
    """Добавить каждому устройству вычисленные признаки (_flags).

    Args:
        devices: Сырые записи NetCerber.
        pool: DHCP-пул для признака «В DHCP-пуле».
        blocked_macs: Множество hex-MAC, заблокированных на шлюзе
            (из _opnsense_blocked_macs). Пусто/None = бейдж блокировки
            не показывается.
    """
    blocked_macs = blocked_macs or set()
    for d in devices:
        flags = _device_flags(d, pool)
        flags["blocked"] = _proto_hex_mac(d.get("mac_address")) in blocked_macs
        d["_flags"] = flags
    return devices


def _device_counts(devices: list[dict], pool: tuple[str, str] | None = None) -> dict[str, int]:
    """Счётчики категорий подозрительности для чипов-фильтров.

    Ожидает сгруппированные записи (group_devices_by_ip): флаги
    считаются по первичным записям, "dupes" — число скрытых
    устаревших записей-дублей.
    """
    counts = {
        "router": 0, "new": 0, "unknown": 0,
        "dhcp": 0, "mismatch": 0, "dupes": 0,
    }
    for d in devices:
        counts["dupes"] += len(d.get("_history", []))
        flags = d.get("_flags") or _device_flags(d, pool)
        for key in counts:
            if key != "dupes" and flags.get(key):
                counts[key] += 1
    return counts


def _match_category(device: dict, category: str) -> bool:
    """Совпадает ли устройство с категорией фильтра."""
    if not category:
        return True
    if category == "dupes":
        # Отдельная категория: у записи есть история (дубли по IP)
        return bool(device.get("_history"))
    flags = device.get("_flags") or _device_flags(device)
    return bool(flags.get(category))


def _matches_query(device: dict, query: str) -> bool:
    """Поиск по подстроке в IP, MAC, hostname или вендоре."""
    q = query.strip().lower()
    if not q:
        return True
    fields = (
        device.get("ip_address", ""),
        device.get("mac_address", ""),
        device.get("hostname", ""),
        device.get("vendor", ""),
    )
    return any(q in str(f).lower() for f in fields)


def _list_filters(
    values: dict | None = None,
) -> dict:
    """Параметры списка устройств (из query или формы модалки).

    Передаются сквозь все запросы, чтобы после авторизации устройства
    список оставался в том же виде (фильтр, поиск, сортировка).
    """
    values = values or {}
    dupes = str(values.get("dupes", "")).strip().lower()
    return {
        "authorized": _as_bool(values.get("authorized")),
        "unauthorized": _as_bool(values.get("unauthorized")),
        "cat": (values.get("cat") or "").strip(),
        "q": (values.get("q") or "").strip(),
        "sort_by": values.get("sort", "first_seen"),
        "order": values.get("order", "desc"),
        "skip": _as_int(values.get("skip"), 0),
        "limit": _as_int(values.get("limit"), 100),
        # Показывать устаревшие записи-дубли отдельными строками
        "dupes": dupes in ("1", "show", "true", "yes"),
    }


def _load_devices(filters: dict) -> tuple[list[dict], int]:
    """Устройства с признаками подозрительности по параметрам списка.

    Args:
        filters: Результат _list_filters().

    Returns:
        (список устройств, число отображённых записей).

    Записи группируются по IP: первичная — свежайшая, остальные
    уходят в "_history" и по умолчанию скрыты (dupes=False показывают
    только первичные; True разворачивает историю тусклыми строками
    под своей первичной записью).

    При активном фильтре категории или поиске выборка берётся целиком
    (limit=500), чтобы total и пагинация были честными.
    """
    client = get_netcerber_client()
    pool = _get_dhcp_pool()
    full_scan = bool(filters["cat"] or filters["q"])
    data = client.get_devices(
        authorized=filters["authorized"],
        unauthorized=filters["unauthorized"],
        sort_by=filters["sort_by"] or None,
        skip=0 if full_scan else filters["skip"],
        limit=500 if full_scan else filters["limit"],
    )
    devices = group_devices_by_ip(
        _enrich(data.get("items", []), pool, _opnsense_blocked_macs())
    )
    devices = [d for d in devices if _match_category(d, filters["cat"])]
    devices = [d for d in devices if _matches_query(d, filters["q"])]
    devices = sort_items(
        devices, filters["sort_by"], filters["order"], SORT_FIELDS
    )

    # "_history" остаётся на первичной записи: по нему шаблон рисует
    # бейдж «×N записей» и кнопку чистки. При dupes=True история
    # дополнительно разворачивается тусклыми строками под первичной;
    # помечаем копии записей (_stale), чтобы не мутировать данные API.
    rows: list[dict] = []
    for device in devices:
        rows.append(device)
        if filters["dupes"]:
            for stale in device.get("_history", []):
                marked = dict(stale)
                marked["_stale"] = True
                rows.append(marked)
    # total считаем от отображаемого набора: после группировки он не
    # совпадает с числом записей API.
    return rows, len(rows)


def _device_counts_all() -> dict[str, int]:
    """Счётчики категорий подозрительности по всем устройствам.

    Отдельный запрос полной выборки — чипы должны показывать
    реальные числа, а не только по загруженной странице списка.

    Результат кэшируется на короткий TTL в состоянии приложения:
    одно действие пользователя (например, авторизация в модалке)
    запрашивает список и счётчики вместе, и без кэша устройства
    выгружались бы из API дважды. Кэш хранится в app.extensions —
    у каждого экземпляра приложения (в том числе в тестах) он свой.
    """
    cache = current_app.extensions.setdefault("netcerber_counts", {})
    now = time.monotonic()
    counts = cache.get("counts")
    if counts is not None and now - cache.get("ts", 0.0) < _COUNTS_CACHE_TTL:
        return counts
    try:
        data = get_netcerber_client().get_devices(limit=500)
        grouped = group_devices_by_ip(_enrich(data.get("items", []), _get_dhcp_pool()))
        counts = _device_counts(grouped)
    except RequestException as e:
        logger.error("NetCerber API (devices counts) error: %s", e)
        return {
            "router": 0, "new": 0, "unknown": 0,
            "dhcp": 0, "mismatch": 0, "dupes": 0,
        }
    cache["counts"] = counts
    cache["ts"] = now
    return counts


def _reload_list_context(filters: dict) -> tuple[list[dict], int, dict, list[str]]:
    """Перезагрузить список устройств после операции блокировки.

    Возвращает (devices, total, counts, unavailable_services) для
    oob-обновления #device-list: бейджи «Заблокировано» и счётчики
    показывают актуальное состояние шлюза без перезагрузки страницы.
    При ошибке NetCerber возвращает пустые структуры и список
    недоступных сервисов — результат операции не теряется.
    """
    unavailable = []
    try:
        devices, total = _load_devices(filters)
    except RequestException as e:
        devices, total = [], 0
        unavailable.append("NetCerber")
        logger.error("NetCerber API (devices list) error: %s", e)
    counts = _device_counts_all()
    return devices, total, counts, unavailable


@netcerber_bp.route("/")
def index():
    unavailable_services = []
    try:
        devices, total = _load_devices(_list_filters(request.args))
    except RequestException as e:
        devices = []
        total = 0
        logger.error("NetCerber API (devices) error: %s", e)
        unavailable_services.append("NetCerber")
    filters = _list_filters(request.args)
    return render_template(
        "netcerber.html",
        devices=devices,
        total=total,
        counts=_device_counts_all(),
        unavailable_services=unavailable_services,
        **filters,
    )


@netcerber_bp.route("/htmx/list")
def htmx_list():
    filters = _list_filters(request.args)
    unavailable_services = []
    try:
        devices, total = _load_devices(filters)
    except RequestException as e:
        devices = []
        total = 0
        logger.error("NetCerber API (devices) error: %s", e)
        # Фрагмент заменяет список целиком — без баннера это выглядело
        # бы как «устройств просто нет».
        unavailable_services.append("NetCerber")

    return render_template(
        "partials/_netcerber_device_list.html",
        devices=devices,
        total=total,
        counts=_device_counts_all(),
        oob=True,
        unavailable_services=unavailable_services,
        **filters,
    )


def _opnsense_problems(config: dict) -> list[str]:
    """Проблемы конфигурации OPNsense-блокировки (пусто = настроено)."""
    if not config.get("OPNSENSE_ENABLED"):
        return []
    problems: list[str] = []
    if not str(config.get("OPNSENSE_URL", "")).strip():
        problems.append("OPNSENSE_URL пуст")
    if not config.get("OPNSENSE_KEY"):
        problems.append("OPNSENSE_KEY пуст")
    if not config.get("OPNSENSE_SECRET"):
        problems.append("OPNSENSE_SECRET пуст")
    return problems


def _opnsense_settings() -> dict | None:
    """Настройки OPNsense-блокировки из конфигурации.

    Returns:
        {url, key, secret, timeout} или None, если функция выключена
        (OPNSENSE_ENABLED=0) или настроена не полностью — какие именно
        переменные не заданы, пишет в лог.
    """
    if not current_app.config.get("OPNSENSE_ENABLED"):
        return None
    problems = _opnsense_problems(current_app.config)
    if problems:
        logger.warning(
            "OPNsense: блокировка включена, но настроена не полностью "
            "(%s) — кнопки скрыты",
            "; ".join(problems),
        )
        return None
    return {
        "url": current_app.config["OPNSENSE_URL"],
        "key": current_app.config["OPNSENSE_KEY"],
        "secret": current_app.config["OPNSENSE_SECRET"],
        "timeout": current_app.config.get("OPNSENSE_TIMEOUT", 10.0),
    }


def _opnsense_shaper_settings() -> dict | None:
    """Настройки OPNsense-шейпера (ограничения скорости) из конфигурации.

    Отдельный флаг включается независимо от блокировки; креды те же
    (один шлюз). Возвращает {url, key, secret, timeout} или None.
    """
    if not current_app.config.get("OPNSENSE_SHAPER_ENABLED"):
        return None
    problems = _opnsense_problems(current_app.config)
    if problems:
        logger.warning(
            "OPNsense: шейпер включён, но настроен не полностью "
            "(%s) — блок скрыт",
            "; ".join(problems),
        )
        return None
    return {
        "url": current_app.config["OPNSENSE_URL"],
        "key": current_app.config["OPNSENSE_KEY"],
        "secret": current_app.config["OPNSENSE_SECRET"],
        "timeout": current_app.config.get("OPNSENSE_TIMEOUT", 10.0),
    }


def _shaper_card_context(mac: str | None, ip: str | None) -> dict:
    """Состояние шейпера для карточки устройства.

    Returns:
        {"enabled": bool, "channels": [потоки-каналы], "current":
        {"uuid","name"} применённого канала или None, "ip": ip}.
        enabled=False — функция выключена, шлюз недоступен или API
        шейпера не отвечает (карточка молча скрывает блок).
    """
    if not mac:
        return {"enabled": False, "channels": [], "current": None, "ip": ip or ""}
    settings = _opnsense_shaper_settings()
    if not settings:
        return {"enabled": False, "channels": [], "current": None, "ip": ip or ""}
    try:
        client = _opnsense_client(settings)
        channels = client.shaper_pipes()
        rule = client.shaper_device_status(mac)
    except OPNsenseError as e:
        logger.error("OPNsense API (shaper %s) error: %s", settings["url"], e)
        return {"enabled": False, "channels": [], "current": None, "ip": ip or ""}
    current = None
    if rule:
        current = {
            "uuid": rule["target_uuid"],
            "name": next(
                (ch["name"] for ch in channels if ch["uuid"] == rule["target_uuid"]),
                rule["target_uuid"] or "—",
            ),
        }
    return {"enabled": True, "channels": channels, "current": current, "ip": ip or ""}


def _opnsense_client(settings: dict) -> OPNsenseClient:
    """Клиент OPNsense по настройкам (`_[a-z]+_settings` dict)."""
    return OPNsenseClient(
        settings["url"],
        settings["key"],
        settings["secret"],
        timeout=settings.get("timeout", 10.0),
    )


def _opnsense_block_status(mac: str | None, ip: str | None) -> dict:
    """Состояние OPNsense-блокировки устройства для модалки.

    Returns:
        {"enabled": bool, "blocked": bool, "ip": str|None}.
        Шлюз один, поэтому статус бинарный (есть/нет правила).
    """
    settings = _opnsense_settings()
    if not settings or not mac:
        return {"enabled": bool(settings), "blocked": False, "ip": ip}
    try:
        blocked = _opnsense_client(settings).is_blocked(mac)
    except OPNsenseError as e:
        logger.error("OPNsense API (is_blocked %s) error: %s", settings["url"], e)
        blocked = False
    return {"enabled": True, "blocked": blocked, "ip": ip}


def _opnsense_blocked_macs() -> set[str]:
    """Множество MAC, заблокированных на шлюзе (hex без ':', верхний регистр).

    Один searchRule (есть ли наше правило) + один searchItem (общий
    алиас) на отрисовку списка — вместо N+1 по каждому устройству.
    При выключенном или недоступном OPNsense возвращает пустое
    множество — бейджи просто не появляются, список не падает.
    """
    settings = _opnsense_settings()
    if not settings:
        return set()
    try:
        return _opnsense_client(settings).blocked_macs()
    except OPNsenseError as e:
        logger.error(
            "OPNsense API (blocked_macs %s) error: %s", settings["url"], e
        )
        return set()


def _proto_hex_mac(mac: str) -> str:
    """Канонический MAC без разделителей, верхний регистр."""
    raw = normalize_mac(mac) or ""
    return raw.replace(":", "")


def _block_context(device_id: int, form_values: dict) -> tuple[dict | None, str | None]:
    """MAC, hostname и IP для операций блокировки.

    MAC и IP берутся свежим запросом к NetCerber (источник истины);
    если сервис недоступен — фолбэк на поле формы из открытой модалки,
    чтобы разблокировка работала даже после удаления записи. Для шлюзной
    (OPNsense) блокировки обязателен только MAC (правило матчит по
    алиасу MAC); IP нужен лишь для отображения в модалке.

    Returns:
        ({mac, hostname, ip}, None) или (None, текст ошибки).
    """
    device = {}
    try:
        device = get_netcerber_client().get_device(device_id)
    except RequestException as e:
        logger.error("NetCerber API (device=%s) error: %s", device_id, e)

    raw_mac = device.get("mac_address") or form_values.get("mac")
    mac = normalize_mac(raw_mac)
    if not mac:
        return (
            None,
            "Не удалось определить MAC устройства: запись пуста или "
            "NetCerber недоступен",
        )
    return {
        "mac": mac,
        "hostname": device.get("hostname") or "",
        "ip": device.get("ip_address") or form_values.get("ip") or "",
    }, None


@netcerber_bp.route("/htmx/device/<int:device_id>")
def htmx_device_detail(device_id: int):
    client = get_netcerber_client()
    try:
        device = client.get_device(device_id)
    except RequestException as e:
        device = {}
        logger.error("NetCerber API (device=%s) error: %s", device_id, e)
    device_mac = normalize_mac(device.get("mac_address"))
    device_ip = device.get("ip_address") or ""
    os_status = _opnsense_block_status(device_mac, device_ip)
    shaper_status = _shaper_card_context(device_mac, device_ip)
    # Диагностика «кнопки блокировки нет»: лог называет точную причину,
    # чтобы не гадать между конфигом контейнера и форматом MAC.
    if not os_status["enabled"]:
        problems = _opnsense_problems(current_app.config)
        if problems:
            logger.warning(
                "Кнопки блокировки скрыты: %s", "; ".join(problems)
            )
        else:
            logger.info("Кнопки блокировки скрыты: OPNSENSE_ENABLED выключен")
    elif not device_mac:
        logger.warning(
            "Кнопки блокировки скрыты (устройство #%s): MAC %r не распознан",
            device_id,
            device.get("mac_address"),
        )
    return render_template(
        "partials/_netcerber_device_detail.html",
        device=device,
        ad_info=_resolve_ad(device.get("ip_address")),
        device_mac=device_mac,
        device_ip=device_ip,
        os_status=os_status,
        shaper_status=shaper_status,
        **_list_filters(request.args),
    )


@netcerber_bp.route("/htmx/os-block/<int:device_id>", methods=["POST"])
def htmx_os_block_device(device_id: int):
    """Заблокировать устройство на шлюзе OPNsense (по MAC, через алиас)."""
    filters = _list_filters(request.form)
    settings = _opnsense_settings()
    if not settings:
        return render_template(
            "partials/_error_message.html",
            message="Блокировка OPNsense отключена: проверьте OPNSENSE_ENABLED/URL/KEY",
        )
    context, error = _block_context(device_id, request.form)
    if error or not context:
        return render_template("partials/_error_message.html", message=error)

    protected = parse_mac_list(
        current_app.config.get("OPNSENSE_PROTECTED_MACS")
    )
    if is_protected_mac(context["mac"], protected):
        logger.warning(
            "Отклонена блокировка защищённого MAC %s (устройство #%s)",
            context["mac"],
            device_id,
        )
        return render_template(
            "partials/_error_message.html",
            message=(
                f"MAC {context['mac']} в списке защищённых — "
                "блокировка запрещена"
            ),
        )

    try:
        detail = _opnsense_client(settings).block_mac(context["mac"])
        ok = True
    except OPNsenseError as e:
        logger.error("OPNsense API (block %s) error: %s", settings["url"], e)
        detail, ok = str(e), False

    logger.warning(
        "Блокировка на шлюзе MAC %s (IP %s, %s #%s): %s",
        context["mac"],
        context["ip"],
        context["hostname"],
        device_id,
        "OK" if ok else detail,
    )
    devices, total, counts, unavailable = [], 0, {}, []
    if ok:
        devices, total, counts, unavailable = _reload_list_context(filters)
    return render_template(
        "partials/_netcerber_os_block_result.html",
        action="block",
        success=ok,
        mac=context["mac"],
        ip=context["ip"],
        hostname=context["hostname"],
        device_id=device_id,
        detail=detail,
        devices=devices,
        total=total,
        counts=counts,
        unavailable_services=unavailable,
        **filters,
    )


@netcerber_bp.route("/htmx/os-unblock/<int:device_id>", methods=["POST"])
def htmx_os_unblock_device(device_id: int):
    """Снять блокировку устройства на шлюзе OPNsense."""
    filters = _list_filters(request.form)
    settings = _opnsense_settings()
    if not settings:
        return render_template(
            "partials/_error_message.html",
            message="Блокировка OPNsense отключена: проверьте OPNSENSE_ENABLED/URL/KEY",
        )
    context, error = _block_context(device_id, request.form)
    if error or not context:
        return render_template("partials/_error_message.html", message=error)

    try:
        detail = _opnsense_client(settings).unblock_mac(context["mac"])
        ok = True
    except OPNsenseError as e:
        logger.error("OPNsense API (unblock %s) error: %s", settings["url"], e)
        detail, ok = str(e), False

    logger.warning(
        "Разблокировка на шлюзе MAC %s (%s #%s): %s",
        context["mac"],
        context["hostname"],
        device_id,
        "OK" if ok else detail,
    )
    devices, total, counts, unavailable = [], 0, {}, []
    if ok:
        devices, total, counts, unavailable = _reload_list_context(filters)
    return render_template(
        "partials/_netcerber_os_block_result.html",
        action="unblock",
        success=ok,
        mac=context["mac"],
        ip=context.get("ip") or "",
        hostname=context["hostname"],
        device_id=device_id,
        detail=detail,
        devices=devices,
        total=total,
        counts=counts,
        unavailable_services=unavailable,
        **filters,
    )


def _shaper_result_detail(device_id: int, filters: dict,
                          context: dict) -> str:
    """Перерисованная модалка устройства после операции шейпера.

    В отличие от блокировки (результат-фрагмент) после применения канала
    показывается сама карточка: статус и выбор канала отражают новое
    состояние, оператор может сразу поменять лимит ещё раз.
    """
    try:
        device = get_netcerber_client().get_device(device_id)
    except RequestException as e:
        logger.error("NetCerber API (device=%s) error: %s", device_id, e)
        device = {
            "id": device_id,
            "mac_address": context["mac"],
            "ip_address": context.get("ip") or "",
            "hostname": context.get("hostname") or "",
        }
    return _device_detail_response(device, filters)


@netcerber_bp.route("/htmx/shaper-apply/<int:device_id>", methods=["POST"])
def htmx_shaper_apply(device_id: int):
    """Установить устройству канал ограничения скорости на шлюзе.

    Создаёт/обновляет правило шейпера TING (destination=IP устройства →
    выбранный канал). IP обязателен: шейпер матчит именно по IP (в
    отличие от блокировки по MAC).
    """
    filters = _list_filters(request.form)
    settings = _opnsense_shaper_settings()
    if not settings:
        return render_template(
            "partials/_error_message.html",
            message="Шейпер отключён: проверьте OPNSENSE_SHAPER_ENABLED/URL/KEY",
        )
    context, error = _block_context(device_id, request.form)
    if error or not context:
        return render_template("partials/_error_message.html", message=error)
    channel_uuid = (request.form.get("channel") or "").strip()
    if not channel_uuid:
        return render_template(
            "partials/_error_message.html", message="Не выбран канал"
        )
    if not context["ip"]:
        return render_template(
            "partials/_error_message.html",
            message=(
                "У устройства нет IP-адреса — канал применить нельзя "
                "(шейпер матчит по IP, не по MAC)"
            ),
        )
    try:
        client = _opnsense_client(settings)
        channel_name = client.shaper_pipe_name(channel_uuid)
        if channel_name is None:
            return render_template(
                "partials/_error_message.html",
                message="Выбранный канал не найден на шлюзе",
            )
        detail = client.shaper_apply(context["mac"], context["ip"], channel_uuid)
        ok = True
    except OPNsenseError as e:
        logger.error("OPNsense API (shaper apply %s) error: %s",
                     settings["url"], e)
        channel_name = None
        detail, ok = str(e), False

    if ok:
        logger.warning(
            "Шейпер: канал %s назначен MAC %s (IP %s, %s #%s)",
            channel_name,
            context["mac"],
            context["ip"],
            context["hostname"],
            device_id,
        )
        return _shaper_result_detail(device_id, filters, context)
    return render_template(
        "partials/_error_message.html",
        message=f"Шейпер: не удалось применить канал: {detail}",
    )


@netcerber_bp.route("/htmx/shaper-clear/<int:device_id>", methods=["POST"])
def htmx_shaper_clear(device_id: int):
    """Снять ограничение скорости: удалить правило шейпера устройства."""
    filters = _list_filters(request.form)
    settings = _opnsense_shaper_settings()
    if not settings:
        return render_template(
            "partials/_error_message.html",
            message="Шейпер отключён: проверьте OPNSENSE_SHAPER_ENABLED/URL/KEY",
        )
    context, error = _block_context(device_id, request.form)
    if error or not context:
        return render_template("partials/_error_message.html", message=error)
    try:
        detail = _opnsense_client(settings).shaper_clear(context["mac"])
        ok = True
    except OPNsenseError as e:
        logger.error("OPNsense API (shaper clear %s) error: %s",
                     settings["url"], e)
        detail, ok = str(e), False

    if ok:
        logger.warning(
            "Шейпер: снято ограничение MAC %s (%s #%s)",
            context["mac"],
            context["hostname"],
            device_id,
        )
        return _shaper_result_detail(device_id, filters, context)
    return render_template(
        "partials/_error_message.html",
        message=f"Шейпер: не удалось снять ограничение: {detail}",
    )


@netcerber_bp.route("/htmx/authorize/<int:device_id>", methods=["POST"])
def htmx_authorize(device_id: int):
    client = get_netcerber_client()
    desc = request.form.get("description", "")
    filters = _list_filters(request.form)
    try:
        result = client.authorize_device(device_id, desc)
        return _device_detail_response(result, filters)
    except RequestException as e:
        logger.error("NetCerber API (authorize=%s) error: %s", device_id, e)
        return render_template(
            "partials/_error_message.html", message="NetCerber недоступен"
        )


@netcerber_bp.route("/htmx/unauthorize/<int:device_id>", methods=["POST"])
def htmx_unauthorize(device_id: int):
    client = get_netcerber_client()
    filters = _list_filters(request.form)
    try:
        result = client.unauthorize_device(device_id)
        return _device_detail_response(result, filters)
    except RequestException as e:
        logger.error("NetCerber API (unauthorize=%s) error: %s", device_id, e)
        return render_template(
            "partials/_error_message.html", message="NetCerber недоступен"
        )


@netcerber_bp.route("/htmx/delete/<int:device_id>", methods=["POST"])
def htmx_delete_device(device_id: int):
    """Удалить устройство из базы NetCerber.

    Для протухших записей после инцидентов вида «IP переехал на другое
    устройство»: запись со старым MAC/вендором сбивает классификацию,
    следующий скан создаст её заново с актуальными данными.

    Устройства больше нет — вместо модалки возвращается подтверждение
    и обновлённый список (hx-swap-oob), как после действий со сканами.
    """
    client = get_netcerber_client()
    filters = _list_filters(request.form)
    try:
        client.delete_device(device_id)
    except RequestException as e:
        logger.error("NetCerber API (delete=%s) error: %s", device_id, e)
        return render_template(
            "partials/_netcerber_message.html",
            success=False,
            message="Не удалось удалить: NetCerber недоступен",
        )
    unavailable_services = []
    try:
        devices, total = _load_devices(filters)
    except RequestException as e:
        devices, total = [], 0
        logger.error("NetCerber API (devices) error: %s", e)
        unavailable_services.append("NetCerber")
    return render_template(
        "partials/_netcerber_device_deleted.html",
        oob=True,
        devices=devices,
        total=total,
        counts=_device_counts_all(),
        unavailable_services=unavailable_services,
        **filters,
    )


@netcerber_bp.route("/htmx/cleanup-duplicates", methods=["POST"])
def htmx_cleanup_duplicates():
    """Удалить устаревшие записи-дубли одного IP (свежайшая остаётся).

    Дубли возникают естественно: NetCerber идентифицирует устройство
    по MAC, и при переезде IP на другое устройство старая запись
    остаётся в базе как история. Кнопка чистит историю конкретного
    адреса, не трогая остальные; ответ — обновлённый список.
    """
    values = {**request.args.to_dict(), **request.form.to_dict()}
    filters = _list_filters(values)
    ip = str(values.get("ip") or "").strip()
    if not ip:
        return render_template(
            "partials/_error_message.html", message="Не указан IP-адрес"
        )
    client = get_netcerber_client()
    try:
        data = client.get_devices(limit=500)
        grouped = group_devices_by_ip(
            _enrich(data.get("items", []), _get_dhcp_pool())
        )
    except RequestException as e:
        logger.error("NetCerber API (devices) error: %s", e)
        return render_template(
            "partials/_error_message.html", message="NetCerber недоступен"
        )

    group = next(
        (g for g in grouped if str(g.get("ip_address")) == ip), None
    )
    stale = (group or {}).get("_history", [])
    if not stale:
        # Уже почищено (повторный клик/гонка) — просто обновим список.
        return _devices_list_response(filters)

    deleted, errors = 0, 0
    for record in stale:
        try:
            client.delete_device(record["id"])
            deleted += 1
        except RequestException as e:
            errors += 1
            logger.error(
                "NetCerber API (cleanup delete=%s) error: %s", record["id"], e
            )
    logger.warning(
        "Чистка дублей IP %s: удалено %d из %d устаревших записей",
        ip, deleted, len(stale),
    )
    if errors:
        return render_template(
            "partials/_error_message.html",
            message=f"Удалено {deleted} из {len(stale)}: часть запросов не прошла",
        )
    return _devices_list_response(filters)


def _devices_list_response(filters: dict) -> str:
    """Обновлённый фрагмент списка устройств (общий хвост действий)."""
    unavailable_services = []
    try:
        devices, total = _load_devices(filters)
    except RequestException as e:
        devices, total = [], 0
        logger.error("NetCerber API (devices) error: %s", e)
        unavailable_services.append("NetCerber")
    return render_template(
        "partials/_netcerber_device_list.html",
        devices=devices,
        total=total,
        counts=_device_counts_all(),
        oob=True,
        unavailable_services=unavailable_services,
        **filters,
    )


def _device_detail_response(device: dict, filters: dict) -> str:
    """Модалка устройства + обновлённый список (hx-swap-oob).

    После авторизации/деавторизации список в фоне перерисовывается,
    чтобы статус в таблице совпадал с реальным.
    """
    device_mac = normalize_mac(device.get("mac_address"))
    device_ip = device.get("ip_address") or ""
    unavailable_services = []
    try:
        devices, total = _load_devices(filters)
    except RequestException as e:
        devices, total = [], 0
        logger.error("NetCerber API (devices) error: %s", e)
        unavailable_services.append("NetCerber")
    return render_template(
        "partials/_netcerber_device_detail.html",
        device=device,
        ad_info=_resolve_ad(device.get("ip_address")),
        device_mac=device_mac,
        device_ip=device_ip,
        os_status=_opnsense_block_status(device_mac, device_ip),
        shaper_status=_shaper_card_context(device_mac, device_ip),
        oob=True,
        devices=devices,
        total=total,
        counts=_device_counts_all(),
        unavailable_services=unavailable_services,
        **filters,
    )


@netcerber_bp.route("/htmx/authorize-all", methods=["POST"])
def htmx_authorize_all():
    client = get_netcerber_client()
    desc = request.form.get("description", "")
    try:
        result = client.authorize_all_devices(desc)
        status = result.get("status", "ok")
        msg = result.get("message", "Все устройства авторизованы")
    except RequestException as e:
        logger.error("NetCerber API (authorize-all) error: %s", e)
        return render_template(
            "partials/_netcerber_message.html",
            success=False,
            message="NetCerber недоступен",
        )
    # Обновляем список в фоне: после авторизации всех статусы изменятся.
    filters = _list_filters(request.form)
    unavailable_services = []
    try:
        devices, total = _load_devices(filters)
    except RequestException as e:
        devices, total = [], 0
        logger.error("NetCerber API (devices) error: %s", e)
        unavailable_services.append("NetCerber")
    return render_template(
        "partials/_netcerber_authorize_all.html",
        success=status == "ok",
        message=msg,
        devices=devices,
        total=total,
        unavailable_services=unavailable_services,
        **filters,
    )


@netcerber_bp.route("/export")
def export_html():
    """Выгрузка устройств в HTML-отчёт (все устройства, без фильтров).

    Отчёт генерируется на стороне NetView из обычной выборки API:
    в отличие от серверного экспорта NetCerber он включает вычисленные
    признаки подозрительности (роутер/новое/неизвестное/DHCP).
    """
    pool = _get_dhcp_pool()
    try:
        data = get_netcerber_client().get_devices(limit=500)
        devices = _enrich(
            data.get("items", []), pool, _opnsense_blocked_macs()
        )
    except RequestException as e:
        logger.error("NetCerber API (export) error: %s", e)
        return render_template("partials/_error_message.html", message="NetCerber недоступен")
    # В печатном отчёте удобнее читать список, отсортированный по IP.
    devices.sort(key=lambda d: ip_to_int(d.get("ip_address")) or 0)
    return Response(
        render_template(
            "exports/devices_report.html",
            devices=devices,
            total=data.get("total", len(devices)),
            generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        ),
        mimetype="text/html",
        headers={"Content-Disposition": "attachment; filename=devices.html"},
    )


@netcerber_bp.route("/htmx/stats")
def htmx_stats():
    client = get_netcerber_client()
    try:
        devices = client.get_devices(limit=1)
        total = devices.get("total", 0)
        unauth = client.get_devices(unauthorized=True, limit=1)
        unauth_total = unauth.get("total", 0)
        stats_data = client.get_stats()
    except RequestException as e:
        total = 0
        unauth_total = 0
        stats_data = {}
        logger.error("NetCerber API (stats) error: %s", e)
    return render_template(
        "partials/_netcerber_stats.html",
        total_devices=total,
        unauthorized=unauth_total,
        stats=stats_data,
    )


@netcerber_bp.route("/scans/")
def scans():
    client = get_netcerber_client()
    unavailable_services = []
    try:
        data = client.get_scans(limit=50)
        scans = data.get("items", [])
        total = data.get("total", 0)
    except RequestException as e:
        scans = []
        total = 0
        logger.error("NetCerber API (scans) error: %s", e)
        unavailable_services.append("NetCerber")
    try:
        baseline = client.get_baseline_scan()
    except RequestException as e:
        baseline = None
        logger.error("NetCerber API (baseline) error: %s", e)
    baseline_id = baseline["id"] if baseline else None

    try:
        scan_status = client.scan_status()
    except RequestException as e:
        scan_status = {}
        logger.error("NetCerber API (scan status) error: %s", e)

    return render_template(
        "netcerber_scans.html",
        scans=scans,
        total=total,
        baseline=baseline,
        baseline_id=baseline_id,
        scan_status=scan_status,
        unavailable_services=unavailable_services,
        skip=0,
        limit=50,
    )


@netcerber_bp.route("/htmx/scans")
def htmx_scans():
    return _render_scan_list(_scan_filters(request.args))


def _scan_filters(values: dict | None = None) -> dict:
    """Параметры журнала сканирований (skip/limit)."""
    values = values or {}
    return {
        "skip": _as_int(values.get("skip"), 0),
        "limit": _as_int(values.get("limit"), 50),
    }


def _render_scan_list(filters: dict | None = None,
                      flash: tuple[bool, str] | None = None) -> str:
    """Фрагмент журнала сканирований (список + счётчик в шапке).

    Args:
        filters: Параметры skip/limit (результат _scan_filters).
        flash: (успех, текст) сообщение поверх списка, например после
            удаления записи.

    Returns:
        HTML-фрагмент для подмены #scan-list.
    """
    filters = filters or _scan_filters({})
    client = get_netcerber_client()
    try:
        data = client.get_scans(limit=filters["limit"], skip=filters["skip"])
        scans = data.get("items", [])
        total = data.get("total", 0)
    except RequestException as e:
        scans = []
        total = 0
        logger.error("NetCerber API (scans) error: %s", e)
    try:
        baseline = client.get_baseline_scan()
        baseline_id = baseline["id"] if baseline else None
    except RequestException as e:
        baseline_id = None
        logger.error("NetCerber API (baseline) error: %s", e)
    return render_template(
        "partials/_netcerber_scans.html",
        scans=scans,
        total=total,
        baseline_id=baseline_id,
        flash=flash,
        oob=True,
        **filters,
    )


@netcerber_bp.route("/htmx/scan-now", methods=["POST"])
def htmx_trigger_scan():
    client = get_netcerber_client()
    try:
        result = client.trigger_scan()
        status = result.get("status", "ok")
        msg = result.get("message", "Сканирование запущено")
    except RequestException as e:
        logger.error("NetCerber API (trigger scan) error: %s", e)
        return render_template(
            "partials/_netcerber_message.html",
            success=False,
            message="NetCerber недоступен",
        )
    # В ответе дополнительно обновляем блок статуса (hx-swap-oob),
    # чтобы сразу увидеть "Сканирование..." и автообновление журнала.
    scan_status = {}
    last_scan = None
    try:
        scan_status = client.scan_status()
        last_scan = client.get_scans(limit=1).get("items", [])[0]
    except RequestException as e:
        logger.error("NetCerber API (scan status) error: %s", e)
    return render_template(
        "partials/_netcerber_scan_trigger.html",
        success=status == "ok",
        message=msg,
        scan_status=scan_status,
        last_scan=last_scan,
    )


@netcerber_bp.route("/htmx/scan-status")
def htmx_scan_status():
    client = get_netcerber_client()
    try:
        status = client.scan_status()
    except RequestException as e:
        status = {}
        logger.error("NetCerber API (scan status) error: %s", e)
    try:
        data = client.get_scans(limit=1)
        last_scan = data.get("items", [])
        last_scan = last_scan[0] if last_scan else None
    except RequestException as e:
        last_scan = None
        logger.error("NetCerber API (scans) error: %s", e)
    return render_template(
        "partials/_netcerber_scan_status.html",
        scan_status=status,
        last_scan=last_scan,
        oob=True,
    )


@netcerber_bp.route("/htmx/scheduler")
def htmx_scheduler():
    """HTMX: блок управления планировщиком автосканирований."""
    return render_template(
        "partials/_netcerber_scheduler.html",
        scheduler=_scheduler_status(),
    )


@netcerber_bp.route("/htmx/scheduler/toggle", methods=["POST"])
def htmx_scheduler_toggle():
    """HTMX: пауза/возобновление автосканирований."""
    running = _scheduler_status().get("running", False)
    client = get_netcerber_client()
    try:
        if running:
            client.scheduler_pause()
            flash = "Автосканирование поставлено на паузу"
        else:
            client.scheduler_resume()
            flash = "Автосканирование возобновлено"
        return render_template(
            "partials/_netcerber_scheduler.html",
            scheduler=_scheduler_status(),
            message=(True, flash),
        )
    except RequestException as e:
        logger.error("NetCerber API (scheduler toggle) error: %s", e)
        return render_template(
            "partials/_netcerber_scheduler.html",
            scheduler=_scheduler_status(),
            message=(False, "NetCerber недоступен"),
        )


@netcerber_bp.route("/htmx/scheduler/interval", methods=["POST"])
def htmx_scheduler_interval():
    """HTMX: изменить интервал автосканирований (в часах)."""
    hours = request.form.get("interval_hours", type=float)
    if not hours or hours <= 0 or hours > 168:
        return render_template(
            "partials/_netcerber_scheduler.html",
            scheduler=_scheduler_status(),
            message=(False, "Интервал: от 0.5 до 168 часов"),
        )
    try:
        get_netcerber_client().scheduler_set_interval(int(hours * 3600))
        return render_template(
            "partials/_netcerber_scheduler.html",
            scheduler=_scheduler_status(),
            message=(True, f"Интервал автосканирования: {hours:g} ч"),
        )
    except RequestException as e:
        logger.error("NetCerber API (scheduler interval) error: %s", e)
        return render_template(
            "partials/_netcerber_scheduler.html",
            scheduler=_scheduler_status(),
            message=(False, "NetCerber недоступен"),
        )


@netcerber_bp.route("/htmx/set-baseline/<int:scan_id>", methods=["POST"])
def htmx_set_baseline(scan_id: int):
    client = get_netcerber_client()
    filters = _scan_filters(request.form)
    try:
        client.set_baseline_scan(scan_id)
        return _render_scan_list(filters, flash=(True, f"Эталонный снимок #{scan_id} установлен"))
    except RequestException as e:
        logger.error("NetCerber API (set baseline=%s) error: %s", scan_id, e)
        return _render_scan_list(filters, flash=(False, "NetCerber недоступен"))


@netcerber_bp.route("/htmx/clear-baseline", methods=["POST"])
def htmx_clear_baseline():
    client = get_netcerber_client()
    filters = _scan_filters(request.form)
    try:
        client.clear_baseline_scan()
        return _render_scan_list(filters, flash=(True, "Эталонный снимок сброшен"))
    except RequestException as e:
        logger.error("NetCerber API (clear baseline) error: %s", e)
        return _render_scan_list(filters, flash=(False, "NetCerber недоступен"))


@netcerber_bp.route("/htmx/delete-scan/<int:scan_id>", methods=["POST"])
def htmx_delete_scan(scan_id: int):
    client = get_netcerber_client()
    filters = _scan_filters(request.form)
    try:
        client.delete_scan(scan_id)
        return _render_scan_list(filters, flash=(True, f"Запись #{scan_id} удалена"))
    except RequestException as e:
        logger.error("NetCerber API (delete scan=%s) error: %s", scan_id, e)
        return _render_scan_list(filters, flash=(False, "NetCerber недоступен"))


@netcerber_bp.route("/htmx/delete-scans", methods=["POST"])
def htmx_delete_scans():
    """Групповое удаление записей журнала (чекбоксы → delete_scan)."""
    client = get_netcerber_client()
    filters = _scan_filters(request.form)
    # Чекбоксы приходят строками: отсекаем мусор до запросов к API,
    # иначе int() внутри цикла ронял бы обработчик.
    ids = [
        int(v) for v in request.form.getlist("scan_ids") if v.strip().isdigit()
    ]
    if not ids:
        return _render_scan_list(filters, flash=(False, "Не выбрано записей"))
    errors = 0
    for scan_id in ids:
        try:
            client.delete_scan(scan_id)
        except RequestException as e:
            errors += 1
            logger.error("NetCerber API (delete scan=%s) error: %s", scan_id, e)
    deleted = len(ids) - errors
    if errors:
        msg = f"Удалено {deleted} из {len(ids)} записей"
        return _render_scan_list(filters, flash=(False, msg))
    return _render_scan_list(filters, flash=(True, f"Удалено записей: {deleted}"))


@netcerber_bp.route("/htmx/alerts")
def htmx_alerts():
    client = get_netcerber_client()
    limit = request.args.get("limit", 20, type=int)
    alert_type = request.args.get("type")
    try:
        data = client.get_alerts(limit=limit, alert_type=alert_type)
        alerts = data.get("items", [])
        total = data.get("total", 0)
    except RequestException as e:
        alerts = []
        total = 0
        logger.error("NetCerber API (alerts) error: %s", e)
    return render_template(
        "partials/_netcerber_alerts.html",
        alerts=alerts,
        total=total,
        alert_type=alert_type,
    )
