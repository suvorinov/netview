"""Клиент Host Monitor API.

Модуль для взаимодействия с Host Monitor API.
"""

from typing import Any, Optional

import requests


class HostMonitorClient:
    """Клиент для работы с Host Monitor API.

    Attributes:
        base_url: Базовый URL API.
        timeout: Таймаут запросов в секундах.
    """

    def __init__(self, base_url: str, timeout: int = 10) -> None:
        """Инициализация клиента.

        Args:
            base_url: Базовый URL Host Monitor API.
            timeout: Таймаут запросов.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_hosts(
        self,
        q: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 50
    ) -> dict[str, Any]:
        """Получить список хостов с пагинацией.

        Args:
            q: Поиск по hostname.
            status: Фильтр по статусу (ONLINE/OFFLINE).
            page: Номер страницы.
            limit: Количество элементов на странице.

        Returns:
            Список хостов с метаданными пагинации.
        """
        params: dict[str, Any] = {"page": page, "limit": limit}
        if q:
            params["q"] = q
        if status:
            params["status"] = status

        response = requests.get(
            f"{self.base_url}/api/v1/hosts",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def get_host(self, hostname: str) -> dict[str, Any]:
        """Получить информацию о конкретном хосте.

        Args:
            hostname: Имя хоста.

        Returns:
            Информация о хосте.
        """
        response = requests.get(
            f"{self.base_url}/api/v1/hosts/{hostname}",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def get_stats(self) -> dict[str, Any]:
        """Получить статистику по хостам.

        Returns:
            Статистика: количество хостов, средние нагрузки.
        """
        response = requests.get(
            f"{self.base_url}/api/v1/hosts/stats",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
