"""Маршруты NetCerber — мониторинг устройств локальной сети.

Модуль содержит маршруты для просмотра устройств, управления
авторизацией, журнала сканирований и оповещений NetCerber.
"""

import logging

from flask import Blueprint, current_app, render_template, request

from app.api.netcerber_client import NetCerberClient
from app.utils import sort_items

netcerber_bp = Blueprint("netcerber", __name__)

logger = logging.getLogger(__name__)

SORT_FIELDS: dict[str, str] = {
    "ip": "ip_address",
    "hostname": "hostname",
    "vendor": "vendor",
    "last_seen": "last_seen",
    "first_seen": "first_seen",
}


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


@netcerber_bp.route("/")
def index():
    client = _get_client()
    unavailable_services = []
    try:
        data = client.get_devices(limit=100)
        devices = data.get("items", [])
        total = data.get("total", 0)
    except Exception as e:
        devices = []
        total = 0
        logger.error("NetCerber API (devices) error: %s", e)
        unavailable_services.append("NetCerber")
    return render_template(
        "netcerber.html",
        devices=devices,
        total=total,
        unavailable_services=unavailable_services,
    )


@netcerber_bp.route("/htmx/list")
def htmx_list():
    client = _get_client()
    authorized = _as_bool(request.args.get("authorized"))
    unauthorized = _as_bool(request.args.get("unauthorized"))
    sort_by = request.args.get("sort", "")
    order = request.args.get("order", "asc")
    skip = request.args.get("skip", 0, type=int)
    limit = request.args.get("limit", 100, type=int)

    try:
        data = client.get_devices(
            authorized=authorized,
            unauthorized=unauthorized,
            sort_by=sort_by or None,
            skip=skip,
            limit=limit,
        )
        devices = data.get("items", [])
        total = data.get("total", 0)
    except Exception as e:
        devices = []
        total = 0
        logger.error("NetCerber API (devices) error: %s", e)

    devices = sort_items(devices, sort_by, order, SORT_FIELDS)

    return render_template(
        "partials/_netcerber_device_list.html",
        devices=devices,
        total=total,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        order=order,
        authorized=authorized,
        unauthorized=unauthorized,
    )


@netcerber_bp.route("/htmx/device/<int:device_id>")
def htmx_device_detail(device_id: int):
    client = _get_client()
    try:
        device = client.get_device(device_id)
    except Exception as e:
        device = {}
        logger.error("NetCerber API (device=%s) error: %s", device_id, e)
    return render_template("partials/_netcerber_device_detail.html", device=device)


@netcerber_bp.route("/htmx/authorize/<int:device_id>", methods=["POST"])
def htmx_authorize(device_id: int):
    client = _get_client()
    desc = request.form.get("description", "")
    try:
        result = client.authorize_device(device_id, desc)
        return render_template(
            "partials/_netcerber_device_detail.html", device=result
        )
    except Exception as e:
        logger.error("NetCerber API (authorize=%s) error: %s", device_id, e)
        return render_template(
            "partials/_error_message.html", message=str(e)
        )


@netcerber_bp.route("/htmx/unauthorize/<int:device_id>", methods=["POST"])
def htmx_unauthorize(device_id: int):
    client = _get_client()
    try:
        result = client.unauthorize_device(device_id)
        return render_template(
            "partials/_netcerber_device_detail.html", device=result
        )
    except Exception as e:
        logger.error("NetCerber API (unauthorize=%s) error: %s", device_id, e)
        return render_template(
            "partials/_error_message.html", message=str(e)
        )


@netcerber_bp.route("/htmx/authorize-all", methods=["POST"])
def htmx_authorize_all():
    client = _get_client()
    desc = request.form.get("description", "")
    try:
        result = client.authorize_all_devices(desc)
        status = result.get("status", "ok")
        msg = result.get("message", "Все устройства авторизованы")
        return render_template(
            "partials/_netcerber_message.html",
            success=status == "ok",
            message=msg,
        )
    except Exception as e:
        logger.error("NetCerber API (authorize-all) error: %s", e)
        return render_template(
            "partials/_netcerber_message.html",
            success=False,
            message=str(e),
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
        scan_status=scan_status,
        unavailable_services=unavailable_services,
    )


@netcerber_bp.route("/htmx/scans")
def htmx_scans():
    client = _get_client()
    skip = request.args.get("skip", 0, type=int)
    limit = request.args.get("limit", 50, type=int)
    try:
        data = client.get_scans(limit=limit, skip=skip)
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
        skip=skip,
        limit=limit,
        baseline_id=baseline_id,
    )


@netcerber_bp.route("/htmx/scan-now", methods=["POST"])
def htmx_trigger_scan():
    client = _get_client()
    try:
        result = client.trigger_scan()
        status = result.get("status", "ok")
        msg = result.get("message", "Сканирование запущено")
        return render_template(
            "partials/_netcerber_message.html",
            success=status == "ok",
            message=msg,
        )
    except Exception as e:
        logger.error("NetCerber API (trigger scan) error: %s", e)
        return render_template(
            "partials/_netcerber_message.html",
            success=False,
            message=str(e),
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
    )


@netcerber_bp.route("/htmx/set-baseline/<int:scan_id>", methods=["POST"])
def htmx_set_baseline(scan_id: int):
    client = _get_client()
    try:
        client.set_baseline_scan(scan_id)
        return render_template(
            "partials/_netcerber_message.html",
            success=True,
            message="Эталонный снимок установлен",
        )
    except Exception as e:
        logger.error("NetCerber API (set baseline=%s) error: %s", scan_id, e)
        return render_template(
            "partials/_netcerber_message.html",
            success=False,
            message=str(e),
        )


@netcerber_bp.route("/htmx/clear-baseline", methods=["POST"])
def htmx_clear_baseline():
    client = _get_client()
    try:
        client.clear_baseline_scan()
        return render_template(
            "partials/_netcerber_message.html",
            success=True,
            message="Эталонный снимок сброшен",
        )
    except Exception as e:
        logger.error("NetCerber API (clear baseline) error: %s", e)
        return render_template(
            "partials/_netcerber_message.html",
            success=False,
            message=str(e),
        )


@netcerber_bp.route("/htmx/delete-scan/<int:scan_id>", methods=["POST"])
def htmx_delete_scan(scan_id: int):
    client = _get_client()
    try:
        client.delete_scan(scan_id)
        return render_template(
            "partials/_netcerber_message.html",
            success=True,
            message="Запись сканирования удалена",
        )
    except Exception as e:
        logger.error("NetCerber API (delete scan=%s) error: %s", scan_id, e)
        return render_template(
            "partials/_netcerber_message.html",
            success=False,
            message=str(e),
        )


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
