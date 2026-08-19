"""Маршруты Logs — просмотр логов Squid.

Модуль содержит маршруты для просмотра, поиска и фильтрации
записей логов прокси-сервера Squid.
"""

import logging

from flask import Blueprint, current_app, jsonify, render_template, request

from app.api.logspy_client import LogSpyClient

logs_bp = Blueprint("logs", __name__)

logger = logging.getLogger(__name__)


def _get_logspy_client() -> LogSpyClient:
    return LogSpyClient(current_app.config["LOGSPY_API_URL"])


@logs_bp.route("/")
def index():
    client = _get_logspy_client()
    log_file = request.args.get("file", "")
    search = request.args.get("search", "").strip()
    user_filter = request.args.get("user", "").strip()
    if user_filter and "@" not in user_filter:
        user_filter = f"{user_filter}@{current_app.config['AD_DOMAIN']}"
    status_filter = request.args.get("status", "").strip()
    sort = request.args.get("sort", "time_desc")
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 100, type=int)

    unavailable_services = []
    try:
        log_files = client.get_logs()
    except Exception as e:
        log_files = []
        logger.error("LogSpy API (logs list) error: %s", e)
        unavailable_services.append("LogSpy")

    if not log_file and log_files:
        log_file = log_files[0]["name"]

    records = []
    stats = {}
    pagination = {"page": 1, "limit": limit, "total_records": 0, "total_pages": 0}

    if log_file:
        try:
            data = client.get_data(
                log_file,
                page=page,
                limit=limit,
                search=search or None,
                user=user_filter or None,
                status=status_filter or None,
                sort=sort,
            )
            raw_records = data.get("records", [])
            records = [r for r in raw_records if r.get("user") and r["user"] != "-"]
            stats = data.get("stats", {})
            pagination = data.get("pagination", pagination)
        except Exception as e:
            logger.error("LogSpy API (logs data) error: %s", e)
            unavailable_services.append("LogSpy")

    return render_template(
        "logs.html",
        log_files=log_files,
        log_file=log_file,
        records=records,
        stats=stats,
        pagination=pagination,
        search=search,
        user_filter=user_filter,
        status_filter=status_filter,
        sort=sort,
        unavailable_services=unavailable_services,
    )


@logs_bp.route("/api/file-info")
def api_file_info():
    client = _get_logspy_client()
    log_file = request.args.get("file", "")
    if not log_file:
        return ""

    try:
        info = client.get_file_info(log_file, sample_size=500)
        return render_template("partials/_file_info.html", file_info=info)
    except Exception as e:
        logger.error("LogSpy API (file info) error: %s", e)
        return '<span class="text-gray-400 text-xs">Информация недоступна</span>'


@logs_bp.route("/api/data")
def api_data():
    client = _get_logspy_client()
    log_file = request.args.get("file", "")
    if not log_file:
        return jsonify({"error": "file parameter required"}), 400

    try:
        data = client.get_data(
            log_file,
            page=request.args.get("page", 1, type=int),
            limit=request.args.get("limit", 100, type=int),
            search=request.args.get("search"),
            user=request.args.get("user"),
            status=request.args.get("status"),
            sort=request.args.get("sort", "time_desc"),
        )
        return jsonify(data)
    except Exception as e:
        logger.error("LogSpy API (data) error: %s", e)
        return jsonify({"error": str(e)}), 500


@logs_bp.route("/api/summary")
def api_summary():
    client = _get_logspy_client()
    log_file = request.args.get("file", "")
    if not log_file:
        return jsonify({"error": "file parameter required"}), 400

    try:
        data = client.get_summary(log_file)
        return jsonify(data)
    except Exception as e:
        logger.error("LogSpy API (summary) error: %s", e)
        return jsonify({"error": str(e)}), 500
