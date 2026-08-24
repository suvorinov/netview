"""Маршруты настроек.

Модуль содержит маршруты для управления настройками сервисов.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from flask import Blueprint, current_app, render_template, request
from requests import RequestException

from app.api.factories import (
    get_host_client,
    get_logspy_client,
    get_netcerber_client,
    get_printer_client,
)

settings_bp = Blueprint("settings", __name__)

logger = logging.getLogger(__name__)

# Границы значений формы (серверная валидация): клиентские min/max
# в HTML легко обходятся запросом напрямую.
THRESHOLD_MIN, THRESHOLD_MAX = 0, 100
INTERVAL_MIN, INTERVAL_MAX = 10, 86400  # от 10 секунд до суток


@settings_bp.route("/")
def settings_page() -> str:
    """Страница настроек.

    Returns:
        HTML-шаблон настроек.
    """
    client = get_printer_client()

    unavailable_services = []
    try:
        threshold = client.get_threshold()
    except RequestException as e:
        threshold = {"threshold": 20}
        logger.error("Printer Monitor API (threshold) error: %s", e)
        unavailable_services.append("Printer Monitor")

    try:
        interval = client.get_check_interval()
    except RequestException as e:
        interval = {"interval": 300}
        logger.error("Printer Monitor API (interval) error: %s", e)
        unavailable_services.append("Printer Monitor")

    try:
        status = client.get_status()
    except RequestException as e:
        status = {}
        logger.error("Printer Monitor API (status) error: %s", e)
        unavailable_services.append("Printer Monitor")

    return render_template(
        "settings.html",
        threshold=threshold.get("threshold", 20),
        interval=interval.get("interval", 300),
        status=status,
        services=_services_health(),
        unavailable_services=unavailable_services,
    )


def _services_health() -> list[dict[str, Any]]:
    """Проверить доступность всех внутренних сервисов.

    Каждый сервис опрашивается параллельно; при недоступности
    возвращается ok=False, страница настроек не падает.

    Returns:
        Список {name, url, ok, summary} для карточек «Сервисы».
    """
    probes: dict[str, tuple[str, Callable[[], Any], Callable[[Any], str]]] = {
        "Printer Monitor": (
            "PRINTER_API_URL",
            get_printer_client().get_status,
            lambda d: (
                f"{d.get('online_printers', 0)}/{d.get('total_printers', 0)}"
                " принтеров онлайн"
            ),
        ),
        "Host Monitor": (
            "HOST_API_URL",
            get_host_client().get_stats,
            lambda d: (
                f"{d.get('online', 0)}/{d.get('total', 0)} хостов онлайн"
            ),
        ),
        "LogSpy": (
            "LOGSPY_API_URL",
            get_logspy_client().get_health,
            lambda d: f"статус: {d.get('status', 'ok')}",
        ),
        "NetCerber": (
            "NETCERBER_API_URL",
            get_netcerber_client().get_health,
            lambda d: ", ".join(
                f"{k}: {v}" for k, v in d.items() if k != "status"
            ) or f"статус: {d.get('status', 'ok')}",
        ),
    }

    def check(name: str, url: str, fn: Callable[[], Any], fmt: Callable[[Any], str]) -> dict[str, Any]:
        try:
            data = fn()
        except RequestException as e:
            logger.error("%s health check error: %s", name, e)
            return {"name": name, "url": url, "ok": False, "summary": "Недоступен"}
        # Форматирование вне try: ошибка формы данных — наш баг,
        # а не «сервис недоступен».
        return {"name": name, "url": url, "ok": True, "summary": fmt(data)}

    # URL читаем в контексте запроса: в воркер-потоках current_app
    # недоступен (контекст приложения привязан к потоку).
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        futures = {
            pool.submit(
                check, name, current_app.config[url_key], fn, fmt
            ): name
            for name, (url_key, fn, fmt) in probes.items()
        }
        return [f.result() for f in as_completed(futures)]


@settings_bp.route("/htmx/threshold", methods=["PUT"])
def update_threshold():
    """HTMX: обновить порог уведомления.

    Returns:
        HTML-фрагмент с результатом.
    """
    threshold = request.form.get("threshold", 20, type=int)
    # type=int при мусоре во входе тихо вернёт default, поэтому
    # отдельной проверки "не число" не нужно — только диапазон.
    if not THRESHOLD_MIN <= threshold <= THRESHOLD_MAX:
        return render_template(
            "partials/_settings_result.html",
            success=False,
            message=(
                f"Порог должен быть от {THRESHOLD_MIN} "
                f"до {THRESHOLD_MAX}%"
            ),
        )

    client = get_printer_client()
    try:
        result = client.set_threshold(threshold)
        return render_template(
            "partials/_settings_result.html",
            success=True,
            message=f"Порог установлен: {result['threshold']}%"
        )
    except RequestException as e:
        logger.error("Printer Monitor API (set threshold) error: %s", e)
        return render_template(
            "partials/_settings_result.html",
            success=False,
            message=f"Ошибка: {str(e)}"
        )


@settings_bp.route("/htmx/interval", methods=["PUT"])
def update_interval():
    """HTMX: обновить интервал проверки.

    Returns:
        HTML-фрагмент с результатом.
    """
    interval = request.form.get("interval", 300, type=int)
    if not INTERVAL_MIN <= interval <= INTERVAL_MAX:
        return render_template(
            "partials/_settings_result.html",
            success=False,
            message=(
                f"Интервал должен быть от {INTERVAL_MIN} "
                f"до {INTERVAL_MAX} сек."
            ),
        )

    client = get_printer_client()
    try:
        result = client.set_check_interval(interval)
        return render_template(
            "partials/_settings_result.html",
            success=True,
            message=f"Интервал установлен: {result['interval']} сек."
        )
    except RequestException as e:
        logger.error("Printer Monitor API (set interval) error: %s", e)
        return render_template(
            "partials/_settings_result.html",
            success=False,
            message=f"Ошибка: {str(e)}"
        )


@settings_bp.route("/htmx/status")
def htmx_status():
    """HTMX: получить статус сервиса.

    Returns:
        HTML-фрагмент со статусом.
    """
    client = get_printer_client()
    try:
        status = client.get_status()
    except RequestException as e:
        status = {"status": "Недоступен"}
        logger.error("Printer Monitor API (status) error: %s", e)

    return render_template("partials/_service_status.html", status=status)
