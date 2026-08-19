"""Клиент Host Monitor API.

Модуль для взаимодействия с Host Monitor API.
"""

from typing import Any

from app.api.base import BaseApiClient


class HostMonitorClient(BaseApiClient):
    """Клиент для работы с Host Monitor API."""

    def __init__(self, base_url: str, timeout: int = 10) -> None:
        super().__init__(base_url, timeout)

    def get_hosts(
        self,
        q: str | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 50,
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

        return self._get("/api/v1/hosts", params)

    def get_host(self, hostname: str) -> dict[str, Any]:
        """Получить информацию о конкретном хосте.

        Args:
            hostname: Имя хоста.

        Returns:
            Информация о хосте.
        """
        return self._get(f"/api/v1/hosts/{hostname}")

    def get_stats(self) -> dict[str, Any]:
        """Получить статистику по хостам.

        Returns:
            Статистика: количество хостов, средние нагрузки.
        """
        return self._get("/api/v1/hosts/stats")
