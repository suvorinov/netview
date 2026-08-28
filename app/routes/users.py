"""Маршруты Users — мониторинг пользователей AD.

Модуль содержит маршруты для просмотра пользователей Active Directory,
их интернет-активности и заблокированных запросов.
"""

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from flask import (
    Blueprint,
    Response,
    jsonify,
    render_template,
    request,
)
from requests import RequestException

from app.api.factories import get_logspy_client
from app.utils import format_duration, human_size

users_bp = Blueprint("users", __name__)

logger = logging.getLogger(__name__)


def _run_parallel(tasks: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    """Выполнить независимые запросы к сервису параллельно.

    Страница пользователя делает до четырёх запросов к LogSpy;
    последовательно на медленном сервисе это 1–3 секунды ожидания.
    Параллельный запуск сокращает время страницы до одного таймаута.

    Args:
        tasks: {имя задачи: функция запроса}. Имя попадает в лог.

    Returns:
        {имя задачи: результат}; при сетевой ошибке результат None
        (ошибка залогирована). Не-сетевые исключения не глушатся:
        ошибка формы данных — наш баг и должен падать громко.
    """
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except RequestException as e:
                logger.error("LogSpy API (%s) error: %s", name, e)
                results[name] = None
    return results


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
    client = get_logspy_client()
    search = request.args.get("search", "").strip()
    ou_filter = request.args.get("ou", "").strip()
    dept_filter = request.args.get("department", "").strip()
    view = request.args.get("view", "users")

    # Множество: несколько упавших запросов к одному сервису не должны
    # дублировать баннер недоступности.
    unavailable_services: set[str] = set()

    # Вкладка «Компьютеры»: список рабочих станций и серверов AD.
    if view == "computers":
        try:
            computers = client.get_ad_computers()
        except RequestException as e:
            computers = []
            logger.error("LogSpy API (ad computers) error: %s", e)
            unavailable_services.add("LogSpy")
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
    except RequestException as e:
        users = []
        logger.error("LogSpy API (ad users) error: %s", e)
        unavailable_services.add("LogSpy")

    try:
        ous = client.get_ad_ous()
    except RequestException as e:
        ous = []
        logger.error("LogSpy API (ad ous) error: %s", e)
        unavailable_services.add("LogSpy")

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
    client = get_logspy_client()
    unavailable_services: set[str] = set()

    # Профиль и текущий лог-файл независимы — параллельно.
    first = _run_parallel({
        "ad_user": lambda: client.get_ad_user(username),
        "logs_list": client.get_current_log,
    })
    user = first["ad_user"]
    if user is None:
        # LogSpy не отдал профиль (в т.ч. 404) — страницы пользователя нет.
        return render_template("errors/404.html", message="Пользователь не найден"), 404
    if first["logs_list"] is None:
        unavailable_services.add("LogSpy")
    current_log = first["logs_list"] or ""

    user_upn = _get_user_upn(user)

    activity = None
    blocked_records = []
    all_records = []
    all_data: dict = {}

    if current_log:
        # Записи за выборку и серверная статистика независимы — параллельно.
        second = _run_parallel({
            "user_records": lambda: client.get_data(
                current_log, user=user_upn, limit=500
            ),
            "user_activity": lambda: client.get_ad_user_activity(
                user_upn, current_log
            ),
        })
        if any(result is None for result in second.values()):
            unavailable_services.add("LogSpy")

        all_data = second["user_records"] or {}
        # Разбор ответа вне try: ошибка формы данных — наш баг,
        # а не «сервис недоступен».
        raw_records = all_data.get("records", [])
        all_records = [
            r for r in raw_records
            if r.get("user") and r["user"] != "-"
        ]
        blocked_records = [
            r for r in all_records if r.get("is_blocked")
        ]

        server_stats = second["user_activity"]
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
            except RequestException as e:
                logger.error(
                    "LogSpy API (user blocked stats=%s) error: %s", username, e
                )
            else:
                blocked_total = (blocked_data.get("pagination", {}) or {}).get(
                    "total_records", blocked_total
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

    template = (
        "partials/_user_detail.html"
        if request.headers.get("HX-Request")
        else "user_detail.html"
    )
    return render_template(
        template,
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
    client = get_logspy_client()

    try:
        user = client.get_ad_user(username)
        user_upn = _get_user_upn(user)
    except RequestException as e:
        logger.error("LogSpy API (ad user=%s) error: %s", username, e)
        user_upn = username

    log_file = request.args.get("log", "")
    if not log_file:
        try:
            log_file = client.get_current_log()
        except RequestException as e:
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
    except RequestException as e:
        logger.error("LogSpy API (user activity=%s) error: %s", username, e)
        return jsonify({"error": "LogSpy недоступен"}), 500


def _domain_stats(records: list[dict]) -> list[dict]:
    """Сводка блокировок по доменам: повторные визиты суммируются.

    Args:
        records: Заблокированные записи из LogSpy.

    Returns:
        [{"domain", "count", "size"}], отсортировано по числу
        посещений (по убыванию); при равенстве — по трафику.
    """
    stats: dict[str, dict[str, int]] = {}
    for r in records:
        domain = r.get("domain")
        if not domain:
            continue
        entry = stats.setdefault(domain, {"count": 0, "size": 0})
        entry["count"] += 1
        entry["size"] += r.get("size") or 0
    return sorted(
        ({"domain": d, **v} for d, v in stats.items()),
        key=lambda e: (e["count"], e["size"]),
        reverse=True,
    )


def _safe_filename(name: str) -> str:
    """Оставить в имени файла только символы, допустимые в заголовке.

    Username приходит из URL: кавычки/переводы строк в заголовке
    Content-Disposition недопустимы.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "user"


@users_bp.route("/<username>/export/blocked")
def export_blocked_report(username: str):
    """HTML-отчёт о посещении заблокированных ресурсов.

    Записи берутся напрямую из LogSpy с серверным фильтром
    status="blocked", поэтому отчёт не зависит от того, что
    показано на странице пользователя.

    Помимо списка запросов отчёт содержит сводку по доменам
    (повторные посещения и трафик просуммированы) и время,
    проведённое на заблокированных ресурсах — серверная
    агрегация LogSpy за весь файл журнала.
    """
    client = get_logspy_client()

    try:
        user = client.get_ad_user(username)
    except RequestException as e:
        logger.error("LogSpy API (ad user=%s) error: %s", username, e)
        return render_template("errors/404.html", message="Пользователь не найден"), 404

    user_upn = _get_user_upn(user)

    try:
        log_file = client.get_current_log()
    except RequestException as e:
        log_file = ""
        logger.error("LogSpy API (logs list) error: %s", e)

    records: list[dict] = []
    blocked_total = 0
    time_on_blocked: float | None = None
    if log_file:
        # Записи блокировок и серверная статистика независимы — параллельно.
        results = _run_parallel({
            "blocked_records": lambda: client.get_data(
                log_file, user=user_upn, status="blocked", limit=500
            ),
            "activity": lambda: client.get_ad_user_activity(user_upn, log_file),
        })

        data = results["blocked_records"]
        if data is not None:
            records = data.get("records", [])
            # Истинное число блокировок за файл — из пагинации LogSpy,
            # даже если записей больше, чем помещается в отчёт.
            blocked_total = (data.get("pagination", {}) or {}).get(
                "total_records", len(records)
            )

        server_stats = results["activity"]
        if server_stats:
            time_on_blocked = server_stats.get("time_on_blocked")

    domain_rows = _domain_stats(records)
    blocked_traffic = sum(r.get("size", 0) for r in records if r.get("size"))

    return Response(
        render_template(
            "exports/blocked_report.html",
            user=user,
            user_upn=user_upn,
            log_file=log_file,
            records=records,
            blocked_total=blocked_total,
            domain_rows=domain_rows,
            blocked_traffic=blocked_traffic,
            time_on_blocked_formatted=(
                format_duration(time_on_blocked)
                if time_on_blocked is not None
                else "—"
            ),
            generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        ),
        mimetype="text/html",
        headers={
            "Content-Disposition": (
                f"attachment; filename=blocked_{_safe_filename(username)}.html"
            )
        },
    )
