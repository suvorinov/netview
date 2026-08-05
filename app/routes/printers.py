"""Маршруты принтеров.

Модуль содержит маршруты для работы с принтерами.
"""

import logging
from typing import Any

from flask import Blueprint, render_template, current_app, request

from app.api.printer_client import PrinterMonitorClient

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
    except Exception as e:
        printers = []
        logger.error("Printer Monitor API error: %s", e)
        unavailable_services.append("Printer Monitor")

    return render_template(
        "printers.html",
        printers=printers,
        unavailable_services=unavailable_services,
    )


def _sort_printers(printers: list[dict[str, Any]], sort_by: str, order: str) -> list[dict[str, Any]]:
    """Сортировать список принтеров.

    Args:
        printers: Список принтеров.
        sort_by: Поле сортировки.
        order: Направление (asc/desc).

    Returns:
        Отсортированный список.
    """
    if sort_by not in SORT_FIELDS:
        return printers

    field = SORT_FIELDS[sort_by]
    reverse = order == "desc"

    def get_sort_key(p: dict) -> Any:
        val = p.get(field, 0)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                return 0
        return val or 0

    return sorted(printers, key=get_sort_key, reverse=reverse)


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
    except Exception as e:
        printers = []
        logger.error("Printer Monitor API error: %s", e)

    printers = _sort_printers(printers, sort_by, order)

    return render_template(
        "partials/_printer_list.html",
        printers=printers,
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
        message = f"{result['message']}. Проверено: {result['printers_count']}, низкий тонер: {result['low_toner_count']}"
    except Exception as e:
        message = f"Ошибка проверки: {str(e)}"
        logger.error("Printer Monitor API error: %s", e)

    return render_template("partials/_check_result.html", message=message)
