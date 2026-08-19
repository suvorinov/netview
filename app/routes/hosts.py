"""Маршруты хостов.

Модуль содержит маршруты для работы с хостами.
"""

import logging

from flask import Blueprint, current_app, render_template, request

from app.api.host_client import HostMonitorClient
from app.utils import sort_items

hosts_bp = Blueprint("hosts", __name__)

logger = logging.getLogger(__name__)

# Карта полей для сортировки
SORT_FIELDS: dict[str, str] = {
    "hostname": "hostname",
    "ip": "ip_address",
    "os": "os_name",
    "cpu": "cpu_percent",
    "ram": "ram_percent",
    "disk": "disk_percent",
    "status": "status",
}


def _get_client() -> HostMonitorClient:
    """Создать клиент Host Monitor API.

    Returns:
        Экземпляр клиента.
    """
    return HostMonitorClient(current_app.config["HOST_API_URL"])


@hosts_bp.route("/")
def hosts_list() -> str:
    """Страница списка хостов.

    Returns:
        HTML-шаблон со списком хостов.
    """
    client = _get_client()
    unavailable_services = []
    try:
        # Пагинация не используется: показываем все хосты одним списком
        data = client.get_hosts(page=1, limit=500)
        hosts = data.get("items", [])
        stats = client.get_stats()
    except Exception as e:
        hosts = []
        stats = {"total": 0, "online": 0, "offline": 0}
        logger.error("Host Monitor API error: %s", e)
        unavailable_services.append("Host Monitor")

    return render_template(
        "hosts.html",
        hosts=hosts,
        stats=stats,
        unavailable_services=unavailable_services,
    )


@hosts_bp.route("/htmx/list")
def htmx_hosts_list() -> str:
    """HTMX: список хостов для частичной загрузки.

    Returns:
        HTML-фрагмент со списком хостов.
    """
    client = _get_client()
    status_filter = request.args.get("status", None)
    sort_by = request.args.get("sort", "")
    order = request.args.get("order", "asc")

    try:
        data = client.get_hosts(page=1, limit=500, status=status_filter)
        hosts = data.get("items", [])
    except Exception as e:
        hosts = []
        logger.error("Host Monitor API error: %s", e)

    hosts = sort_items(hosts, sort_by, order, SORT_FIELDS)

    return render_template(
        "partials/_host_list.html",
        hosts=hosts,
        status_filter=status_filter,
        sort_by=sort_by,
        order=order
    )


@hosts_bp.route("/stats")
def hosts_stats() -> str:
    """HTMX: статистика хостов.

    Returns:
        HTML-фрагмент со статистикой.
    """
    client = _get_client()
    try:
        stats = client.get_stats()
    except Exception as e:
        stats = {"total": 0, "online": 0, "offline": 0}
        logger.error("Host Monitor API error: %s", e)

    return render_template("partials/_host_stats.html", stats=stats)


@hosts_bp.route("/htmx/host/<hostname>")
def htmx_host_detail(hostname: str) -> str:
    """HTMX: детальная информация о хосте для модального окна.

    Args:
        hostname: Имя хоста.

    Returns:
        HTML-фрагмент с информацией о хосте.
    """
    client = _get_client()
    try:
        host = client.get_host(hostname)
    except Exception as e:
        host = {}
        logger.error("Host Monitor API error (host=%s): %s", hostname, e)

    return render_template("partials/_host_detail.html", host=host)
