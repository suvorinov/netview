"""Клиент Printer Monitor API.

Модуль для взаимодействия с KYOCERA Printer Monitor API.
"""

from typing import Any

from app.api.base import BaseApiClient


class PrinterMonitorClient(BaseApiClient):
    """Клиент для работы с Printer Monitor API."""

    def __init__(self, base_url: str, timeout: int = 60) -> None:
        super().__init__(base_url, timeout)

    def get_printers(self) -> list[dict[str, Any]]:
        """Получить список всех принтеров.

        Returns:
            Список информации о принтерах.
        """
        return self._get("/api/printers")

    def get_printer(self, ip: str) -> dict[str, Any]:
        """Получить информацию о конкретном принтере.

        Args:
            ip: IP-адрес принтера.

        Returns:
            Информация о принтере.
        """
        return self._get(f"/api/printers/{ip}")

    def check_printers(self) -> dict[str, Any]:
        """Выполнить принудительную проверку принтеров.

        Returns:
            Результат проверки.
        """
        return self._post("/api/check")

    def get_status(self) -> dict[str, Any]:
        """Получить статус системы мониторинга.

        Returns:
            Статус системы.
        """
        return self._get("/api/status")

    def get_threshold(self) -> dict[str, Any]:
        """Получить порог уведомления о низком тонере.

        Returns:
            Текущий порог.
        """
        return self._get("/api/threshold")

    def set_threshold(self, threshold: int) -> dict[str, Any]:
        """Установить порог уведомления о низком тонере.

        Args:
            threshold: Новое значение порога в процентах.

        Returns:
            Установленное значение.
        """
        return self._put("/api/threshold", json={"threshold": threshold})

    def get_check_interval(self) -> dict[str, Any]:
        """Получить текущий интервал проверки.

        Returns:
            Текущий интервал.
        """
        return self._get("/api/check-interval")

    def set_check_interval(self, interval: int) -> dict[str, Any]:
        """Установить интервал проверки.

        Args:
            interval: Новый интервал в секундах.

        Returns:
            Установленное значение.
        """
        return self._put("/api/check-interval", json={"interval": interval})
