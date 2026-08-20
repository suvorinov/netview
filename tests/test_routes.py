"""Тесты рендера страниц с замоканными API-клиентами.

Внутренние сервисы в тестах недоступны — клиенты подменяются
статичными ответами, чтобы проверить рендер шаблонов.
"""

import pytest

from app.api.host_client import HostMonitorClient
from app.api.logspy_client import LogSpyClient
from app.api.netcerber_client import NetCerberClient
from app.api.printer_client import PrinterMonitorClient


@pytest.fixture(autouse=True)
def mock_api_clients(monkeypatch):
    """Подменить все HTTP-клиенты статичными ответами."""
    monkeypatch.setattr(PrinterMonitorClient, "get_printers", lambda self: [])
    monkeypatch.setattr(PrinterMonitorClient, "get_threshold", lambda self: {"threshold": 20})
    monkeypatch.setattr(PrinterMonitorClient, "get_status", lambda self: {"status": "ok"})
    monkeypatch.setattr(PrinterMonitorClient, "get_check_interval", lambda self: {"interval": 300})
    monkeypatch.setattr(
        HostMonitorClient, "get_hosts",
        lambda self, **kwargs: {"items": [], "total": 0, "total_pages": 0},
    )
    monkeypatch.setattr(
        HostMonitorClient, "get_stats",
        lambda self: {"total": 0, "online": 0, "offline": 0, "avg_cpu": 0},
    )
    monkeypatch.setattr(HostMonitorClient, "get_host", lambda self, hostname: {})
    monkeypatch.setattr(LogSpyClient, "get_logs", lambda self: [{"name": "access.log"}])
    monkeypatch.setattr(LogSpyClient, "get_current_log", lambda self: "access.log")
    monkeypatch.setattr(
        LogSpyClient, "get_data",
        lambda self, filename, **kwargs: {
            "records": [],
            "pagination": {"total_records": 0},
        },
    )
    monkeypatch.setattr(
        LogSpyClient, "get_ad_user",
        lambda self, username: {
            "sAMAccountName": username,
            "displayName": "Тест Тестович",
            "distinguishedName": f"CN={username},OU=ZR,DC=zr,DC=local",
            "enabled": True,
        },
    )
    monkeypatch.setattr(
        LogSpyClient, "get_ad_user_activity",
        lambda self, username, filename: {
            "username": username,
            "total_requests": 1682,
            "total_traffic": 85302169,
            "total_traffic_formatted": "81.35 MB",
            "blocked_requests": 119,
            "time_on_blocked": 150.18,
            "domains_visited": ["yandex.ru", "vk.com"],
            "last_activity": "2026-08-20 08:10:01",
        },
    )
    monkeypatch.setattr(LogSpyClient, "get_ad_stats", lambda self: {})
    monkeypatch.setattr(LogSpyClient, "get_stoplist", lambda self: {"total": 0})
    monkeypatch.setattr(LogSpyClient, "get_ad_users", lambda self, **kwargs: [])
    monkeypatch.setattr(LogSpyClient, "get_ad_ous", lambda self: [])
    monkeypatch.setattr(NetCerberClient, "get_devices", lambda self, **kwargs: {"items": [], "total": 0})
    monkeypatch.setattr(NetCerberClient, "get_scans", lambda self, **kwargs: {"items": [], "total": 0})
    monkeypatch.setattr(NetCerberClient, "get_alerts", lambda self, **kwargs: {"items": [], "total": 0})
    monkeypatch.setattr(NetCerberClient, "get_stats", lambda self: {})
    monkeypatch.setattr(NetCerberClient, "scan_status", lambda self: {})
    monkeypatch.setattr(NetCerberClient, "get_baseline_scan", lambda self: None)
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: {})


PAGES = [
    "/",
    "/printers/",
    "/hosts/",
    "/users/",
    "/logs/",
    "/stoplist/",
    "/netcerber/",
    "/netcerber/scans/",
    "/settings/",
]

HTMX_FRAGMENTS = [
    "/printers/htmx/list",
    "/hosts/htmx/list",
    "/netcerber/htmx/list",
    "/netcerber/htmx/scans",
    "/netcerber/htmx/alerts",
    "/hosts/stats",
    "/settings/htmx/status",
    "/netcerber/htmx/stats",
    "/netcerber/htmx/scan-status",
    "/netcerber/htmx/device/1",
]


@pytest.mark.parametrize("page", PAGES)
def test_pages_render(logged_client, page):
    response = logged_client.get(page)
    assert response.status_code == 200


@pytest.mark.parametrize("page", HTMX_FRAGMENTS)
def test_htmx_fragments_render(logged_client, page):
    response = logged_client.get(page)
    assert response.status_code == 200


def test_dashboard_renders_quick_panels(logged_client):
    html = logged_client.get("/").get_data(as_text=True)
    # Пустые списки: сервисы замоканы, но панели критических состояний есть
    assert "Критический тонер не обнаружен" in html
    assert "Критических нагрузок нет" in html


def test_critical_printers_excludes_na():
    """Принтеры с "N/A" (нет данных о тонере) не считаются критическими."""
    from app.routes.dashboard import _critical_printers

    printers = [
        {"name": "Buh", "toner_percentage": "5.0%", "toner_percentage_value": 5.0},
        {"name": "Room 115", "toner_percentage": "N/A", "toner_percentage_value": 0.0},
        {"name": "Нет связи", "toner_percentage": "N/A", "toner_percentage_value": 0.0},
        {"name": "Kooperacia", "toner_percentage": "6.0%", "toner_percentage_value": 6.0},
    ]
    result = _critical_printers(printers, toner_threshold=25)
    assert [p["name"] for p in result] == ["Buh", "Kooperacia"]


def test_user_detail_shows_server_stats(logged_client):
    """Карточка пользователя показывает серверную статистику за весь файл."""
    html = logged_client.get("/users/Valentin.Gorohov").get_data(as_text=True)
    assert "1682" in html          # всего запросов
    assert "81.35 MB" in html      # трафик за файл
    assert "2:30" in html          # время на заблокированных (150.18 сек)
    assert "Открыть в Логах" in html
    assert "yandex.ru" in html


def test_user_detail_fallback_when_activity_unavailable(logged_client, monkeypatch):
    """Если серверный endpoint activity недоступен — фолбэк без падения."""
    from app.api.logspy_client import LogSpyClient

    def boom(*args, **kwargs):
        raise ConnectionError("LogSpy down")

    monkeypatch.setattr(LogSpyClient, "get_ad_user_activity", boom)
    response = logged_client.get("/users/Valentin.Gorohov")
    assert response.status_code == 200


def test_404_page():
    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    from conftest import login as do_login

    do_login(client)
    response = client.get("/nonexistent")
    assert response.status_code == 404
