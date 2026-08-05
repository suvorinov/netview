"""Клиент LogSpy API.

Модуль для взаимодействия с LogSpy API — анализ логов Squid
и мониторинг активности пользователей Active Directory.
"""

from typing import Any, Optional

import requests


class LogSpyClient:
    """Клиент для работы с LogSpy API.

    Attributes:
        base_url: Базовый URL API.
        timeout: Таймаут запросов в секундах.
    """

    def __init__(self, base_url: str, timeout: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        response = requests.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, json: Optional[dict] = None) -> Any:
        response = requests.post(
            f"{self.base_url}{path}",
            json=json,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def _put(self, path: str, json: Optional[dict] = None) -> Any:
        response = requests.put(
            f"{self.base_url}{path}",
            json=json,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def _delete(self, path: str) -> Any:
        response = requests.delete(
            f"{self.base_url}{path}",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    # Health

    def get_health(self) -> dict[str, Any]:
        return self._get("/api/v1/health")

    # Logs

    def get_logs(self) -> list[dict[str, Any]]:
        return self._get("/api/v1/logs")

    def get_file_info(
        self, filename: str, sample_size: int = 1000
    ) -> dict[str, Any]:
        return self._get(
            "/api/v1/file/info",
            {"filename": filename, "sample_size": sample_size}
        )

    # Data

    def get_data(
        self,
        filename: str,
        page: int = 1,
        limit: int = 100,
        search: Optional[str] = None,
        user: Optional[str] = None,
        status: Optional[str] = None,
        sort: str = "time_desc",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "filename": filename,
            "page": page,
            "limit": limit,
            "sort": sort,
        }
        if search:
            params["search"] = search
        if user:
            params["user"] = user
        if status:
            params["status"] = status
        return self._get("/api/v1/data", params)

    # Summary

    def get_summary(self, filename: str) -> dict[str, Any]:
        return self._get("/api/v1/summary", {"filename": filename})

    # Active Directory — Stats

    def get_ad_stats(self) -> dict[str, Any]:
        return self._get("/api/v1/ad/stats")

    def ad_sync(self) -> dict[str, Any]:
        return self._post("/api/v1/ad/sync")

    def ad_test_connection(self) -> dict[str, Any]:
        return self._get("/api/v1/ad/test-connection")

    # Active Directory — Users

    def get_ad_users(
        self,
        search: Optional[str] = None,
        department: Optional[str] = None,
        ou: Optional[str] = None,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"enabled_only": enabled_only}
        if search:
            params["search"] = search
        if department:
            params["department"] = department
        if ou:
            params["ou"] = ou
        return self._get("/api/v1/ad/users", params)

    def get_ad_user(self, username: str) -> dict[str, Any]:
        return self._get(f"/api/v1/ad/users/{username}")

    def get_ad_user_activity(
        self, username: str, filename: str
    ) -> dict[str, Any]:
        return self._get(
            f"/api/v1/ad/users/{username}/activity",
            {"filename": filename}
        )

    # Active Directory — Computers

    def get_ad_computers(
        self,
        search: Optional[str] = None,
        ou: Optional[str] = None,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"enabled_only": enabled_only}
        if search:
            params["search"] = search
        if ou:
            params["ou"] = ou
        return self._get("/api/v1/ad/computers", params)

    # Active Directory — Groups

    def get_ad_groups(
        self, search: Optional[str] = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        return self._get("/api/v1/ad/groups", params)

    # Active Directory — OUs

    def get_ad_ous(self) -> list[dict[str, Any]]:
        return self._get("/api/v1/ad/ous")

    # Active Directory — IP Resolution

    def ad_resolve_ip(self, ip_address: str) -> dict[str, Any]:
        return self._get(f"/api/v1/ad/ip/{ip_address}")

    # Stoplist

    def get_stoplist(self) -> dict[str, Any]:
        return self._get("/api/v1/stoplist")

    def add_stoplist_words(self, words: list[str]) -> dict[str, Any]:
        return self._post("/api/v1/stoplist", {"words": words})

    def replace_stoplist(self, words: list[str]) -> dict[str, Any]:
        return self._put("/api/v1/stoplist", {"words": words})

    def remove_stoplist_word(self, word: str) -> dict[str, Any]:
        return self._delete(f"/api/v1/stoplist/{word}")
