"""Маршруты Dashboard.

Модуль содержит маршруты для главной страницы Dashboard.
"""

import logging
from collections.abc import Callable
from typing import Any

from flask import Blueprint, render_template
from requests import RequestException

from app.api.factories import (
    get_host_client,
    get_logspy_client,
    get_netcerber_client,
    get_printer_client,
)
from app.utils import (
    is_new_device,
    is_router_vendor,
    is_unknown_device,
    run_in_parallel,
)

dashboard_bp = Blueprint("dashboard", __name__)

logger = logging.getLogger(__name__)

# Порог загрузки RAM/Диска, после которого хост считается критическим
CRITICAL_PERCENT = 80

# Значения по умолчанию при недоступности сервисов
EMPTY_HOST_STATS = {"total": 0, "online": 0, "offline": 0, "avg_cpu": 0}


def _has_toner(p: dict[str, Any]) -> bool:
    """Есть ли у принтера числовое значение тонера (не "N/A").

    У принтеров без данных о расходнике API отдаёт 0.0 с
    toner_percentage == "N/A" — такие принтеры не считаются критическими.
    """
    if p.get("toner_percentage") == "N/A":
        return False
    return isinstance(p.get("toner_percentage_value"), int | float)


def _critical_printers(
    printers: list[dict[str, Any]], toner_threshold: int, limit: int = 5
) -> list[dict[str, Any]]:
    """Принтеры с тонером ниже порога, топ-limit по возрастанию тонера.

    Принтеры с "N/A" (нет данных о тонере) исключаются из списка.
    """
    critical = [
        p for p in printers
        if _has_toner(p)
        and p.get("toner_percentage_value", 0) < toner_threshold
    ]
    return sorted(critical, key=lambda p: p["toner_percentage_value"])[:limit]


def _critical_hosts(
    hosts: list[dict[str, Any]], limit: int = 5
) -> list[dict[str, Any]]:
    """Хосты с критической загрузкой RAM/Диска, топ-limit по нагрузке."""
    return sorted(
        (h for h in hosts
         if h.get("ram_percent", 0) > CRITICAL_PERCENT
         or h.get("disk_percent", 0) > CRITICAL_PERCENT),
        key=lambda h: max(h.get("ram_percent", 0), h.get("disk_percent", 0)),
        reverse=True,
    )[:limit]


