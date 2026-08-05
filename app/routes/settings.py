"""Маршруты настроек.

Модуль содержит маршруты для управления настройками сервисов.
"""

import logging

from flask import Blueprint, render_template, current_app, request, jsonify

from app.api.printer_client import PrinterMonitorClient

settings_bp = Blueprint("settings", __name__)

logger = logging.getLogger(__name__)


def _get_printer_client() -> PrinterMonitorClient:
    """Создать клиент Printer Monitor API.

    Returns:
        Экземпляр клиента.
    """
    return PrinterMonitorClient(current_app.config["PRINTER_API_URL"])


@settings_bp.route("/")
def settings_page() -> str:
    """Страница настроек.

    Returns:
        HTML-шаблон настроек.
    """
    client = _get_printer_client()

    unavailable_services = []
    try:
        threshold = client.get_threshold()
    except Exception as e:
        threshold = {"threshold": 20}
        logger.error("Printer Monitor API (threshold) error: %s", e)
        unavailable_services.append("Printer Monitor")

    try:
        interval = client.get_check_interval()
    except Exception as e:
        interval = {"interval": 300}
        logger.error("Printer Monitor API (interval) error: %s", e)
        unavailable_services.append("Printer Monitor")

    try:
        status = client.get_status()
    except Exception as e:
        status = {}
        logger.error("Printer Monitor API (status) error: %s", e)
        unavailable_services.append("Printer Monitor")

    return render_template(
        "settings.html",
        threshold=threshold.get("threshold", 20),
        interval=interval.get("interval", 300),
        status=status,
        unavailable_services=unavailable_services,
    )


@settings_bp.route("/htmx/threshold", methods=["PUT"])
def update_threshold():
    """HTMX: обновить порог уведомления.

    Returns:
        HTML-фрагмент с результатом.
    """
    client = _get_printer_client()
    threshold = request.form.get("threshold", 20, type=int)

    try:
        result = client.set_threshold(threshold)
        return render_template(
            "partials/_settings_result.html",
            success=True,
            message=f"Порог установлен: {result['threshold']}%"
        )
    except Exception as e:
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
    client = _get_printer_client()
    interval = request.form.get("interval", 300, type=int)

    try:
        result = client.set_check_interval(interval)
        return render_template(
            "partials/_settings_result.html",
            success=True,
            message=f"Интервал установлен: {result['interval']} сек."
        )
    except Exception as e:
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
    client = _get_printer_client()
    try:
        status = client.get_status()
    except Exception as e:
        status = {"status": "Недоступен"}
        logger.error("Printer Monitor API (status) error: %s", e)

    return render_template("partials/_service_status.html", status=status)
