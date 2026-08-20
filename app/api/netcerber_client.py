"""Клиент NetCerber API.

Модуль для взаимодействия с NetCerber API — мониторинг устройств
локальной сети, сканирование, авторизация и оповещения.
"""

from typing import Any

import requests

from app.api.base import BaseApiClient


class NetCerberClient(BaseApiClient):
    """Клиент для работы с NetCerber API."""

    def __init__(self, base_url: str, timeout: int = 15) -> None:
        super().__init__(base_url, timeout)

    # ── Health / Stats ──────────────────────────────────────────

    def get_health(self) -> dict[str, Any]:
        return self._get("/api/v1/health")

    def get_stats(self) -> dict[str, Any]:
        return self._get("/api/v1/stats")

    # ── Devices ─────────────────────────────────────────────────

    def get_devices(
        self,
        authorized: bool | None = None,
        unauthorized: bool | None = None,
        sort_by: str = "last_seen",
        skip: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"sort_by": sort_by, "skip": skip, "limit": limit}
        if authorized is not None:
            params["authorized"] = authorized
        if unauthorized is not None:
            params["unauthorized"] = unauthorized
        return self._get("/api/v1/devices", params)

    def export_devices(self, fmt: str = "csv") -> str:
        """Выгрузить устройства в файл (CSV) — сырой текст ответа."""
        response = requests.get(
            f"{self.base_url}/api/v1/devices/export",
            params={"format": fmt},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def get_device(self, device_id: int) -> dict[str, Any]:
        return self._get(f"/api/v1/devices/{device_id}")

    def update_device(self, device_id: int, data: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"/api/v1/devices/{device_id}", json=data)

    def delete_device(self, device_id: int) -> dict[str, Any]:
        return self._delete(f"/api/v1/devices/{device_id}")

    def authorize_device(self, device_id: int, description: str = "") -> dict[str, Any]:
        params = {"description": description} if description else None
        return self._post(f"/api/v1/devices/{device_id}/authorize", params=params)

    def unauthorize_device(self, device_id: int) -> dict[str, Any]:
        return self._post(f"/api/v1/devices/{device_id}/unauthorize")

    def authorize_all_devices(self, description: str = "") -> dict[str, Any]:
        params = {"description": description} if description else None
        return self._post("/api/v1/devices/authorize-all", params=params)

    # ── Scans ───────────────────────────────────────────────────

    def get_scans(self, limit: int = 50, skip: int = 0) -> dict[str, Any]:
        return self._get("/api/v1/scans", {"limit": limit, "skip": skip})

    def get_baseline_scan(self) -> dict[str, Any] | None:
        return self._get("/api/v1/scans/baseline")

    def get_scan(self, scan_id: int) -> dict[str, Any]:
        return self._get(f"/api/v1/scans/{scan_id}")

    def delete_scan(self, scan_id: int) -> dict[str, Any]:
        return self._delete(f"/api/v1/scans/{scan_id}")

    def set_baseline_scan(self, scan_id: int) -> dict[str, Any]:
        return self._post(f"/api/v1/scans/{scan_id}/set-baseline")

    def clear_baseline_scan(self) -> dict[str, Any]:
        return self._post("/api/v1/scans/clear-baseline")

    # ── Alerts ──────────────────────────────────────────────────

    def get_alerts(
        self, limit: int = 50, skip: int = 0, alert_type: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "skip": skip}
        if alert_type:
            params["type"] = alert_type
        return self._get("/api/v1/alerts", params)

    def get_alert(self, alert_id: int) -> dict[str, Any]:
        return self._get(f"/api/v1/alerts/{alert_id}")

    # ── Scheduler ───────────────────────────────────────────────

    def scheduler_status(self) -> dict[str, Any]:
        return self._get("/api/v1/scheduler/status")

    def scheduler_pause(self) -> dict[str, Any]:
        return self._post("/api/v1/scheduler/pause")

    def scheduler_resume(self) -> dict[str, Any]:
        return self._post("/api/v1/scheduler/resume")

    def scheduler_set_interval(self, interval: int) -> dict[str, Any]:
        return self._post("/api/v1/scheduler/interval", json={"interval": interval})

    # ── Active Directory ────────────────────────────────────────

    def ad_status(self) -> dict[str, Any]:
        return self._get("/api/v1/ad/status")

    def ad_computers(self) -> list[dict[str, Any]]:
        return self._get("/api/v1/ad/computers")

    def ad_refresh(self) -> dict[str, Any]:
        return self._post("/api/v1/ad/refresh")

    # ── Scan Control ────────────────────────────────────────────

    def trigger_scan(self) -> dict[str, Any]:
        return self._post("/api/v1/scan/now")

    def scan_status(self) -> dict[str, Any]:
        return self._get("/api/v1/scan/status")
