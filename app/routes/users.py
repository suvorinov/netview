"""Маршруты Users — мониторинг пользователей AD.

Модуль содержит маршруты для просмотра пользователей Active Directory,
их интернет-активности и заблокированных запросов.
"""

import logging
import re

from flask import Blueprint, current_app, jsonify, render_template, request

from app.api.logspy_client import LogSpyClient
from app.utils import format_duration, human_size

users_bp = Blueprint("users", __name__)

logger = logging.getLogger(__name__)


def _get_logspy_client() -> LogSpyClient:
    return LogSpyClient(current_app.config["LOGSPY_API_URL"])


def _get_user_upn(user: dict) -> str:
    """Получить UPN (user@domain) из данных AD-пользователя.

    Извлекает домен из distinguishedName и формирует UPN
    для поиска в логах Squid.

    Args:
        user: Словарь с данными AD-пользователя.

    Returns:
        Строка вида 'username@DOMAIN' или просто username.
    """
    sam = user.get("sAMAccountName", "")
    dn = user.get("distinguishedName", "")

    match = re.search(r"DC=([^,]+)", dn, re.IGNORECASE)
    if match:
        domain_parts = re.findall(r"DC=([^,]+)", dn, re.IGNORECASE)
        domain = ".".join(domain_parts).upper()
        return f"{sam}@{domain}"

    return sam


@users_bp.route("/")
def index():
    client = _get_logspy_client()
    search = request.args.get("search", "").strip()
    ou_filter = request.args.get("ou", "").strip()
    dept_filter = request.args.get("department", "").strip()
    view = request.args.get("view", "users")

    unavailable_services = []

    # Вкладка «Компьютеры»: список рабочих станций и серверов AD.
    if view == "computers":
        try:
            computers = client.get_ad_computers()
        except Exception as e:
            computers = []
            logger.error("LogSpy API (ad computers) error: %s", e)
            unavailable_services.append("LogSpy")
        return render_template(
            "users.html",
            view="computers",
            computers=computers,
            unavailable_services=unavailable_services,
        )

    try:
        users = client.get_ad_users(
            search=search or None,
            ou=ou_filter or None,
            department=dept_filter or None,
            enabled_only=True,
        )
    except Exception as e:
        users = []
        logger.error("LogSpy API (ad users) error: %s", e)
        unavailable_services.append("LogSpy")

    try:
        ous = client.get_ad_ous()
    except Exception as e:
        ous = []
        logger.error("LogSpy API (ad ous) error: %s", e)
        unavailable_services.append("LogSpy")

    return render_template(
        "users.html",
        view="users",
        users=users,
        ous=ous,
        search=search,
        ou_filter=ou_filter,
        dept_filter=dept_filter,
        unavailable_services=unavailable_services,
    )


@users_bp.route("/<username>")
def detail(username: str):
    client = _get_logspy_client()
    unavailable_services = []

    try:
        user = client.get_ad_user(username)
    except Exception as e:
        logger.error("LogSpy API (ad user=%s) error: %s", username, e)
        return render_template("errors/404.html", message="Пользователь не найден"), 404

    try:
        current_log = client.get_current_log()
    except Exception as e:
        current_log = ""
        logger.error("LogSpy API (logs list) error: %s", e)
        unavailable_services.append("LogSpy")

    user_upn = _get_user_upn(user)

    activity = None
    blocked_records = []
    all_records = []
    all_data: dict = {}

    if current_log:
        try:
            all_data = client.get_data(
                current_log, user=user_upn, limit=500
            )
            raw_records = all_data.get("records", [])
            all_records = [
                r for r in raw_records
                if r.get("user") and r["user"] != "-"
            ]

            blocked_records = [
                r for r in all_records if r.get("is_blocked")
            ]
        except Exception as e:
            logger.error("LogSpy API (user records=%s) error: %s", username, e)
            unavailable_services.append("LogSpy")

        # Точная статистика за весь файл — серверная агрегация LogSpy.
        server_stats = None
        try:
            server_stats = client.get_ad_user_activity(user_upn, current_log)
        except Exception as e:
            logger.error("LogSpy API (user activity=%s) error: %s", username, e)
            unavailable_services.append("LogSpy")

        if server_stats:
            activity = {
                "username": username,
                "total_requests": server_stats.get("total_requests", 0),
                "total_traffic": server_stats.get("total_traffic", 0),
                "total_traffic_formatted": (
                    server_stats.get("total_traffic_formatted")
                    or human_size(server_stats.get("total_traffic", 0))
                ),
                "blocked_requests": server_stats.get("blocked_requests", 0),
                "time_on_blocked": server_stats.get("time_on_blocked", 0),
                "time_on_blocked_formatted": format_duration(
                    server_stats.get("time_on_blocked", 0)
                ),
                "domains_visited": sorted(
                    server_stats.get("domains_visited") or []
                ),
                "last_activity": server_stats.get("last_activity", ""),
                "records_shown": len(all_records),
                "blocked_shown": len(blocked_records),
            }
        else:
            # Фолбэк: оценка по последним 500 записям выборки.
            domains = sorted({r["domain"] for r in all_records if r.get("domain")})
            total_traffic = sum(r.get("size", 0) for r in all_records)

            last_activity = ""
            if all_records:
                last_activity = all_records[0].get("timestamp_human", "")

            total_requests = (all_data.get("pagination", {}) or {}).get(
                "total_records", len(all_records)
            )

            blocked_total = len(blocked_records)
            try:
                blocked_data = client.get_data(
                    current_log, user=user_upn, status="blocked", limit=1
                )
                blocked_total = (blocked_data.get("pagination", {}) or {}).get(
                    "total_records", blocked_total
                )
            except Exception as e:
                logger.error(
                    "LogSpy API (user blocked stats=%s) error: %s", username, e
                )

            activity = {
                "username": username,
                "total_requests": total_requests,
                "total_traffic": total_traffic,
                "total_traffic_formatted": human_size(total_traffic),
                "blocked_requests": blocked_total,
                "time_on_blocked": None,
                "time_on_blocked_formatted": "—",
                "domains_visited": domains,
                "last_activity": last_activity,
                "records_shown": len(all_records),
                "blocked_shown": len(blocked_records),
            }

    return render_template(
        "user_detail.html",
        user=user,
        user_upn=user_upn,
        activity=activity,
        blocked_records=blocked_records,
        all_records=all_records,
        current_log=current_log,
        unavailable_services=unavailable_services,
    )


@users_bp.route("/api/<username>/activity")
def api_user_activity(username: str):
    client = _get_logspy_client()

    try:
        user = client.get_ad_user(username)
        user_upn = _get_user_upn(user)
    except Exception as e:
        logger.error("LogSpy API (ad user=%s) error: %s", username, e)
        user_upn = username

    log_file = request.args.get("log", "")
    if not log_file:
        try:
            log_file = client.get_current_log()
        except Exception as e:
            logger.error("LogSpy API (logs list) error: %s", e)
            return jsonify({"error": "No log file"}), 400

    try:
        data = client.get_data(
            log_file,
            user=user_upn,
            page=request.args.get("page", 1, type=int),
            limit=request.args.get("limit", 100, type=int),
            search=request.args.get("search"),
            status=request.args.get("status"),
            sort=request.args.get("sort", "time_desc"),
        )
        return jsonify(data)
    except Exception as e:
        logger.error("LogSpy API (user activity=%s) error: %s", username, e)
        return jsonify({"error": str(e)}), 500
