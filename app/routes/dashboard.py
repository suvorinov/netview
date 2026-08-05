"""Маршруты Dashboard.

Модуль содержит маршруты для главной страницы Dashboard.
"""

import logging

from flask import Blueprint, render_template, current_app

from app.api.printer_client import PrinterMonitorClient
from app.api.host_client import HostMonitorClient
from app.api.logspy_client import LogSpyClient

dashboard_bp = Blueprint("dashboard", __name__)

logger = logging.getLogger(__name__)


def _get_printer_client() -> PrinterMonitorClient:
    return PrinterMonitorClient(current_app.config["PRINTER_API_URL"])


def _get_host_client() -> HostMonitorClient:
    return HostMonitorClient(current_app.config["HOST_API_URL"])


def _get_logspy_client() -> LogSpyClient:
    return LogSpyClient(current_app.config["LOGSPY_API_URL"])


@dashboard_bp.route("/")
def index() -> str:
    printer_client = _get_printer_client()
    host_client = _get_host_client()
    logspy_client = _get_logspy_client()

    unavailable_services = []

    # Принтеры
    printers = []
    printer_count = 0
    low_toner = 0
    try:
        printers = printer_client.get_printers()
        printer_count = len(printers)
        low_toner = sum(
            1 for p in printers
            if p.get("toner_percentage_value", 100) < 20
        )
    except Exception as e:
        printer_count = 0
        low_toner = 0
        logger.error("Printer Monitor API error: %s", e)
        unavailable_services.append("Printer Monitor")

    # Хосты
    host_stats = {"total": 0, "online": 0, "offline": 0, "avg_cpu": 0}
    host_count = 0
    hosts_online = 0
    hosts_offline = 0
    try:
        host_stats = host_client.get_stats()
        host_count = host_stats.get("total", 0)
        hosts_online = host_stats.get("online", 0)
        hosts_offline = host_stats.get("offline", 0)
    except Exception as e:
        host_count = 0
        hosts_online = 0
        hosts_offline = 0
        logger.error("Host Monitor API error: %s", e)
        unavailable_services.append("Host Monitor")

    # LogSpy — AD
    logspy_ok = True
    ad_stats = {}
    ad_users_count = 0
    ad_computers_count = 0
    ad_sync_status = "not_started"
    try:
        ad_stats = logspy_client.get_ad_stats()
        ad_users_count = ad_stats.get("enabled_users", 0)
        ad_computers_count = ad_stats.get("total_computers", 0)
        ad_sync_status = ad_stats.get("sync_status", "not_started")
    except Exception as e:
        logspy_ok = False
        logger.error("LogSpy API (AD stats) error: %s", e)

    # LogSpy — Логи
    log_files = []
    blocked_count = 0
    total_requests = 0
    unique_users = 0
    stoplist_count = 0
    try:
        log_files = logspy_client.get_logs()
        if log_files:
            current_log = log_files[0]["name"]
            summary = logspy_client.get_summary(current_log)
            ip_summary = summary.get("summary", {})
            for item in ip_summary.values():
                blocked_count += item.get("blocked_visits", 0)
                total_requests += item.get("total_visits", 0)
            unique_users = len(ip_summary)
    except Exception as e:
        logspy_ok = False
        logger.error("LogSpy API (logs/summary) error: %s", e)

    # LogSpy — Стоп-лист
    try:
        stoplist = logspy_client.get_stoplist()
        stoplist_count = stoplist.get("total", 0)
    except Exception as e:
        logspy_ok = False
        logger.error("LogSpy API (stoplist) error: %s", e)

    if not logspy_ok:
        unavailable_services.append("LogSpy")

    return render_template(
        "dashboard.html",
        printer_count=printer_count,
        low_toner=low_toner,
        printers=printers,
        host_count=host_count,
        hosts_online=hosts_online,
        hosts_offline=hosts_offline,
        stats=host_stats,
        ad_users_count=ad_users_count,
        ad_computers_count=ad_computers_count,
        ad_sync_status=ad_sync_status,
        log_files_count=len(log_files),
        blocked_count=blocked_count,
        total_requests=total_requests,
        unique_users=unique_users,
        stoplist_count=stoplist_count,
        unavailable_services=unavailable_services,
    )
