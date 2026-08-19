"""Клиент LogSpy API.

Модуль для взаимодействия с LogSpy API — анализ логов Squid
и мониторинг активности пользователей Active Directory.
"""

from typing import Any

from app.api.base import BaseApiClient


class LogSpyClient(BaseApiClient):
    """Клиент для работы с LogSpy API."""

    def __init__(self, base_url: str, timeout: int = 15) -> None:
        super().__init__(base_url, timeout)

    # Health

    def get_health(self) -> dict[str, Any]:
        return self._get("/api/v1/health")

    # Logs

    def get_logs(self) -> list[dict[str, Any]]:
        return self._get("/api/v1/logs")

    def get_current_log(self) -> str:
        """Имя текущего (первого) лог-файла или пустая строка."""
        logs = self.get_logs()
        return logs[0]["name"] if logs else ""

    def get_file_info(
        self, filename: str, sample_size: int = 1000
    ) -> dict[str, Any]:
        return self._get(
            "/api/v1/file/info",
            {"filename": filename, "sample_size": sample_size},
        )

    # Data

    def get_data(
        self,
        filename: str,
        page: int = 1,
        limit: int = 100,
        search: str | None = None,
        user: str | None = None,
        status: str | None = None,
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
        search: str | None = None,
        department: str | None = None,
        ou: str | None = None,
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
            {"filename": filename},
        )

    # Active Directory — Computers

    def get_ad_computers(
        self,
        search: str | None = None,
        ou: str | None = None,
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
        self, search: str | None = None
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
        return self._post("/api/v1/stoplist", json={"words": words})

    def replace_stoplist(self, words: list[str]) -> dict[str, Any]:
        return self._put("/api/v1/stoplist", json={"words": words})

    def remove_stoplist_word(self, word: str) -> dict[str, Any]:
        return self._delete(f"/api/v1/stoplist/{word}")
