"""Маршруты Users — мониторинг пользователей AD.

Модуль содержит маршруты для просмотра пользователей Active Directory,
их интернет-активности и заблокированных запросов.
"""

import logging
import re

from flask import Blueprint, render_template, request, current_app, jsonify

from app.api.logspy_client import LogSpyClient

users_bp = Blueprint("users", __name__)

logger = logging.getLogger(__name__)


def _get_logspy_client() -> LogSpyClient:
    return LogSpyClient(current_app.config["LOGSPY_API_URL"])


def _get_current_log(client: LogSpyClient) -> str:
    logs = client.get_logs()
    if logs:
        return logs[0]["name"]
    return ""


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

    unavailable_services = []
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
        current_log = _get_current_log(client)
    except Exception as e:
        current_log = ""
        logger.error("LogSpy API (logs list) error: %s", e)
        unavailable_services.append("LogSpy")

    user_upn = _get_user_upn(user)

    activity = None
    blocked_records = []
    all_records = []

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
            stats = all_data.get("stats", {})

            blocked_records = [
                r for r in all_records if r.get("is_blocked")
            ]
            domains = list({r["domain"] for r in all_records if r.get("domain")})
            total_traffic = sum(r.get("size", 0) for r in all_records)

            def _fmt_size(b: int) -> str:
                for unit in ("B", "KB", "MB", "GB"):
                    if b < 1024:
                        return f"{b:.1f} {unit}"
                    b /= 1024
                return f"{b:.1f} TB"

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
                "total_traffic_formatted": _fmt_size(total_traffic),
                "blocked_requests": blocked_total,
                "domains_visited": sorted(domains),
                "last_activity": last_activity,
                "records_shown": len(all_records),
                "blocked_shown": len(blocked_records),
            }
        except Exception as e:
            logger.error("LogSpy API (user activity=%s) error: %s", username, e)
            unavailable_services.append("LogSpy")

    return render_template(
        "user_detail.html",
        user=user,
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
            log_file = _get_current_log(client)
        except Exception as e:
            logger.error("LogSpy API (logs list) error: %s", e)
            return jsonify({"error": "No log file"}), 400

    try:
        data = client.get_data(
            log_file,
            user=user_upn,
            page=int(request.args.get("page", 1)),
            limit=int(request.args.get("limit", 100)),
            search=request.args.get("search"),
            status=request.args.get("status"),
            sort=request.args.get("sort", "time_desc"),
        )
        return jsonify(data)
    except Exception as e:
        logger.error("LogSpy API (user activity=%s) error: %s", username, e)
        return jsonify({"error": str(e)}), 500
