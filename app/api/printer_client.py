"""Клиент Printer Monitor API.

Модуль для взаимодействия с KYOCERA Printer Monitor API.
"""

from typing import Any

import requests


class PrinterMonitorClient:
    """Клиент для работы с Printer Monitor API.

    Attributes:
        base_url: Базовый URL API.
        timeout: Таймаут запросов в секундах.
    """

    def __init__(self, base_url: str, timeout: int = 20) -> None:
        """Инициализация клиента.

        Args:
            base_url: Базовый URL Printer Monitor API.
            timeout: Таймаут запросов.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_printers(self) -> list[dict[str, Any]]:
        """Получить список всех принтеров.

        Returns:
            Список информации о принтерах.
        """
        response = requests.get(
            f"{self.base_url}/api/printers",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def get_printer(self, ip: str) -> dict[str, Any]:
        """Получить информацию о конкретном принтере.

        Args:
            ip: IP-адрес принтера.

        Returns:
            Информация о принтере.
        """
        response = requests.get(
            f"{self.base_url}/api/printers/{ip}",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def check_printers(self) -> dict[str, Any]:
        """Выполнить принудительную проверку принтеров.

        Returns:
            Результат проверки.
        """
        response = requests.post(
            f"{self.base_url}/api/check",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def get_status(self) -> dict[str, Any]:
        """Получить статус системы мониторинга.

        Returns:
            Статус системы.
        """
        response = requests.get(
            f"{self.base_url}/api/status",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def get_threshold(self) -> dict[str, Any]:
        """Получить порог уведомления о низком тонере.

        Returns:
            Текущий порог.
        """
        response = requests.get(
            f"{self.base_url}/api/threshold",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def set_threshold(self, threshold: int) -> dict[str, Any]:
        """Установить порог уведомления о низком тонере.

        Args:
            threshold: Новое значение порога в процентах.

        Returns:
            Установленное значение.
        """
        response = requests.put(
            f"{self.base_url}/api/threshold",
            json={"threshold": threshold},
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def get_check_interval(self) -> dict[str, Any]:
        """Получить текущий интервал проверки.

        Returns:
            Текущий интервал.
        """
        response = requests.get(
            f"{self.base_url}/api/check-interval",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def set_check_interval(self, interval: int) -> dict[str, Any]:
        """Установить интервал проверки.

        Args:
            interval: Новый интервал в секундах.

        Returns:
            Установленное значение.
        """
        response = requests.put(
            f"{self.base_url}/api/check-interval",
            json={"interval": interval},
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
