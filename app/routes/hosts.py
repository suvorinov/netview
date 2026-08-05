"""Маршруты хостов.

Модуль содержит маршруты для работы с хостами.
"""

import logging
from typing import Any

from flask import Blueprint, render_template, current_app, request

from app.api.host_client import HostMonitorClient

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
        data = client.get_hosts(page=1, limit=50)
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


def _sort_hosts(hosts: list[dict[str, Any]], sort_by: str, order: str) -> list[dict[str, Any]]:
    """Сортировать список хостов.

    Args:
        hosts: Список хостов.
        sort_by: Поле сортировки.
        order: Направление (asc/desc).

    Returns:
        Отсортированный список.
    """
    if sort_by not in SORT_FIELDS:
        return hosts

    field = SORT_FIELDS[sort_by]
    reverse = order == "desc"

    def get_sort_key(h: dict) -> Any:
        val = h.get(field, "")
        if isinstance(val, (int, float)):
            return val
        return val or ""

    return sorted(hosts, key=get_sort_key, reverse=reverse)


@hosts_bp.route("/htmx/list")
def htmx_hosts_list() -> str:
    """HTMX: список хостов для частичной загрузки.

    Returns:
        HTML-фрагмент со списком хостов.
    """
    client = _get_client()
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", None)
    sort_by = request.args.get("sort", "")
    order = request.args.get("order", "asc")

    try:
        data = client.get_hosts(page=page, limit=50, status=status_filter)
        hosts = data.get("items", [])
        total_pages = data.get("total_pages", 1)
    except Exception as e:
        hosts = []
        total_pages = 1
        logger.error("Host Monitor API error: %s", e)

    hosts = _sort_hosts(hosts, sort_by, order)

    return render_template(
        "partials/_host_list.html",
        hosts=hosts,
        current_page=page,
        total_pages=total_pages,
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