@dashboard_bp.route("/")
def index() -> str:
    printer_client = get_printer_client()
    host_client = get_host_client()
    logspy_client = get_logspy_client()
    netcerber_client = get_netcerber_client()

    # Независимые запросы выполняем параллельно, чтобы страница не ждала
    # каждый сервис по очереди (при недоступном сервисе — до 20 секунд).
    task_fns: dict[str, Callable[[], Any]] = {
        "printers": printer_client.get_printers,
        "threshold": printer_client.get_threshold,
        "host_stats": host_client.get_stats,
        "hosts": lambda: host_client.get_hosts(page=1, limit=500),
        "ad_stats": logspy_client.get_ad_stats,
        "logs": logspy_client.get_logs,
        "stoplist": logspy_client.get_stoplist,
        "netcerber_devices": lambda: netcerber_client.get_devices(limit=500),
        "netcerber_alerts": lambda: netcerber_client.get_alerts(limit=1),
        "netcerber_stats": netcerber_client.get_stats,
    }
    # Сервис-владелец каждой задачи — для баннера недоступности.
    task_service = {
        "printers": "Printer Monitor",
        "threshold": "Printer Monitor",
        "host_stats": "Host Monitor",
        "hosts": "Host Monitor",
        "ad_stats": "LogSpy",
        "logs": "LogSpy",
        "stoplist": "LogSpy",
        "netcerber_devices": "NetCerber",
        "netcerber_alerts": "NetCerber",
        "netcerber_stats": "NetCerber",
    }
    # Значение-заглушка для каждой задачи при недоступном сервисе.
    task_defaults: dict[str, Any] = {
        "printers": [],
        "threshold": {},
        "host_stats": EMPTY_HOST_STATS,
        "hosts": {},
        "ad_stats": {},
        "logs": [],
        "stoplist": {},
        "netcerber_devices": {},
        "netcerber_alerts": {},
        "netcerber_stats": {},
    }

    results = run_in_parallel(task_fns, service="Dashboard")
    unavailable = {
        task_service[name]
        for name, value in results.items() if value is None
    }
    data = {
        name: (value if value is not None else task_defaults[name])
        for name, value in results.items()
    }

    printers = data["printers"]
    printer_count = len(printers)
    toner_threshold = data["threshold"].get("threshold", 20)
    low_toner = sum(
        1 for p in printers
        if _has_toner(p)
        and p.get("toner_percentage_value", 0) < toner_threshold
    )
    critical_printers = _critical_printers(printers, toner_threshold)

    host_stats = data["host_stats"]
    host_count = host_stats.get("total", 0)
    hosts_online = host_stats.get("online", 0)
    hosts_offline = host_stats.get("offline", 0)
    critical_hosts = _critical_hosts(data["hosts"].get("items", []))

    ad_stats = data["ad_stats"]
    ad_users_count = ad_stats.get("enabled_users", 0)
    ad_computers_count = ad_stats.get("total_computers", 0)
    ad_sync_status = ad_stats.get("sync_status", "not_started")

    # Summary зависит от списка логов — выполняется после параллельного блока.
    log_files = data["logs"]
    blocked_count = 0
    total_requests = 0
    unique_users = 0
    if log_files:
        try:
            summary = logspy_client.get_summary(log_files[0]["name"])
        except RequestException as e:
            logger.error("LogSpy API (logs/summary) error: %s", e)
            unavailable.add("LogSpy")
        else:
            # Разбор ответа вне try: ошибка формы данных — наш баг,
            # а не «сервис недоступен», и не должен маскироваться.
            ip_summary = summary.get("summary", {})
            for item in ip_summary.values():
                blocked_count += item.get("blocked_visits", 0)
                total_requests += item.get("total_visits", 0)
            unique_users = len(ip_summary)

    stoplist_count = data["stoplist"].get("total", 0)

    # NetCerber: счётчики подозрительных устройств и топ новых.
    nc_devices = data["netcerber_devices"].get("items", [])
    nc_router = 0
    nc_unknown = 0
    nc_new: list[dict[str, Any]] = []
    for d in nc_devices:
        unknown = is_unknown_device(d)
        if is_router_vendor(d.get("vendor", ""), unknown):
            nc_router += 1
        if unknown:
            nc_unknown += 1
        if is_new_device(d):
            nc_new.append(d)
    nc_new.sort(key=lambda d: d.get("first_seen") or "", reverse=True)
    nc_alerts_total = data["netcerber_alerts"].get("total", 0)
    nc_stats = data["netcerber_stats"]
    nc_total_devices = nc_stats.get("total_devices", 0)
    nc_authorized = nc_stats.get("authorized_count", 0)

    return render_template(
        "dashboard.html",
        printer_count=printer_count,
        low_toner=low_toner,
        printers=printers,
        critical_printers=critical_printers,
        host_count=host_count,
        hosts_online=hosts_online,
        hosts_offline=hosts_offline,
        stats=host_stats,
        critical_hosts=critical_hosts,
        ad_users_count=ad_users_count,
        ad_computers_count=ad_computers_count,
        ad_sync_status=ad_sync_status,
        log_files_count=len(log_files),
        blocked_count=blocked_count,
        total_requests=total_requests,
        unique_users=unique_users,
        stoplist_count=stoplist_count,
        nc_router=nc_router,
        nc_unknown=nc_unknown,
        nc_new_count=len(nc_new),
        nc_new_top=nc_new[:5],
        nc_alerts_total=nc_alerts_total,
        nc_total_devices=nc_total_devices,
        nc_authorized=nc_authorized,
        unavailable_services=sorted(unavailable),
    )
