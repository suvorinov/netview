"""Маршруты NetCerber — мониторинг устройств локальной сети.

Модуль содержит маршруты для просмотра устройств, управления
авторизацией, журнала сканирований и оповещений NetCerber.
"""

import logging
import re

from flask import Blueprint, Response, current_app, render_template, request

from app.api.logspy_client import LogSpyClient
from app.api.netcerber_client import NetCerberClient
from app.utils import (
    is_in_dhcp_pool,
    is_new_device,
    is_router_vendor,
    is_unknown_device,
    parse_dhcp_pool,
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
}


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


def _get_client() -> NetCerberClient:
    return NetCerberClient(current_app.config["NETCERBER_API_URL"])


def _get_logspy_client() -> LogSpyClient:
    return LogSpyClient(current_app.config["LOGSPY_API_URL"])


def _resolve_ad(ip_address: str | None) -> dict | None:
    """Сопоставить IP с компьютером/пользователем AD (через LogSpy).

    Returns:
        {"username", "computer_name", "source"} или None, если
        сопоставление не найдено или сервис недоступен.
    """
    if not ip_address:
        return None
    try:
        return _get_logspy_client().ad_resolve_ip(ip_address)
    except Exception as e:
        logger.info("LogSpy AD resolve (%s): %s", ip_address, e)
        return None


