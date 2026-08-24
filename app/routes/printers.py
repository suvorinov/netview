"""Маршруты принтеров.

Модуль содержит маршруты для работы с принтерами.
"""

import logging

from flask import Blueprint, current_app, render_template, request
from requests import RequestException

from app.api.printer_client import PrinterMonitorClient
from app.utils import sort_items

printers_bp = Blueprint("printers", __name__)

logger = logging.getLogger(__name__)

# Карта полей для сортировки
SORT_FIELDS: dict[str, str] = {
    "ip": "ip",
    "toner": "toner_percentage_value",
    "print_count": "print_count",
}


def _get_client() -> PrinterMonitorClient:
    """Создать клиент Printer Monitor API.

    Returns:
        Экземпляр клиента.
    """
    return PrinterMonitorClient(current_app.config["PRINTER_API_URL"])


def _get_toner_threshold(client: PrinterMonitorClient) -> int:
    """Порог критического тонера из API (по умолчанию 20)."""
    try:
        data = client.get_threshold()
    except RequestException as e:
        logger.error("Printer Monitor threshold error: %s", e)
        return 20
    return data.get("threshold", 20)


@printers_bp.route("/")
def printers_list() -> str:
    """Страница списка принтеров.

    Returns:
        HTML-шаблон со списком принтеров.
    """
    client = _get_client()
    unavailable_services = []
    try:
        printers = client.get_printers()
    except RequestException as e:
        printers = []
        logger.error("Printer Monitor API error: %s", e)
        unavailable_services.append("Printer Monitor")

    return render_template(
        "printers.html",
        printers=printers,
        toner_threshold=_get_toner_threshold(client),
        unavailable_services=unavailable_services,
    )


@printers_bp.route("/htmx/list")
def htmx_printers_list() -> str:
    """HTMX: список принтеров для частичной загрузки.

    Returns:
        HTML-фрагмент со списком принтеров.
    """
    client = _get_client()
    sort_by = request.args.get("sort", "")
    order = request.args.get("order", "asc")

    try:
        printers = client.get_printers()
    except RequestException as e:
        printers = []
        logger.error("Printer Monitor API error: %s", e)

    printers = sort_items(printers, sort_by, order, SORT_FIELDS)

    return render_template(
        "partials/_printer_list.html",
        printers=printers,
        toner_threshold=_get_toner_threshold(client),
        sort_by=sort_by,
        order=order
    )


@printers_bp.route("/check", methods=["POST"])
def check_printers() -> str:
    """HTMX: принудительная проверка принтеров.

    Returns:
        HTML-фрагмент с результатом проверки.
    """
    client = _get_client()
    try:
        result = client.check_printers()
    except RequestException as e:
        logger.error("Printer Monitor API error: %s", e)
        message = f"Ошибка проверки: {e}"
    else:
        # Формирование сообщения вне try: ошибка формы ответа — наш баг,
        # а не «сервис недоступен».
        message = (
            f"{result['message']}. "
            f"Проверено: {result['printers_count']}, "
            f"низкий тонер: {result['low_toner_count']}"
        )

    return render_template("partials/_check_result.html", message=message)
