"""Маршруты Dashboard.

Модуль содержит маршруты для главной страницы Dashboard.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from flask import Blueprint, current_app, render_template

from app.api.host_client import HostMonitorClient
from app.api.logspy_client import LogSpyClient
from app.api.netcerber_client import NetCerberClient
from app.api.printer_client import PrinterMonitorClient
from app.utils import is_new_device, is_router_vendor, is_unknown_device

dashboard_bp = Blueprint("dashboard", __name__)

logger = logging.getLogger(__name__)

# Порог загрузки RAM/Диска, после которого хост считается критическим
CRITICAL_PERCENT = 80

# Значения по умолчанию при недоступности сервисов
EMPTY_HOST_STATS = {"total": 0, "online": 0, "offline": 0, "avg_cpu": 0}


def _get_printer_client() -> PrinterMonitorClient:
    return PrinterMonitorClient(current_app.config["PRINTER_API_URL"])


def _get_host_client() -> HostMonitorClient:
    return HostMonitorClient(current_app.config["HOST_API_URL"])


def _get_logspy_client() -> LogSpyClient:
    return LogSpyClient(current_app.config["LOGSPY_API_URL"])


def _run_task(
    name: str,
    fn: Callable[[], Any],
    default: Any,
    service: str,
) -> tuple[Any, str | None]:
    """Выполнить запрос к сервису.

    Args:
        name: Имя задачи (для лога).
        fn: Функция запроса.
        default: Значение при ошибке.
        service: Имя сервиса (для баннера недоступности).

    Returns:
        (результат, None) при успехе или (default, service) при ошибке.
    """
    try:
        return fn(), None
    except Exception as e:
        logger.error("%s API (%s) error: %s", service, name, e)
        return default, service


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
    printer_client = _get_printer_client()
    host_client = _get_host_client()
    logspy_client = _get_logspy_client()
    netcerber_client = NetCerberClient(current_app.config["NETCERBER_API_URL"])

    # Независимые запросы выполняем параллельно, чтобы страница не ждала
    # каждый сервис по очереди (при недоступном сервисе — до 20 секунд).
    tasks: dict[str, tuple[Callable[[], Any], Any, str]] = {
        "printers": (printer_client.get_printers, [], "Printer Monitor"),
        "threshold": (printer_client.get_threshold, {}, "Printer Monitor"),
        "host_stats": (host_client.get_stats, EMPTY_HOST_STATS, "Host Monitor"),
        "hosts": (
            lambda: host_client.get_hosts(page=1, limit=500),
            {}, "Host Monitor",
        ),
        "ad_stats": (logspy_client.get_ad_stats, {}, "LogSpy"),
        "logs": (logspy_client.get_logs, [], "LogSpy"),
        "stoplist": (logspy_client.get_stoplist, {}, "LogSpy"),
        "netcerber_devices": (
            lambda: netcerber_client.get_devices(limit=500),
            {}, "NetCerber",
        ),
        "netcerber_alerts": (
            lambda: netcerber_client.get_alerts(limit=1),
            {}, "NetCerber",
        ),
    }

    results: dict[str, Any] = {}
    unavailable: set[str] = set()
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {
            pool.submit(_run_task, name, fn, default, service): name
            for name, (fn, default, service) in tasks.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            results[name], failed_service = future.result()
            if failed_service:
                unavailable.add(failed_service)

    printers = results["printers"]
    printer_count = len(printers)
    toner_threshold = results["threshold"].get("threshold", 20)
    low_toner = sum(
        1 for p in printers
        if _has_toner(p)
        and p.get("toner_percentage_value", 0) < toner_threshold
    )
    critical_printers = _critical_printers(printers, toner_threshold)

    host_stats = results["host_stats"]
    host_count = host_stats.get("total", 0)
    hosts_online = host_stats.get("online", 0)
    hosts_offline = host_stats.get("offline", 0)
    critical_hosts = _critical_hosts(results["hosts"].get("items", []))

    ad_stats = results["ad_stats"]
    ad_users_count = ad_stats.get("enabled_users", 0)
    ad_computers_count = ad_stats.get("total_computers", 0)
    ad_sync_status = ad_stats.get("sync_status", "not_started")

    # Summary зависит от списка логов — выполняется после параллельного блока.
    log_files = results["logs"]
    blocked_count = 0
    total_requests = 0
    unique_users = 0
    if log_files:
        try:
            summary = logspy_client.get_summary(log_files[0]["name"])
            ip_summary = summary.get("summary", {})
            for item in ip_summary.values():
                blocked_count += item.get("blocked_visits", 0)
                total_requests += item.get("total_visits", 0)
            unique_users = len(ip_summary)
        except Exception as e:
            logger.error("LogSpy API (logs/summary) error: %s", e)
            unavailable.add("LogSpy")

    stoplist_count = results["stoplist"].get("total", 0)

    # NetCerber: счётчики подозрительных устройств и топ новых.
    nc_devices = results["netcerber_devices"].get("items", [])
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
    nc_alerts_total = results["netcerber_alerts"].get("total", 0)

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
        unavailable_services=sorted(unavailable),
    )
