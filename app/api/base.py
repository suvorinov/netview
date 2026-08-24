"""Базовый HTTP-клиент для всех внутренних сервисов NetView.

Единая точка обработки запросов: таймаут, проверка статуса ответа,
десериализация JSON. Каждый клиент держит собственную requests.Session —
TCP-соединения переиспользуются между вызовами (keep-alive).
"""

from typing import Any

import requests


class BaseApiClient:
    """Базовый клиент для работы с JSON API внутренних сервисов.

    Attributes:
        base_url: Базовый URL API (без завершающего слеша).
        timeout: Таймаут запросов в секундах.
    """

    def __init__(self, base_url: str, timeout: int = 15) -> None:
        """Инициализация клиента.

        Args:
            base_url: Базовый URL API.
            timeout: Таймаут запросов в секундах.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Сессия переиспользует TCP-соединения: одна страница Dashboard
        # делает ~10 запросов к сервисам, и без keep-alive это 10
        # рукопожатий. Пул соединений urllib3 потокобезопасен, поэтому
        # параллельные задачи Dashboard могут делить один клиент.
        self._session = requests.Session()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        """Выполнить запрос к API и вернуть JSON-ответ.

        Args:
            method: HTTP-метод (GET, POST, PUT, PATCH, DELETE).
            path: Путь к эндпоинту (например, "/api/v1/hosts").
            **kwargs: Дополнительные параметры requests
                (params, json, data).

        Returns:
            Данные ответа (dict, list или None для пустых ответов).

        Raises:
            requests.RequestException: При сетевой ошибке или
                некорректном статусе ответа.
        """
        response = self._session.request(
            method,
            f"{self.base_url}{path}",
            timeout=self.timeout,
            **kwargs,
        )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def _get(self, path: str, params: dict | None = None) -> Any:
        """Выполнить GET-запрос."""
        return self._request("GET", path, params=params)

    def _post(
        self,
        path: str,
        params: dict | None = None,
        json: dict | None = None,
    ) -> Any:
        """Выполнить POST-запрос."""
        return self._request("POST", path, params=params, json=json)

    def _put(self, path: str, json: dict | None = None) -> Any:
        """Выполнить PUT-запрос."""
        return self._request("PUT", path, json=json)

    def _patch(self, path: str, json: dict | None = None) -> Any:
        """Выполнить PATCH-запрос."""
        return self._request("PATCH", path, json=json)

    def _delete(self, path: str) -> Any:
        """Выполнить DELETE-запрос."""
        return self._request("DELETE", path)