def _scheduler_status() -> dict:
    """Статус планировщика автосканирований NetCerber.

    Добавляет interval_hours — интервал из trigger-строки
    "interval[5:00:00]" в часах (для поля формы).
    """
    try:
        status = _get_client().scheduler_status()
    except Exception as e:
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

    Возвращает словарь {router, new, unknown, dhcp} для отрисовки бейджей.
    """
    unknown = is_unknown_device(device)
    return {
        "router": is_router_vendor(device.get("vendor", ""), unknown),
        "new": is_new_device(device),
        "unknown": unknown,
        "dhcp": is_in_dhcp_pool(device.get("ip_address"), pool),
    }


def _enrich(devices: list[dict], pool: tuple[str, str] | None = None) -> list[dict]:
    """Добавить каждому устройству вычисленные признаки (_flags)."""
    for d in devices:
        d["_flags"] = _device_flags(d, pool)
    return devices


def _device_counts(devices: list[dict], pool: tuple[str, str] | None = None) -> dict[str, int]:
    """Счётчики категорий подозрительности для чипов-фильтров."""
    counts = {"router": 0, "new": 0, "unknown": 0, "dhcp": 0}
    for d in devices:
        flags = d.get("_flags") or _device_flags(d, pool)
        for key in counts:
            if flags.get(key):
                counts[key] += 1
    return counts


def _match_category(device: dict, category: str) -> bool:
    """Совпадает ли устройство с категорией фильтра."""
    if not category:
        return True
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
    return {
        "authorized": _as_bool(values.get("authorized")),
        "unauthorized": _as_bool(values.get("unauthorized")),
        "cat": (values.get("cat") or "").strip(),
        "q": (values.get("q") or "").strip(),
        "sort_by": values.get("sort", "first_seen"),
        "order": values.get("order", "desc"),
        "skip": int(values.get("skip") or 0),
        "limit": int(values.get("limit") or 100),
    }


def _load_devices(filters: dict) -> tuple[list[dict], int]:
    """Устройства с признаками подозрительности по параметрам списка.

    Args:
        filters: Результат _list_filters().

    Returns:
        (список устройств с _flags, число отображённых устройств).

    При активном фильтре категории или поиске выборка берётся целиком
    (limit=500), чтобы total и пагинация были честными.
    """
    client = _get_client()
    pool = _get_dhcp_pool()
    full_scan = bool(filters["cat"] or filters["q"])
    data = client.get_devices(
        authorized=filters["authorized"],
        unauthorized=filters["unauthorized"],
        sort_by=filters["sort_by"] or None,
        skip=0 if full_scan else filters["skip"],
        limit=500 if full_scan else filters["limit"],
    )
    devices = _enrich(data.get("items", []), pool)
    total = data.get("total", 0)
    devices = [d for d in devices if _match_category(d, filters["cat"])]
    devices = [d for d in devices if _matches_query(d, filters["q"])]
    if full_scan:
        total = len(devices)
    return sort_items(devices, filters["sort_by"], filters["order"], SORT_FIELDS), total


def _device_counts_all() -> dict[str, int]:
    """Счётчики категорий подозрительности по всем устройствам.

    Отдельный запрос полной выборки — чипы должны показывать
    реальные числа, а не только по загруженной странице списка.
    """
    try:
        data = _get_client().get_devices(limit=500)
        return _device_counts(_enrich(data.get("items", []), _get_dhcp_pool()))
    except Exception as e:
        logger.error("NetCerber API (devices counts) error: %s", e)
        return {"router": 0, "new": 0, "unknown": 0, "dhcp": 0}


@netcerber_bp.route("/")
def index():
    unavailable_services = []
    try:
        devices, total = _load_devices(_list_filters(request.args))
    except Exception as e:
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
    try:
        devices, total = _load_devices(filters)
    except Exception as e:
        devices = []
        total = 0
        logger.error("NetCerber API (devices) error: %s", e)

    return render_template(
        "partials/_netcerber_device_list.html",
        devices=devices,
        total=total,
        counts=_device_counts_all(),
        oob=True,
        **filters,
    )


@netcerber_bp.route("/htmx/device/<int:device_id>")
def htmx_device_detail(device_id: int):
    client = _get_client()
    try:
        device = client.get_device(device_id)
    except Exception as e:
        device = {}
        logger.error("NetCerber API (device=%s) error: %s", device_id, e)
    return render_template(
        "partials/_netcerber_device_detail.html",
        device=device,
        ad_info=_resolve_ad(device.get("ip_address")),
        **_list_filters(request.args),
    )


@netcerber_bp.route("/htmx/authorize/<int:device_id>", methods=["POST"])
def htmx_authorize(device_id: int):
    client = _get_client()
    desc = request.form.get("description", "")
    filters = _list_filters(request.form)
    try:
        result = client.authorize_device(device_id, desc)
        return _device_detail_response(result, filters)
    except Exception as e:
        logger.error("NetCerber API (authorize=%s) error: %s", device_id, e)
        return render_template(
            "partials/_error_message.html", message=str(e)
        )


@netcerber_bp.route("/htmx/unauthorize/<int:device_id>", methods=["POST"])
def htmx_unauthorize(device_id: int):
    client = _get_client()
    filters = _list_filters(request.form)
    try:
        result = client.unauthorize_device(device_id)
        return _device_detail_response(result, filters)
    except Exception as e:
        logger.error("NetCerber API (unauthorize=%s) error: %s", device_id, e)
        return render_template(
            "partials/_error_message.html", message=str(e)
        )


def _device_detail_response(device: dict, filters: dict) -> str:
    """Модалка устройства + обновлённый список (hx-swap-oob).

    После авторизации/деавторизации список в фоне перерисовывается,
    чтобы статус в таблице совпадал с реальным.
    """
    try:
        devices, total = _load_devices(filters)
    except Exception as e:
        devices, total = [], 0
        logger.error("NetCerber API (devices) error: %s", e)
    return render_template(
        "partials/_netcerber_device_detail.html",
        device=device,
        ad_info=_resolve_ad(device.get("ip_address")),
        oob=True,
        devices=devices,
        total=total,
        counts=_device_counts_all(),
        **filters,
    )


@netcerber_bp.route("/htmx/authorize-all", methods=["POST"])
def htmx_authorize_all():
    client = _get_client()
    desc = request.form.get("description", "")
    try:
        result = client.authorize_all_devices(desc)
        status = result.get("status", "ok")
        msg = result.get("message", "Все устройства авторизованы")
    except Exception as e:
        logger.error("NetCerber API (authorize-all) error: %s", e)
        return render_template(
            "partials/_netcerber_message.html",
            success=False,
            message=str(e),
        )
    # Обновляем список в фоне: после авторизации всех статусы изменятся.
    filters = _list_filters(request.form)
    try:
        devices, total = _load_devices(filters)
    except Exception as e:
        devices, total = [], 0
        logger.error("NetCerber API (devices) error: %s", e)
    return render_template(
        "partials/_netcerber_authorize_all.html",
        success=status == "ok",
        message=msg,
        devices=devices,
        total=total,
        **filters,
    )


@netcerber_bp.route("/export")
def export_csv():
    """Выгрузка устройств в CSV (все устройства, без фильтров)."""
    client = _get_client()
    try:
        csv_text = client.export_devices("csv")
    except Exception as e:
        logger.error("NetCerber API (export) error: %s", e)
        return render_template("partials/_error_message.html", message=str(e))
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=devices.csv"},
    )


@netcerber_bp.route("/htmx/stats")
def htmx_stats():
    client = _get_client()
    try:
        devices = client.get_devices(limit=1)
        total = devices.get("total", 0)
        unauth = client.get_devices(unauthorized=True, limit=1)
        unauth_total = unauth.get("total", 0)
        stats_data = client.get_stats()
    except Exception as e:
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
    client = _get_client()
    unavailable_services = []
    try:
        data = client.get_scans(limit=50)
        scans = data.get("items", [])
        total = data.get("total", 0)
    except Exception as e:
        scans = []
        total = 0
        logger.error("NetCerber API (scans) error: %s", e)
        unavailable_services.append("NetCerber")
    try:
        baseline = client.get_baseline_scan()
    except Exception as e:
        baseline = None
        logger.error("NetCerber API (baseline) error: %s", e)
    baseline_id = baseline["id"] if baseline else None

    try:
        scan_status = client.scan_status()
    except Exception as e:
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
        "skip": int(values.get("skip") or 0),
        "limit": int(values.get("limit") or 50),
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
    client = _get_client()
    try:
        data = client.get_scans(limit=filters["limit"], skip=filters["skip"])
        scans = data.get("items", [])
        total = data.get("total", 0)
    except Exception as e:
        scans = []
        total = 0
        logger.error("NetCerber API (scans) error: %s", e)
    try:
        baseline = client.get_baseline_scan()
        baseline_id = baseline["id"] if baseline else None
    except Exception as e:
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
    client = _get_client()
    try:
        result = client.trigger_scan()
        status = result.get("status", "ok")
        msg = result.get("message", "Сканирование запущено")
    except Exception as e:
        logger.error("NetCerber API (trigger scan) error: %s", e)
        return render_template(
            "partials/_netcerber_message.html",
            success=False,
            message=str(e),
        )
    # В ответе дополнительно обновляем блок статуса (hx-swap-oob),
    # чтобы сразу увидеть "Сканирование..." и автообновление журнала.
    scan_status = {}
    last_scan = None
    try:
        scan_status = client.scan_status()
        last_scan = client.get_scans(limit=1).get("items", [])[0]
    except Exception as e:
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
    client = _get_client()
    try:
        status = client.scan_status()
    except Exception as e:
        status = {}
        logger.error("NetCerber API (scan status) error: %s", e)
    try:
        data = client.get_scans(limit=1)
        last_scan = data.get("items", [])
        last_scan = last_scan[0] if last_scan else None
    except Exception as e:
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
    client = _get_client()
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
    except Exception as e:
        logger.error("NetCerber API (scheduler toggle) error: %s", e)
        return render_template(
            "partials/_netcerber_scheduler.html",
            scheduler=_scheduler_status(),
            message=(False, str(e)),
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
        _get_client().scheduler_set_interval(int(hours * 3600))
        return render_template(
            "partials/_netcerber_scheduler.html",
            scheduler=_scheduler_status(),
            message=(True, f"Интервал автосканирования: {hours:g} ч"),
        )
    except Exception as e:
        logger.error("NetCerber API (scheduler interval) error: %s", e)
        return render_template(
            "partials/_netcerber_scheduler.html",
            scheduler=_scheduler_status(),
            message=(False, str(e)),
        )


@netcerber_bp.route("/htmx/set-baseline/<int:scan_id>", methods=["POST"])
def htmx_set_baseline(scan_id: int):
    client = _get_client()
    filters = _scan_filters(request.form)
    try:
        client.set_baseline_scan(scan_id)
        return _render_scan_list(filters, flash=(True, f"Эталонный снимок #{scan_id} установлен"))
    except Exception as e:
        logger.error("NetCerber API (set baseline=%s) error: %s", scan_id, e)
        return _render_scan_list(filters, flash=(False, str(e)))


@netcerber_bp.route("/htmx/clear-baseline", methods=["POST"])
def htmx_clear_baseline():
    client = _get_client()
    filters = _scan_filters(request.form)
    try:
        client.clear_baseline_scan()
        return _render_scan_list(filters, flash=(True, "Эталонный снимок сброшен"))
    except Exception as e:
        logger.error("NetCerber API (clear baseline) error: %s", e)
        return _render_scan_list(filters, flash=(False, str(e)))


@netcerber_bp.route("/htmx/delete-scan/<int:scan_id>", methods=["POST"])
def htmx_delete_scan(scan_id: int):
    client = _get_client()
    filters = _scan_filters(request.form)
    try:
        client.delete_scan(scan_id)
        return _render_scan_list(filters, flash=(True, f"Запись #{scan_id} удалена"))
    except Exception as e:
        logger.error("NetCerber API (delete scan=%s) error: %s", scan_id, e)
        return _render_scan_list(filters, flash=(False, str(e)))


@netcerber_bp.route("/htmx/delete-scans", methods=["POST"])
def htmx_delete_scans():
    """Групповое удаление записей журнала (чекбоксы → delete_scan)."""
    client = _get_client()
    filters = _scan_filters(request.form)
    ids = request.form.getlist("scan_ids")
    if not ids:
        return _render_scan_list(filters, flash=(False, "Не выбрано записей"))
    errors = 0
    for scan_id in ids:
        try:
            client.delete_scan(int(scan_id))
        except Exception as e:
            errors += 1
            logger.error("NetCerber API (delete scan=%s) error: %s", scan_id, e)
    deleted = len(ids) - errors
    if errors:
        msg = f"Удалено {deleted} из {len(ids)} записей"
        return _render_scan_list(filters, flash=(False, msg))
    return _render_scan_list(filters, flash=(True, f"Удалено записей: {deleted}"))


@netcerber_bp.route("/htmx/alerts")
def htmx_alerts():
    client = _get_client()
    limit = request.args.get("limit", 20, type=int)
    alert_type = request.args.get("type")
    try:
        data = client.get_alerts(limit=limit, alert_type=alert_type)
        alerts = data.get("items", [])
        total = data.get("total", 0)
    except Exception as e:
        alerts = []
        total = 0
        logger.error("NetCerber API (alerts) error: %s", e)
    return render_template(
        "partials/_netcerber_alerts.html",
        alerts=alerts,
        total=total,
        alert_type=alert_type,
    )
