"""Фабрики API-клиентов внутренних сервисов.

Единая точка получения клиентов вместо копий _get_*_client()
в каждом модуле маршрутов.

Клиенты создаются лениво и кэшируются на экземпляре приложения
(app.extensions["api_clients"]): requests.Session переиспользуется
между запросами — TCP-соединения к сервисам живут (keep-alive),
а не рвутся на каждый запрос страницы. Пул соединений urllib3
потокобезопасен, поэтому один клиент могут делить параллельные
задачи Dashboard.
"""

from collections.abc import Callable
from typing import Any

from flask import current_app

from app.api.host_client import HostMonitorClient
from app.api.logspy_client import LogSpyClient
from app.api.netcerber_client import NetCerberClient
from app.api.printer_client import PrinterMonitorClient

_CACHE_KEY = "api_clients"


def _cached_client(
    key: str,
    config_key: str,
    client_cls: Callable[..., Any],
    timeout_key: str | None = None,
) -> Any:
    """Получить клиента из кэша приложения или создать и закэшировать.

    Кэш хранится в current_app.extensions — у каждого экземпляра
    приложения (в том числе в тестах) он свой.

    Args:
        key: Ключ клиента в кэше ("printer", "host", ...).
        config_key: Имя переменной конфигурации с URL сервиса.
        client_cls: Класс клиента.
        timeout_key: Имя переменной конфигурации с таймаутом (сек.).
            Если не задан — таймаут клиента из его конструктора.

    Returns:
        Экземпляр клиента для текущего приложения.
    """
    clients = current_app.extensions.setdefault(_CACHE_KEY, {})
    if key not in clients:
        kwargs: dict[str, Any] = {}
        if timeout_key:
            kwargs["timeout"] = int(current_app.config.get(timeout_key, 15))
        clients[key] = client_cls(current_app.config[config_key], **kwargs)
    return clients[key]


def get_printer_client() -> PrinterMonitorClient:
    """Клиент Printer Monitor API."""
    return _cached_client(
        "printer", "PRINTER_API_URL", PrinterMonitorClient, "PRINTER_TIMEOUT"
    )


def get_host_client() -> HostMonitorClient:
    """Клиент Host Monitor API."""
    return _cached_client(
        "host", "HOST_API_URL", HostMonitorClient, "HOST_TIMEOUT"
    )


def get_logspy_client() -> LogSpyClient:
    """Клиент LogSpy API.

    Таймаут настраивается отдельно (LOGSPY_TIMEOUT): запрос сведений
    о пользователе может быть тяжёлым и не укладываться в общий дефолт.
    """
    return _cached_client(
        "logspy", "LOGSPY_API_URL", LogSpyClient, "LOGSPY_TIMEOUT"
    )


def get_netcerber_client() -> NetCerberClient:
    """Клиент NetCerber API."""
    return _cached_client(
        "netcerber", "NETCERBER_API_URL", NetCerberClient, "NETCERBER_TIMEOUT"
    )
