"""Тесты рендера страниц с замоканными API-клиентами.

Внутренние сервисы в тестах недоступны — клиенты подменяются
статичными ответами, чтобы проверить рендер шаблонов.
"""

import re

import pytest

from app.api.host_client import HostMonitorClient
from app.api.logspy_client import LogSpyClient
from app.api.netcerber_client import NetCerberClient
from app.api.printer_client import PrinterMonitorClient


def _iso(*, days=0, hours=0):
    """ISO-дата относительно текущего момента: тесты не должны стареть.

    Флаг «Новое» в панели живёт 7 дней от first_seen — жёсткие даты в
    фикстурах со временем выходили из окна и роняли тесты.
    """
    from datetime import datetime, timedelta

    return (
        datetime.now() - timedelta(days=days, hours=hours)
    ).isoformat(timespec="seconds")



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
    monkeypatch.setattr(NetCerberClient, "delete_scan", lambda self, scan_id: {})
    monkeypatch.setattr(NetCerberClient, "set_baseline_scan", lambda self, scan_id: {})
    monkeypatch.setattr(NetCerberClient, "clear_baseline_scan", lambda self: {})
    monkeypatch.setattr(
        NetCerberClient, "authorize_device",
        lambda self, device_id, description="": {
            "id": device_id, "ip_address": "192.168.0.201",
            "hostname": "test-device.zr.local", "is_authorized": True,
        },
    )
    monkeypatch.setattr(
        NetCerberClient, "unauthorize_device",
        lambda self, device_id: {
            "id": device_id, "ip_address": "192.168.0.201",
            "hostname": "test-device.zr.local", "is_authorized": False,
        },
    )
    monkeypatch.setattr(
        NetCerberClient, "authorize_all_devices",
        lambda self, description="": {"status": "ok", "message": "ok"},
    )
    monkeypatch.setattr(LogSpyClient, "ad_resolve_ip", lambda self, ip: None)
    monkeypatch.setattr(LogSpyClient, "get_ad_computers", lambda self, **kwargs: [])
    monkeypatch.setattr(LogSpyClient, "get_health", lambda self: {"status": "ok"})
    monkeypatch.setattr(
        NetCerberClient, "get_health",
        lambda self: {"status": "healthy", "database": "ok", "scanner": "ready"},
    )
    monkeypatch.setattr(
        NetCerberClient, "scheduler_status",
        lambda self: {
            "running": True,
            "job": {
                "next_run_time": "2026-08-21T11:53:37+03:00",
                "trigger": "interval[5:00:00]",
            },
        },
    )
    monkeypatch.setattr(NetCerberClient, "scheduler_pause", lambda self: {})
    monkeypatch.setattr(NetCerberClient, "scheduler_resume", lambda self: {})
    monkeypatch.setattr(
        NetCerberClient, "scheduler_set_interval", lambda self, interval: {},
    )


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
    "/netcerber/htmx/scheduler",
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
    assert "Сетевые угрозы" in html
    assert "Новых устройств не обнаружено" in html


def _netcerber_devices_fixture():
    """Четыре устройства: роутер TP-LINK (неизвестный), ПК ASUS (известный),
    принтер KYOCERA (известный, свежий), ПК MSI (в DHCP-пуле)."""
    return {
        "total": 4,
        "items": [
            {
                "id": 1,
                "ip_address": "192.168.0.201",
                "hostname": "Неизвестное устройство",
                "vendor": "TP-LINK TECHNOLOGIES CO.,LTD.",
                "mac_address": "aa:bb:cc:dd:ee:01",
                "first_seen": _iso(days=1),
                "is_authorized": False,
            },
            {
                "id": 2,
                "ip_address": "192.168.0.202",
                "hostname": "zr-pc-01.zr.local",
                "vendor": "ASUSTek COMPUTER INC.",
                "mac_address": "aa:bb:cc:dd:ee:02",
                "first_seen": _iso(days=90),
                "is_authorized": False,
            },
            {
                "id": 3,
                "ip_address": "192.168.0.203",
                "hostname": "zr-printer-01.zr.local",
                "vendor": "KYOCERA Display Corporation",
                "mac_address": "aa:bb:cc:dd:ee:03",
                "first_seen": _iso(days=1),
                "is_authorized": False,
            },
            {
                "id": 4,
                "ip_address": "192.168.0.100",
                "hostname": "zr-pc-02.zr.local",
                "vendor": "MSI",
                "mac_address": "aa:bb:cc:dd:ee:04",
                "first_seen": _iso(days=90),
                "is_authorized": False,
            },
        ],
    }


def test_netcerber_cat_filter(logged_client, monkeypatch):
    """Фильтр cat=router показывает только роутеры; флаги проставляются
    по правилам: TP-LINK неизвестный — роутер, ASUS известный — нет,
    TP-LINK и KYOCERA свежие — новое."""
    from app.api.netcerber_client import NetCerberClient

    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )

    html_all = logged_client.get("/netcerber/htmx/list").get_data(as_text=True)
    assert html_all.count('title="Вендор производит сетевое оборудование') == 1
    assert html_all.count("> Новое") == 2
    assert html_all.count("> Неизвестное") == 1

    html_router = logged_client.get(
        "/netcerber/htmx/list?cat=router"
    ).get_data(as_text=True)
    assert "192.168.0.201" in html_router
    assert "zr-pc-01.zr.local" not in html_router
    assert "zr-printer-01.zr.local" not in html_router

    html_new = logged_client.get("/netcerber/htmx/list?cat=new").get_data(as_text=True)
    assert "192.168.0.201" in html_new
    assert "zr-printer-01.zr.local" in html_new
    assert "zr-pc-01.zr.local" not in html_new

    html_chips = logged_client.get("/netcerber/htmx/list?cat=new").get_data(as_text=True)
    assert 'id="suspect-chips" hx-swap-oob="true"' in html_chips


def test_netcerber_active_chip_highlighted(logged_client, monkeypatch):
    """Активный чип подсвечивается и в OOB-фрагменте списка."""
    from app.api.netcerber_client import NetCerberClient

    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )
    html = logged_client.get("/netcerber/htmx/list?cat=new").get_data(as_text=True)
    assert 'hx-get="/netcerber/htmx/list?cat=new"' in html
    assert 'hx-get="/netcerber/htmx/list?cat=router"' in html
    # Чип "Новые" активен (синий), чип роутеров — нет
    idx_new = html.index('hx-get="/netcerber/htmx/list?cat=new"')
    idx_router = html.index('hx-get="/netcerber/htmx/list?cat=router"')
    assert "bg-blue-600 text-white" in html[idx_new - 300:idx_new + 100]
    assert "bg-blue-600 text-white" not in html[idx_router - 300:idx_router + 100]


def test_netcerber_list_shows_blocked_badge(app, logged_client, monkeypatch):
    """Устройство, заблокированное на шлюзе, помечается бейджем в списке.

    Блокировка вычисляется один раз на весь список (набор hex-MAC), а не
    запросом на каждое устройство.
    """
    from app.api.netcerber_client import NetCerberClient
    from app.routes import netcerber as netcerber_routes

    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )
    # Заблокирован только роутер TP-LINK (aa:bb:cc:dd:ee:01 -> AABBCCDDEE01)
    monkeypatch.setattr(
        netcerber_routes,
        "_opnsense_blocked_macs",
        lambda: {"AABBCCDDEE01"},
    )

    html = logged_client.get("/netcerber/htmx/list").get_data(as_text=True)
    assert html.count("> Заблокировано") == 1
    # Бейдж появляется только у устройства с заблокированным MAC (TP-LINK)
    # — других красных shield-бейджей блокировки в списке нет.


def test_netcerber_list_no_badge_when_opnsense_off(
    logged_client, monkeypatch
):
    """OPNsense выключен/недоступен — бейдж блокировки не выводится."""
    from app.api.netcerber_client import NetCerberClient
    from app.routes import netcerber as netcerber_routes

    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )
    monkeypatch.setattr(netcerber_routes, "_opnsense_blocked_macs", lambda: set())

    html = logged_client.get("/netcerber/htmx/list").get_data(as_text=True)
    assert "> Заблокировано" not in html


def test_netcerber_alerts_panel(logged_client, monkeypatch):
    """Блок оповещений рендерит список с типом unauthorized."""
    from app.api.netcerber_client import NetCerberClient

    monkeypatch.setattr(
        NetCerberClient, "get_alerts",
        lambda self, **kwargs: {
            "total": 1,
            "items": [
                {
                    "id": 1,
                    "alert_type": "unauthorized",
                    "device_mac": "aa:bb:cc:dd:ee:ff",
                    "message": "Неавторизованное устройство",
                    "created_at": "2026-08-19T09:00:00",
                    "is_sent": False,
                }
            ],
        },
    )
    html = logged_client.get("/netcerber/htmx/alerts?limit=10").get_data(as_text=True)
    assert "unauthorized" in html
    assert "Неавторизованное устройство" in html


def test_netcerber_search(logged_client, monkeypatch):
    """Поиск фильтрует устройства по IP/hostname/MAC/вендору."""
    from app.api.netcerber_client import NetCerberClient

    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )
    html = logged_client.get("/netcerber/htmx/list?q=192.168.0.201").get_data(as_text=True)
    assert "192.168.0.201" in html
    assert "zr-pc-01.zr.local" not in html
    assert "zr-printer-01.zr.local" not in html

    html_vendor = logged_client.get("/netcerber/htmx/list?q=kyocera").get_data(as_text=True)
    assert "zr-printer-01.zr.local" in html_vendor
    assert "192.168.0.201" not in html_vendor


def test_netcerber_pagination(logged_client, monkeypatch):
    """При неполной загрузке показывается кнопка «Показать ещё»."""
    from app.api.netcerber_client import NetCerberClient

    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )
    html = logged_client.get("/netcerber/htmx/list?limit=2").get_data(as_text=True)
    assert "Показать ещё" in html

    html_all = logged_client.get("/netcerber/htmx/list?limit=500").get_data(as_text=True)
    assert "Показать ещё" not in html_all


def test_netcerber_export_html(logged_client, monkeypatch):
    """Экспорт отдаёт HTML-отчёт: устройства, признаки, сортировка по IP."""
    from app.api.netcerber_client import NetCerberClient

    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )
    resp = logged_client.get("/netcerber/export")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert "devices.html" in resp.headers.get("Content-Disposition", "")
    html = resp.get_data(as_text=True)
    # Устройства из фикстуры и вычисленные признаки на месте
    assert "192.168.0.201" in html
    assert "zr-printer-01.zr.local" in html
    assert "Сетевое оборудование" in html  # TP-LINK с неизвестным hostname
    assert "Новое" in html
    assert "Не авторизовано" in html
    # Сортировка по IP: .100 идёт раньше .201 независимо от порядка выборки
    assert html.index("192.168.0.100") < html.index("192.168.0.201")


def test_netcerber_export_shows_blocked_badge(app, logged_client, monkeypatch):
    """Печатный отчёт помечает устройство, заблокированное на шлюзе."""
    from app.api.netcerber_client import NetCerberClient
    from app.routes import netcerber as netcerber_routes

    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )
    # Заблокирован роутер TP-LINK (aa:bb:cc:dd:ee:01 -> AABBCCDDEE01)
    monkeypatch.setattr(
        netcerber_routes, "_opnsense_blocked_macs", lambda: {"AABBCCDDEE01"}
    )

    html = logged_client.get("/netcerber/export").get_data(as_text=True)
    assert "Заблокировано на шлюзе" in html
    # Ровно один бейдж — у заблокированного TP-LINK (.201)
    assert html.count("Заблокировано на шлюзе") == 1


def test_user_blocked_export_html(logged_client, monkeypatch):
    """Отчёт о заблокированных ресурсах содержит записи, сводку и домены."""
    from app.api.logspy_client import LogSpyClient

    captured: dict = {}

    def fake_get_data(self, filename, **kwargs):
        captured.update(kwargs)
        return {
            "records": [
                {
                    "timestamp_human": "2026-08-20 08:00:01",
                    "url": "http://example.com/x",
                    "domain": "example.com",
                    "method": "GET",
                    "status_code": 403,
                    "size": 1200,
                    "is_blocked": True,
                },
                {
                    "timestamp_human": "2026-08-20 08:05:00",
                    "url": "http://casino.example/",
                    "domain": "casino.example",
                    "method": "GET",
                    "status_code": 403,
                    "size": 500,
                    "is_blocked": True,
                },
            ],
            "pagination": {"total_records": 2},
        }

    monkeypatch.setattr(LogSpyClient, "get_data", fake_get_data)
    resp = logged_client.get("/users/Valentin.Gorohov/export/blocked")
    assert resp.status_code == 200
    # Лимит запроса не превышает максимум API LogSpy (500)
    assert captured.get("limit") == 500
    assert "text/html" in resp.content_type
    assert (
        "blocked_Valentin.Gorohov.html"
        in resp.headers["Content-Disposition"]
    )
    html = resp.get_data(as_text=True)
    assert "Valentin.Gorohov" in html
    assert "example.com" in html
    assert "casino.example" in html
    assert "1.7 KB" in html  # суммарный трафик блокировок (1700 B)
    assert "access.log" in html


def test_user_page_shows_blocked_export_button(logged_client):
    """При наличии блокировок на странице есть кнопка экспорта отчёта."""
    html = logged_client.get("/users/Valentin.Gorohov").get_data(as_text=True)
    assert "Экспорт HTML" in html
    assert "/users/Valentin.Gorohov/export/blocked" in html


def _blocked_record(domain: str, size: int) -> dict:
    """Минимальная заблокированная запись LogSpy для тестов отчёта."""
    return {
        "timestamp_human": "2026-08-24 10:00:00",
        "url": f"http://{domain}/x",
        "domain": domain,
        "method": "GET",
        "status_code": 403,
        "size": size,
        "is_blocked": True,
    }


def test_user_blocked_export_aggregates_domains(logged_client, monkeypatch):
    """Повторные посещения домена суммируются: счётчик и трафик."""

    def fake_get_data(self, filename, **kwargs):
        return {
            "records": [
                _blocked_record("example.com", 1000),
                _blocked_record("example.com", 500),
                _blocked_record("casino.example", 2000),
            ],
            "pagination": {"total_records": 3},
        }

    monkeypatch.setattr(LogSpyClient, "get_data", fake_get_data)
    html = logged_client.get(
        "/users/Valentin.Gorohov/export/blocked"
    ).get_data(as_text=True)
    assert "Сводка по доменам (2)" in html
    # example.com (2 визита) идёт раньше casino.example (1 визит)
    assert html.index("example.com") < html.index("casino.example")
    row = re.search(
        r"<td>example\.com</td>\s*<td class=\"num\">2</td>"
        r"\s*<td class=\"num\"[^>]*>1\.5 KB</td>",
        html,
    )
    assert row, "строка сводки example.com: 2 визита / 1.5 KB не найдена"


def test_user_blocked_export_shows_time_on_blocked(
    logged_client, monkeypatch
):
    """Время на заблокированных ресурсах — из серверной статистики."""
    monkeypatch.setattr(
        LogSpyClient, "get_ad_user_activity",
        lambda self, username, filename: {
            "username": username,
            "time_on_blocked": 3725,
        },
    )
    html = logged_client.get(
        "/users/Valentin.Gorohov/export/blocked"
    ).get_data(as_text=True)
    assert "Время на заблокированных: 1:02:05" in html


def test_user_blocked_export_truncation_note(logged_client, monkeypatch):
    """При усечении списка отчёт честно предупреждает об этом."""

    def fake_get_data(self, filename, **kwargs):
        return {
            "records": [_blocked_record("example.com", 100)],
            "pagination": {"total_records": 700},
        }

    monkeypatch.setattr(LogSpyClient, "get_data", fake_get_data)
    html = logged_client.get(
        "/users/Valentin.Gorohov/export/blocked"
    ).get_data(as_text=True)
    assert "Показаны первые 1 из 700" in html
    assert "700</span>" in html  # итоговый счётчик — по всему файлу


def test_user_blocked_export_sanitizes_filename(logged_client):
    """Спецсимволы из username не попадают в Content-Disposition."""
    resp = logged_client.get("/users/bad%3Cname%3E/export/blocked")
    assert 'filename=blocked_bad_name_.html' in (
        resp.headers["Content-Disposition"]
    )


def test_user_page_hides_blocked_export_without_blocks(
    logged_client, monkeypatch
):
    """Без заблокированных запросов кнопки экспорта нет."""
    from app.api.logspy_client import LogSpyClient

    monkeypatch.setattr(
        LogSpyClient, "get_ad_user_activity",
        lambda self, username, filename: {
            "username": username,
            "total_requests": 10,
            "total_traffic": 1000,
            "blocked_requests": 0,
            "time_on_blocked": 0,
            "domains_visited": [],
            "last_activity": "",
        },
    )
    html = logged_client.get("/users/Valentin.Gorohov").get_data(as_text=True)
    assert "Экспорт HTML" not in html


def test_netcerber_authorize_updates_list(logged_client):
    """Авторизация в модалке обновляет список в фоне (hx-swap-oob)."""
    resp = logged_client.post(
        "/netcerber/htmx/authorize/1",
        data={"csrf_token": _csrf_token(logged_client)},
    )
    html = resp.get_data(as_text=True)
    assert 'id="device-list" hx-swap-oob="true"' in html
    assert "Авторизовано" in html
    assert "Деавторизовать" in html


def test_netcerber_delete_device_shows_confirmation_and_updates_list(
    logged_client, monkeypatch
):
    """Удаление из модалки: подтверждение + обновлённый список (hx-swap-oob)."""
    deleted = []

    def fake_delete(self, device_id):
        deleted.append(device_id)
        return {}

    monkeypatch.setattr(NetCerberClient, "delete_device", fake_delete)
    resp = logged_client.post(
        "/netcerber/htmx/delete/7",
        data={"csrf_token": _csrf_token(logged_client)},
    )

    assert deleted == [7]
    html = resp.get_data(as_text=True)
    assert "Запись удалена" in html
    assert 'id="device-list" hx-swap-oob="true"' in html


def test_netcerber_delete_device_unavailable(logged_client, monkeypatch):
    """Недоступный NetCerber при удалении — сообщение об ошибке."""
    import requests as requests_lib

    def boom(self, device_id):
        raise requests_lib.ConnectionError("NetCerber down")

    monkeypatch.setattr(NetCerberClient, "delete_device", boom)
    resp = logged_client.post(
        "/netcerber/htmx/delete/7",
        data={"csrf_token": _csrf_token(logged_client)},
    )

    assert "Не удалось удалить" in resp.get_data(as_text=True)


def test_netcerber_mismatch_badge_replaces_router_badge(logged_client, monkeypatch):
    """Роутерный вендор с разрешённым hostname → «Вендор ≠ hostname»,
    а не уверенное «Сетевое оборудование?» (кейс IP .37 после DHCP-блока).
    Неразрешённый hostname по-прежнему даёт роутер-бейдж."""
    devices = {
        "items": [
            {
                "id": 1,
                "ip_address": "192.168.0.37",
                "mac_address": "AA:BB:CC:DD:EE:01",
                "hostname": "zr-37",
                "vendor": "TP-LINK TECHNOLOGIES CO.,LTD.",
                "is_authorized": True,
                "first_seen": _iso(days=1),
                "last_seen": _iso(hours=3),
            },
            {
                "id": 2,
                "ip_address": "192.168.0.50",
                "mac_address": "AA:BB:CC:DD:EE:02",
                "hostname": "",
                "vendor": "TP-LINK TECHNOLOGIES CO.,LTD.",
                "is_authorized": False,
                "first_seen": _iso(days=1),
                "last_seen": _iso(hours=3),
            },
        ],
        "total": 2,
    }
    monkeypatch.setattr(NetCerberClient, "get_devices", lambda self, **kw: devices)

    html = logged_client.get("/netcerber/").get_data(as_text=True)

    # Для zr-37 — расхождение, для безымянного — прежний роутер-бейдж
    assert "Вендор ≠ hostname" in html
    assert 'title="Вендор производит сетевое оборудование' in html
    # Чип новой категории со счётчиком
    assert "Расхождение данных (1)" in html


# ── Блокировка устройств на шлюзе (OPNsense / TING) ────────────

_BLOCK_DEVICE = {
    "id": 9,
    "ip_address": "192.168.0.77",
    "mac_address": "aa-bb-cc-dd-ee-99",
    "hostname": "rogue-device",
    "vendor": "Xiaomi Communications",
    "is_authorized": False,
}


def _enable_opnsense(app):
    """Включить шлюзную (OPNsense) блокировку в конфиге тестового приложения."""
    from app.config import Config as _Config

    assert hasattr(_Config, "OPNSENSE_ENABLED")
    app.config.update(
        OPNSENSE_ENABLED=True,
        OPNSENSE_URL="http://192.168.0.1",
        OPNSENSE_KEY="key",
        OPNSENSE_SECRET="secret",
        OPNSENSE_TIMEOUT=5,
    )


def test_os_block_device_success(app, logged_client, monkeypatch):
    """Блокировка на шлюзе выполняется по MAC устройства (через алиас)."""
    from app.api.opnsense import OPNsenseClient

    _enable_opnsense(app)
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))
    called = {}

    def fake_block(self, mac):
        called["mac"] = mac
        return "шлюз: правило по MAC — трафик отсечён"

    monkeypatch.setattr(OPNsenseClient, "block_mac", fake_block)

    resp = logged_client.post(
        "/netcerber/htmx/os-block/9",
        data={"csrf_token": _csrf_token(logged_client)},
    )
    html = resp.get_data(as_text=True)

    assert called == {"mac": "AA:BB:CC:DD:EE:99"}
    assert "Заблокировано на шлюзе" in html
    assert "Разблокировать на шлюзе" in html


def test_os_block_refreshes_list_with_badge(app, logged_client, monkeypatch):
    """После успешной блокировки список перерисовывается oob с бейджем.

    Устройство #9 (AA:BB:CC:DD:EE:99) — ровно одно соответствие в списке;
    бейдж «Заблокировано» появляется в обновлённом фрагменте #device-list.
    """
    from app.api.opnsense import OPNsenseClient
    from app.routes import netcerber as netcerber_routes

    _enable_opnsense(app)
    monkeypatch.setattr(
        NetCerberClient, "get_device",
        lambda self, device_id: dict(_BLOCK_DEVICE),
    )
    monkeypatch.setattr(
        OPNsenseClient, "block_mac",
        lambda self, mac: "шлюз: правило по MAC — трафик отсечён",
    )
    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: {
            "total": 1,
            "items": [dict(_BLOCK_DEVICE)],
        },
    )
    # Шлюз считаем заблокированным для этого MAC
    monkeypatch.setattr(
        netcerber_routes, "_opnsense_blocked_macs",
        lambda: {"AABBCCDDEE99"},
    )

    resp = logged_client.post(
        "/netcerber/htmx/os-block/9",
        data={"csrf_token": _csrf_token(logged_client)},
    )
    html = resp.get_data(as_text=True)

    # oob-фрагмент списка присутствует и содержит бейдж блокировки
    assert 'id="device-list" hx-swap-oob="true"' in html
    assert "> Заблокировано" in html


def test_os_block_failure_keeps_list_unchanged(app, logged_client, monkeypatch):
    """При ошибке блокировки oob-фрагмент списка не выводится."""
    from app.api.opnsense import OPNsenseClient, OPNsenseError

    _enable_opnsense(app)
    monkeypatch.setattr(
        NetCerberClient, "get_device",
        lambda self, device_id: dict(_BLOCK_DEVICE),
    )
    monkeypatch.setattr(
        OPNsenseClient, "block_mac",
        lambda self, mac: (_ for _ in ()).throw(
            OPNsenseError("gateway rejected")
        ),
    )

    resp = logged_client.post(
        "/netcerber/htmx/os-block/9",
        data={"csrf_token": _csrf_token(logged_client)},
    )
    html = resp.get_data(as_text=True)
    assert "Ошибка выполнения" in html
    assert 'id="device-list" hx-swap-oob="true"' not in html


def test_os_block_device_protected_mac_rejected(app, logged_client, monkeypatch):
    """Защищённый MAC не блокируется на шлюзе ни при каких условиях."""
    from app.api.opnsense import OPNsenseClient

    _enable_opnsense(app)
    app.config["OPNSENSE_PROTECTED_MACS"] = "AA-BB-CC-DD-EE-99"
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))
    monkeypatch.setattr(
        OPNsenseClient,
        "block_mac",
        lambda self, mac: pytest.fail("block_mac не должен вызываться"),
    )

    resp = logged_client.post(
        "/netcerber/htmx/os-block/9",
        data={"csrf_token": _csrf_token(logged_client)},
    )
    assert "списке защищённых" in resp.get_data(as_text=True)


def test_os_block_device_disabled(app, logged_client, monkeypatch):
    """Шлюзная блокировка выключена — понятное сообщение."""
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))

    resp = logged_client.post(
        "/netcerber/htmx/os-block/9",
        data={"csrf_token": _csrf_token(logged_client)},
    )

    assert "OPNsense отключена" in resp.get_data(as_text=True)


def test_os_unblock_device_success(app, logged_client, monkeypatch):
    """Разблокировка на шлюзе идёт по MAC (переживает смену IP)."""
    from app.api.opnsense import OPNsenseClient

    _enable_opnsense(app)

    def broken_get(self, device_id):
        import requests as requests_lib

        raise requests_lib.ConnectionError("NetCerber down")

    monkeypatch.setattr(NetCerberClient, "get_device", broken_get)
    calls = []

    def fake_unblock(self, mac):
        calls.append(mac)
        return "шлюз: правила блокировки сняты"

    monkeypatch.setattr(OPNsenseClient, "unblock_mac", fake_unblock)

    resp = logged_client.post(
        "/netcerber/htmx/os-unblock/9",
        data={
            "csrf_token": _csrf_token(logged_client),
            "mac": "AA:BB:CC:DD:EE:99",
        },
    )
    html = resp.get_data(as_text=True)

    assert calls == ["AA:BB:CC:DD:EE:99"]
    assert "Разблокировано на шлюзе" in html


def test_os_block_works_without_ip(app, logged_client, monkeypatch):
    """MAC-блокировка не зависит от IP: правило ссылается на алиас MAC."""
    from app.api.opnsense import OPNsenseClient

    _enable_opnsense(app)
    nodata = dict(_BLOCK_DEVICE, ip_address="")
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: nodata)
    called = {}

    def fake_block(self, mac):
        called["mac"] = mac
        return "шлюз: правило по MAC — трафик отсечён"

    monkeypatch.setattr(OPNsenseClient, "block_mac", fake_block)

    resp = logged_client.post(
        "/netcerber/htmx/os-block/9",
        data={"csrf_token": _csrf_token(logged_client)},
    )

    assert called == {"mac": "AA:BB:CC:DD:EE:99"}
    assert "Заблокировано на шлюзе" in resp.get_data(as_text=True)


# ── Ограничение скорости на шлюзе (Traffic Shaper) ─────────────

def _enable_shaper(app):
    """Включить шейпер в тестовом конфиге (креды те же, что у блокировки)."""
    from app.config import Config as _Config

    assert hasattr(_Config, "OPNSENSE_SHAPER_ENABLED")
    app.config.update(
        OPNSENSE_SHAPER_ENABLED=True,
        OPNSENSE_URL="http://192.168.0.1",
        OPNSENSE_KEY="key",
        OPNSENSE_SECRET="secret",
        OPNSENSE_TIMEOUT=5,
    )


def _shaper_channel(uid, name):
    return {"uuid": uid, "name": name, "bandwidth": "5", "metric": "Mbit/s"}


def _shaped_rule(mac_hex, target, ip):
    return {
        "uuid": "shape-rule-1",
        "description": f"netview-shape-{mac_hex}",
        "enabled": True,
        "sequence": "90",
        "target_uuid": target,
        "destinations": [ip],
    }


def test_shaper_apply_device_success(app, logged_client, monkeypatch):
    """Применение канала: правило отдано клиенту, модалка перерисована."""
    from app.api.opnsense import OPNsenseClient

    _enable_shaper(app)
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))
    monkeypatch.setattr(OPNsenseClient, "shaper_pipe_name", lambda self, uid: "5Mbit")
    calls = {}

    def fake_apply(self, mac, ip, uid):
        calls.update(mac=mac, ip=ip, uid=uid)
        return "шлюз: канал установлен (MAC AA:BB:CC:DD:EE:99)"

    monkeypatch.setattr(OPNsenseClient, "shaper_apply", fake_apply)
    monkeypatch.setattr(OPNsenseClient, "shaper_pipes", lambda self: [_shaper_channel("pipe-a", "5Mbit")])
    monkeypatch.setattr(
        OPNsenseClient, "shaper_device_status",
        lambda self, mac: _shaped_rule("AABBCCDDEE99", "pipe-a", "192.168.0.77"),
    )

    resp = logged_client.post(
        "/netcerber/htmx/shaper-apply/9",
        data={
            "csrf_token": _csrf_token(logged_client),
            "mac": "AA:BB:CC:DD:EE:99",
            "channel": "pipe-a",
        },
    )
    html = resp.get_data(as_text=True)

    assert calls == {"mac": "AA:BB:CC:DD:EE:99", "ip": "192.168.0.77", "uid": "pipe-a"}
    assert "Ограничение скорости (канал)" in html
    assert "5Mbit" in html  # применённый канал в статусе
    assert 'value="pipe-a" selected' in html  # канал выбран в селекте


def test_shaper_apply_device_disabled(app, logged_client, monkeypatch):
    """Шейпер выключен — понятное сообщение вместо операции."""
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))

    resp = logged_client.post(
        "/netcerber/htmx/shaper-apply/9",
        data={
            "csrf_token": _csrf_token(logged_client),
            "mac": "AA:BB:CC:DD:EE:99",
            "channel": "pipe-a",
        },
    )

    assert "Шейпер отключён" in resp.get_data(as_text=True)


def test_shaper_apply_missing_channel(app, logged_client, monkeypatch):
    """Канал обязателен: без него — предупреждение, без запросов к шлюзу."""
    from app.api.opnsense import OPNsenseClient

    _enable_shaper(app)
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))
    monkeypatch.setattr(OPNsenseClient, "shaper_apply",
                        lambda self, mac, ip, uid: pytest.fail("apply не должен вызываться"))

    resp = logged_client.post(
        "/netcerber/htmx/shaper-apply/9",
        data={"csrf_token": _csrf_token(logged_client), "mac": "AA:BB:CC:DD:EE:99"},
    )

    assert "Не выбран канал" in resp.get_data(as_text=True)


def test_shaper_apply_requires_ip(app, logged_client, monkeypatch):
    """Шейпер матчит по IP: устройство без IP канал не получит."""
    from app.api.opnsense import OPNsenseClient

    _enable_shaper(app)
    nodata = dict(_BLOCK_DEVICE, ip_address="")
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: nodata)
    monkeypatch.setattr(OPNsenseClient, "shaper_apply",
                        lambda self, mac, ip, uid: pytest.fail("apply не должен вызываться"))

    resp = logged_client.post(
        "/netcerber/htmx/shaper-apply/9",
        data={
            "csrf_token": _csrf_token(logged_client),
            "mac": "AA:BB:CC:DD:EE:99",
            "channel": "pipe-a",
        },
    )

    assert "нет IP-адреса" in resp.get_data(as_text=True)


def test_shaper_apply_unknown_channel(app, logged_client, monkeypatch):
    """Оператор выбрал канал, которого нет на шлюзе — отказ."""
    from app.api.opnsense import OPNsenseClient

    _enable_shaper(app)
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))
    monkeypatch.setattr(OPNsenseClient, "shaper_pipe_name", lambda self, uid: None)
    monkeypatch.setattr(OPNsenseClient, "shaper_apply",
                        lambda self, mac, ip, uid: pytest.fail("apply не должен вызываться"))

    resp = logged_client.post(
        "/netcerber/htmx/shaper-apply/9",
        data={
            "csrf_token": _csrf_token(logged_client),
            "mac": "AA:BB:CC:DD:EE:99",
            "channel": "no-such-pipe",
        },
    )

    assert "канал не найден на шлюзе" in resp.get_data(as_text=True)


def test_shaper_apply_failure(app, logged_client, monkeypatch):
    """Сбой клиента — сообщение об ошибке, модалка закрыта."""
    from app.api.opnsense import OPNsenseClient, OPNsenseError

    _enable_shaper(app)
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))
    monkeypatch.setattr(OPNsenseClient, "shaper_pipe_name", lambda self, uid: "5Mbit")
    monkeypatch.setattr(
        OPNsenseClient, "shaper_apply",
        lambda self, mac, ip, uid: (_ for _ in ()).throw(OPNsenseError("gateway rejected")),
    )

    resp = logged_client.post(
        "/netcerber/htmx/shaper-apply/9",
        data={
            "csrf_token": _csrf_token(logged_client),
            "mac": "AA:BB:CC:DD:EE:99",
            "channel": "pipe-a",
        },
    )

    assert "не удалось применить канал" in resp.get_data(as_text=True)


def test_shaper_clear_device_success(app, logged_client, monkeypatch):
    """Снятие ограничения: правило удалено, кнопка «Снять» исчезает."""
    from app.api.opnsense import OPNsenseClient

    _enable_shaper(app)
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))
    calls = []
    monkeypatch.setattr(
        OPNsenseClient, "shaper_clear",
        lambda self, mac: calls.append(mac) or "шлюз: ограничение скорости снято",
    )
    monkeypatch.setattr(OPNsenseClient, "shaper_pipes", lambda self: [_shaper_channel("pipe-a", "5Mbit")])
    monkeypatch.setattr(OPNsenseClient, "shaper_device_status", lambda self, mac: None)

    resp = logged_client.post(
        "/netcerber/htmx/shaper-clear/9",
        data={"csrf_token": _csrf_token(logged_client), "mac": "AA:BB:CC:DD:EE:99"},
    )
    html = resp.get_data(as_text=True)

    assert calls == ["AA:BB:CC:DD:EE:99"]
    assert "Ограничение скорости (канал)" in html
    assert "Снять ограничение" not in html  # канал снят — действия нет


def test_shaper_card_shows_channels_and_current(app, logged_client, monkeypatch):
    """Карточка: селект каналов и текущий ограничивающий канал."""
    from app.api.opnsense import OPNsenseClient

    _enable_shaper(app)
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))
    monkeypatch.setattr(
        OPNsenseClient, "shaper_pipes",
        lambda self: [_shaper_channel("pipe-a", "5Mbit"), _shaper_channel("pipe-b", "10Mbit")],
    )
    monkeypatch.setattr(
        OPNsenseClient, "shaper_device_status",
        lambda self, mac: _shaped_rule("AABBCCDDEE99", "pipe-b", "192.168.0.77"),
    )

    resp = logged_client.get("/netcerber/htmx/device/9")
    html = resp.get_data(as_text=True)

    assert "Ограничение скорости (канал)" in html
    assert 'value="pipe-a"' in html and 'value="pipe-b" selected' in html
    assert "10Mbit" in html


def test_shaper_card_hidden_when_disabled(logged_client, monkeypatch):
    """Шейпер выключен — блок про канал в карточке отсутствует."""
    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: dict(_BLOCK_DEVICE))

    resp = logged_client.get("/netcerber/htmx/device/9")

    assert "Ограничение скорости (канал)" not in resp.get_data(as_text=True)


def test_ad_resolve_404_is_not_an_error(logged_client, monkeypatch, caplog):
    """404 от LogSpy (IP вне AD) — штатный ответ: None без шума в журнале."""
    import requests as requests_lib

    def not_found(self, ip_address):
        resp = requests_lib.Response()
        resp.status_code = 404
        raise requests_lib.HTTPError("404 Not Found", response=resp)

    monkeypatch.setattr(LogSpyClient, "ad_resolve_ip", not_found)

    with caplog.at_level("INFO", logger="app.routes.netcerber"):
        device = {
            "id": 5,
            "ip_address": "192.168.0.66",
            "mac_address": "AA:BB:CC:DD:EE:66",
            "hostname": "",
            "vendor": "",
            "is_authorized": False,
        }
        monkeypatch.setattr(NetCerberClient, "get_device", lambda self, did: device)
        logged_client.get("/netcerber/htmx/device/5")

    # Ни строчки про ошибку resolve; страница рендерится с модалкой
    assert "LogSpy AD resolve" not in caplog.text


# ── Дубли по IP: группировка, история, чистка ────────────────

_DUPES_DEVICES = {
    "items": [
        {   # Устаревшая запись: прежний владелец IP (роутер из инцидента)
            "id": 1,
            "ip_address": "192.168.0.37",
            "mac_address": "AA:BB:CC:00:00:01",
            "hostname": "",
            "vendor": "TP-LINK TECHNOLOGIES CO.,LTD.",
            "is_authorized": False,
            "last_seen": _iso(hours=4),
            "first_seen": _iso(days=5),
        },
        {   # Свежайшая запись этого IP (текущий хост)
            "id": 2,
            "ip_address": "192.168.0.37",
            "mac_address": "AA:BB:CC:00:00:02",
            "hostname": "zr-37",
            "vendor": "Gigabyte Technology",
            "is_authorized": True,
            "last_seen": _iso(hours=1),
            "first_seen": _iso(hours=2),
        },
    ],
    "total": 2,
}


def _dupes_payload() -> dict:
    """Свежие копии записей на каждый вызов, как реальный ответ API.

    Важно для честности тестов: группировка навешивает "_history" на
    сами объекты записей, и общий мок между вызовами маскировал баг
    потери истории при рендере.
    """
    return {
        "items": [dict(d) for d in _DUPES_DEVICES["items"]],
        "total": len(_DUPES_DEVICES["items"]),
    }


def test_netcerber_dedupes_by_ip_by_default(logged_client, monkeypatch):
    """По умолчанию показывается одна свежайшая запись IP с бейджем ×N."""
    monkeypatch.setattr(
        NetCerberClient, "get_devices", lambda self, **kw: _dupes_payload()
    )
    html = logged_client.get("/netcerber/").get_data(as_text=True)

    # Первичная строка одна, история скрыта
    assert html.count("zr-37") == 1
    assert "×2 записей" in html
    # Чип со счётчиком дублей
    assert "Дубли по IP (1)" in html


def test_netcerber_dupes_show_renders_history(logged_client, monkeypatch):
    """dupes=1 разворачивает устаревшие записи тусклыми строками."""
    monkeypatch.setattr(
        NetCerberClient, "get_devices", lambda self, **kw: _dupes_payload()
    )
    html = logged_client.get("/netcerber/?dupes=1").get_data(as_text=True)

    assert "устаревшая запись" in html
    # MAC устаревшей записи: в строке истории и в тултипе бейджа ×N
    assert html.count("AA:BB:CC:00:00:01") == 2
    assert "Скрыть историю IP" in html


def test_netcerber_cleanup_duplicates_keeps_freshest(
    logged_client, monkeypatch
):
    """Чистка удаляет только устаревшие записи указанного IP."""
    deleted = []
    # Мок с изменяемым состоянием: delete реально убирает запись,
    # чтобы последующая выборка в ответе это отразила
    data = {"items": [dict(d) for d in _DUPES_DEVICES["items"]], "total": 2}

    def fake_get(self, **kw):
        return data

    def fake_delete(self, device_id):
        deleted.append(device_id)
        data["items"] = [d for d in data["items"] if d["id"] != device_id]
        data["total"] = len(data["items"])
        return {}

    monkeypatch.setattr(NetCerberClient, "get_devices", fake_get)
    monkeypatch.setattr(NetCerberClient, "delete_device", fake_delete)

    resp = logged_client.post(
        "/netcerber/htmx/cleanup-duplicates?ip=192.168.0.37&sort=ip&order=asc",
        data={"csrf_token": _csrf_token(logged_client)},
    )

    assert deleted == [1]  # свежайшая (id=2) не тронута
    html = resp.get_data(as_text=True)
    # Список в ответе уже без бейджа дублей
    assert "×2 записей" not in html
    assert "AA:BB:CC:00:00:02" in html


def test_netcerber_cleanup_duplicates_idempotent(logged_client, monkeypatch):
    """Повторная чистка (дублей уже нет) не падает и обновляет список."""
    monkeypatch.setattr(NetCerberClient, "get_devices", lambda self, **kw: {"items": [], "total": 0})
    monkeypatch.setattr(
        NetCerberClient, "delete_device",
        lambda self, device_id: pytest.fail("удалять нечего"),
    )

    resp = logged_client.post(
        "/netcerber/htmx/cleanup-duplicates?ip=192.168.0.37",
        data={"csrf_token": _csrf_token(logged_client)},
    )

    assert resp.status_code == 200


def test_netcerber_broom_only_on_primary_rows(logged_client, monkeypatch):
    """Метёлка чистки — только у первичной записи с историей.

    Устаревшие строки (dupes=1) рисуются без кнопок действий.
    Регрессия: pop("_history") в _load_devices лишал шаблон данных,
    и бейдж ×N с метёлкой не рендерились вовсе (в тестах это
    маскировалось общим состоянием мока между вызовами).
    """
    monkeypatch.setattr(
        NetCerberClient, "get_devices", lambda self, **kw: _dupes_payload()
    )

    show_html = logged_client.get("/netcerber/?dupes=1").get_data(as_text=True)
    assert "устаревшая запись" in show_html          # история развёрнута
    assert show_html.count("fa-broom") == 1          # одна группа → одна метёлка

    hide_html = logged_client.get("/netcerber/").get_data(as_text=True)
    assert "×2 записей" in hide_html                 # бейдж на первичной
    assert hide_html.count("fa-broom") == 1


def test_netcerber_authorize_all_updates_list(logged_client):
    """«Авторизовать все» обновляет список в фоне."""
    resp = logged_client.post(
        "/netcerber/htmx/authorize-all",
        data={"csrf_token": _csrf_token(logged_client)},
    )
    html = resp.get_data(as_text=True)
    assert 'id="device-list" hx-swap-oob="true"' in html


def test_netcerber_list_has_oob_counter(logged_client):
    """Фрагмент списка обновляет счётчик в шапке через hx-swap-oob."""
    html = logged_client.get("/netcerber/htmx/list").get_data(as_text=True)
    assert 'id="device-count" hx-swap-oob="true"' in html


def test_netcerber_dhcp_filter(app, logged_client, monkeypatch):
    """При заданном DHCP-пуле фильтр cat=dhcp показывает устройства из пула."""
    from app.api.netcerber_client import NetCerberClient

    app.config["DHCP_POOL"] = "192.168.0.31,192.168.0.199"
    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )
    html = logged_client.get("/netcerber/htmx/list?cat=dhcp").get_data(as_text=True)
    assert "192.168.0.100" in html
    assert "192.168.0.201" not in html
    assert 'title="IP выдан DHCP-пулом (зона несанкционированных подключений)"' in html
    assert "В DHCP-пуле (1)" in html


def test_netcerber_dhcp_disabled_without_pool(app, logged_client, monkeypatch):
    """Без настройки пула признак выключен (чип со счётчиком 0, без бейджей)."""
    from app.api.netcerber_client import NetCerberClient

    app.config["DHCP_POOL"] = ""
    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )
    html = logged_client.get("/netcerber/htmx/list").get_data(as_text=True)
    assert 'title="IP выдан DHCP-пулом (зона несанкционированных подключений)"' not in html
    assert "В DHCP-пуле (0)" in html


def test_netcerber_dhcp_no_load_more_under_filter(app, logged_client, monkeypatch):
    """Под отфильтрованным списком (больше страницы) кнопка «Показать ещё»
    не должна появляться — фильтр показывает всю выборку целиком."""
    from app.api.netcerber_client import NetCerberClient

    app.config["DHCP_POOL"] = "192.168.0.31,192.168.0.199"

    def many_devices(self, **kwargs):
        return {
            "total": 150,
            "items": [
                {
                    "id": i,
                    "ip_address": f"192.168.0.{30 + i}",
                    "hostname": f"zr-pc-{i}.zr.local",
                    "vendor": "MSI",
                    "mac_address": f"aa:bb:cc:dd:ee:{i:02x}",
                    "first_seen": _iso(days=90),
                    "is_authorized": False,
                }
                for i in range(1, 151)
            ],
        }

    monkeypatch.setattr(NetCerberClient, "get_devices", many_devices)
    filtered = logged_client.get("/netcerber/htmx/list?cat=dhcp").get_data(as_text=True)
    assert "Показать ещё" not in filtered
    plain = logged_client.get("/netcerber/htmx/list").get_data(as_text=True)
    assert "Показать ещё (50)" in plain


def test_netcerber_modal_keeps_filters(logged_client, monkeypatch):
    """Модалка устройства получает текущие фильтры списка."""
    from app.api.netcerber_client import NetCerberClient

    monkeypatch.setattr(NetCerberClient, "get_device", lambda self, device_id: {
        "id": device_id, "ip_address": "192.168.0.201", "hostname": "dev",
        "is_authorized": False, "vendor": "TP-LINK", "mac_address": "aa:bb:cc:dd:ee:01",
    })
    html = logged_client.get(
        "/netcerber/htmx/device/1?cat=router&q=test&sort=ip&order=asc"
    ).get_data(as_text=True)
    assert 'name="cat" value="router"' in html
    assert 'name="q" value="test"' in html
    assert 'name="sort" value="ip"' in html


def test_dashboard_netcerber_counts(logged_client, monkeypatch):
    """Dashboard показывает счётчики NetCerber и топ новых устройств."""
    from app.api.netcerber_client import NetCerberClient

    monkeypatch.setattr(
        NetCerberClient, "get_devices",
        lambda self, **kwargs: _netcerber_devices_fixture(),
    )
    html = logged_client.get("/").get_data(as_text=True)
    # router: 1 (TP-LINK), new: 2 (TP-LINK + KYOCERA), unknown: 1
    assert ">2<" in html
    assert ">1<" in html
    assert "zr-printer-01.zr.local" in html
    assert "Новых устройств (7 дней)" in html


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
    import requests as requests_lib

    from app.api.logspy_client import LogSpyClient

    def boom(*args, **kwargs):
        # Клиенты raising'ают именно requests-исключения.
        raise requests_lib.ConnectionError("LogSpy down")

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


# ── Обработчик 500 ───────────────────────────────────────────


def _raise_runtime_error(self):
    raise RuntimeError("неожиданная форма ответа сервиса")


def test_500_renders_custom_page(app, logged_client, monkeypatch):
    """Непойманное исключение — страница errors/500.html, а не дефолт Werkzeug.

    В тестах Flask по умолчанию пробрасывает исключения наружу
    (PROPAGATE_EXCEPTIONS наследует TESTING); для проверки обработчика
    проброс отключается — как в рабочем режиме.
    """
    monkeypatch.setattr(PrinterMonitorClient, "get_printers", _raise_runtime_error)
    app.config["PROPAGATE_EXCEPTIONS"] = False

    response = logged_client.get("/printers/")

    assert response.status_code == 500
    html = response.get_data(as_text=True)
    assert "Что-то пошло не так" in html
    assert "На главную" in html


def test_500_fallback_when_template_breaks(app, logged_client, monkeypatch):
    """Если не рендерится сам шаблон ошибки — простой текстовый ответ 500."""

    def broken_template(*args, **kwargs):
        raise RuntimeError("шаблон недоступен")

    monkeypatch.setattr(PrinterMonitorClient, "get_printers", _raise_runtime_error)
    monkeypatch.setattr("app.render_template", broken_template)
    app.config["PROPAGATE_EXCEPTIONS"] = False

    response = logged_client.get("/printers/")

    assert response.status_code == 500
    assert "Внутренняя ошибка сервера" in response.get_data(as_text=True)


# ── Журнал сканирований NetCerber ────────────────────────────


def _csrf_token(client):
    """CSRF-токен текущей сессии (страница журнала содержит форму)."""
    page = client.get("/netcerber/scans/")
    return re.search(
        r'name="csrf_token" value="([^"]+)"',
        page.get_data(as_text=True),
    ).group(1)


def test_scan_delete_updates_list(logged_client):
    """Удаление записи перерисовывает журнал с сообщением."""
    resp = logged_client.post(
        "/netcerber/htmx/delete-scan/42",
        data={"csrf_token": _csrf_token(logged_client)},
    )
    html = resp.get_data(as_text=True)
    assert "Запись #42 удалена" in html
    assert "Сканирований не найдено" in html


def test_scan_batch_delete(logged_client, monkeypatch):
    """Групповое удаление удаляет каждый выбранный скан по очереди."""
    from app.api.netcerber_client import NetCerberClient

    deleted: list[int] = []

    def fake_delete(self, scan_id):
        deleted.append(scan_id)

    monkeypatch.setattr(NetCerberClient, "delete_scan", fake_delete)
    resp = logged_client.post(
        "/netcerber/htmx/delete-scans",
        data={"csrf_token": _csrf_token(logged_client),
              "scan_ids": ["1", "2", "3"]},
    )
    assert deleted == [1, 2, 3]
    assert "Удалено записей: 3" in resp.get_data(as_text=True)


def test_scan_batch_delete_empty(logged_client):
    """Без выбранных чекбоксов — сообщение, а не ошибка."""
    resp = logged_client.post(
        "/netcerber/htmx/delete-scans",
        data={"csrf_token": _csrf_token(logged_client)},
    )
    assert "Не выбрано записей" in resp.get_data(as_text=True)


def test_scan_set_baseline_updates_list(logged_client):
    """Установка эталона перерисовывает журнал (звёздочка обновляется)."""
    resp = logged_client.post(
        "/netcerber/htmx/set-baseline/42",
        data={"csrf_token": _csrf_token(logged_client)},
    )
    html = resp.get_data(as_text=True)
    assert "Эталонный снимок #42 установлен" in html
    assert "Сканирований не найдено" in html


def test_scan_page_has_batch_controls(logged_client):
    """Страница журнала содержит форму группового удаления."""
    html = logged_client.get("/netcerber/scans/").get_data(as_text=True)
    assert 'id="scan-batch-form"' in html
    assert "Удалить выбранные" in html
    assert 'id="scan-delete-selected"' in html


def test_scan_pagination(logged_client, monkeypatch):
    """Кнопка «Показать ещё» появляется, когда записей больше лимита."""
    from app.api.netcerber_client import NetCerberClient

    monkeypatch.setattr(
        NetCerberClient, "get_scans",
        lambda self, **kwargs: {
            "items": [{"id": i, "status": "completed"} for i in range(60)],
            "total": 60,
        },
    )
    html = logged_client.get("/netcerber/htmx/scans?limit=50").get_data(as_text=True)
    assert "Показать ещё (10)" in html

    html_all = logged_client.get("/netcerber/htmx/scans?limit=500").get_data(as_text=True)
    assert "Показать ещё" not in html_all


def test_scan_delete_keeps_position(logged_client, monkeypatch):
    """Удаление сохраняет позицию пагинации (skip/limit из формы)."""
    from app.api.netcerber_client import NetCerberClient

    monkeypatch.setattr(
        NetCerberClient, "get_scans",
        lambda self, **kwargs: {
            "items": [{"id": i, "status": "completed"} for i in range(60)],
            "total": 60,
        },
    )
    resp = logged_client.post(
        "/netcerber/htmx/delete-scan/42",
        data={"csrf_token": _csrf_token(logged_client), "skip": "50", "limit": "50"},
    )
    html = resp.get_data(as_text=True)
    assert "Запись #42 удалена" in html
    assert 'name="skip" value="50"' in html
    assert 'name="limit" value="50"' in html


# ── IP → AD в модалке устройства ──────────────────────────────


def test_netcerber_device_shows_ad_info(logged_client, monkeypatch):
    """В модалке устройства виден AD-компьютер за этим IP."""
    monkeypatch.setattr(
        NetCerberClient, "get_device",
        lambda self, device_id: {"id": device_id, "ip_address": "192.168.0.100"},
    )
    monkeypatch.setattr(
        LogSpyClient, "ad_resolve_ip",
        lambda self, ip: {
            "ip_address": ip,
            "username": "",
            "computer_name": "ZR-19",
            "source": "ad_computer",
        },
    )
    html = logged_client.get("/netcerber/htmx/device/1").get_data(as_text=True)
    assert "В AD" in html
    assert "ZR-19" in html


def test_netcerber_device_without_ad_info(logged_client):
    """Если сопоставление не найдено — строки «В AD» нет, модалка работает."""
    html = logged_client.get("/netcerber/htmx/device/1").get_data(as_text=True)
    assert "В AD" not in html
    assert "MAC" in html


# ── Планировщик автосканирований ──────────────────────────────


def test_netcerber_scheduler_block_active(logged_client):
    """Блок планировщика показывает статус и интервал из trigger-строки."""
    html = logged_client.get("/netcerber/htmx/scheduler").get_data(as_text=True)
    assert "Активно" in html
    assert 'name="interval_hours"' in html
    assert 'value="5.0"' in html


def test_netcerber_scheduler_toggle_pauses(logged_client, monkeypatch):
    paused = []
    monkeypatch.setattr(
        NetCerberClient, "scheduler_pause",
        lambda self: paused.append(True) or {},
    )
    html = logged_client.post(
        "/netcerber/htmx/scheduler/toggle",
        data={"csrf_token": _csrf_token(logged_client)},
    ).get_data(as_text=True)
    assert paused == [True]
    assert "паузу" in html


def test_netcerber_scheduler_interval_validation(logged_client, monkeypatch):
    called = []
    monkeypatch.setattr(
        NetCerberClient, "scheduler_set_interval",
        lambda self, interval: called.append(interval),
    )
    token = _csrf_token(logged_client)
    html = logged_client.post(
        "/netcerber/htmx/scheduler/interval",
        data={"interval_hours": "999", "csrf_token": token},
    ).get_data(as_text=True)
    assert "от 0.5 до 168" in html
    assert not called

    logged_client.post(
        "/netcerber/htmx/scheduler/interval",
        data={"interval_hours": "8", "csrf_token": token},
    )
    assert called == [28800]


# ── Здоровье сервисов в Настройках ────────────────────────────


def test_settings_shows_services_health(logged_client):
    html = logged_client.get("/settings/").get_data(as_text=True)
    assert "Сервисы" in html
    for name in ("Printer Monitor", "Host Monitor", "LogSpy", "NetCerber"):
        assert name in html
    assert ">OK</span>" in html


def test_settings_marks_unavailable_service(logged_client, monkeypatch):
    import requests as requests_lib

    def boom(self):
        raise requests_lib.ConnectionError("down")

    monkeypatch.setattr(HostMonitorClient, "get_stats", boom)
    html = logged_client.get("/settings/").get_data(as_text=True)
    assert "Недоступен" in html


# ── Устойчивость к мусорным параметрам и кэш счётчиков ───────


def test_netcerber_garbage_pagination_params(logged_client):
    """Мусор в skip/limit не роняет страницу и журнал (раньше — 500)."""
    assert logged_client.get("/netcerber/?limit=abc&skip=xyz").status_code == 200
    assert logged_client.get(
        "/netcerber/htmx/scans?limit=abc&skip=xyz"
    ).status_code == 200


def test_netcerber_counts_cached_between_requests(logged_client, monkeypatch):
    """Счётчики чипов кэшируются: повторная загрузка страницы не выгружает
    все устройства из API второй раз."""
    from app.api.netcerber_client import NetCerberClient

    calls: list[dict] = []

    def fake_devices(self, **kwargs):
        calls.append(kwargs)
        return {"items": [], "total": 0}

    monkeypatch.setattr(NetCerberClient, "get_devices", fake_devices)
    logged_client.get("/netcerber/")
    first = len(calls)
    assert first >= 2  # страница списка + полная выборка для счётчиков

    logged_client.get("/netcerber/")
    added = len(calls) - first
    assert added < first  # счётчики взяты из кэша — запросов меньше


# ── Вкладка «Компьютеры» на Users ─────────────────────────────


def test_users_computers_tab(logged_client, monkeypatch):
    monkeypatch.setattr(
        LogSpyClient, "get_ad_computers",
        lambda self, **kwargs: [
            {
                "name": "ZR-19",
                "dNSHostName": "zr-19.zr.local",
                "operatingSystem": "Windows 10 Pro",
                "ip_addresses": ["192.168.0.100"],
                "ou": "ZR",
            },
        ],
    )
    html = logged_client.get("/users/?view=computers").get_data(as_text=True)
    assert "Компьютеры AD" in html
    assert "ZR-19" in html
    assert "192.168.0.100" in html
    # Таблица пользователей не рендерится
    assert "Пользователи не найдены" not in html


def test_users_tab_switch_links(logged_client):
    html = logged_client.get("/users/").get_data(as_text=True)
    assert '/users/?view=computers' in html


def test_users_list_has_logs_spinner(logged_client, monkeypatch):
    """Список пользователей показывает оверлей «Просматриваю логи…»
    при клике по строке (долгий запрос к LogSpy на странице пользователя)."""
    from app.api.logspy_client import LogSpyClient

    monkeypatch.setattr(
        LogSpyClient, "get_ad_users",
        lambda self, **kwargs: [
            {
                "sAMAccountName": "Valentin.Gorohov",
                "displayName": "Валентин Горохов",
                "department": "ИТ",
                "title": "Админ",
                "ou": "OU=Users",
                "mail": "v.gorohov@zr.local",
                "telephoneNumber": "123",
                "enabled": True,
            }
        ],
    )
    html = logged_client.get("/users/").get_data(as_text=True)
    assert 'id="logs-spinner"' in html
    assert "Просматриваю логи…" in html
    assert 'id="user-detail-container"' in html
    # Список оборачивается в отдельный контейнер, который скрывается
    # при открытии пользователя (под деталью не остаётся списка)
    assert 'id="user-list-view"' in html
    # Строки пользователей грузят фрагмент через HTMX в контейнер
    assert 'hx-target="#user-detail-container"' in html
    assert 'hx-get="/users/Valentin.Gorohov"' in html
    assert 'hx-push-url="/users/Valentin.Gorohov"' in html
    assert "function showSpinner" in html


def test_user_detail_htmx_returns_fragment(logged_client):
    """HTMX-запрос возвращает фрагмент без базовой обёртки страницы.

    Фрагмент вставляется в #user-detail-container на странице списка,
    поэтому не должен содержать полноценный <html> (только контент).
    """
    html = logged_client.get(
        "/users/Valentin.Gorohov", headers={"HX-Request": "true"}
    ).get_data(as_text=True)
    assert "<!DOCTYPE html>" not in html
    assert "<html" not in html
    # контент фрагмента на месте
    assert "Заблокированные запросы" in html or "Все запросы" in html


# ── Валидация настроек Printer Monitor ────────────────────────


def test_settings_threshold_rejects_out_of_range(
    logged_client, monkeypatch
):
    """Порог вне 0–100 не уходит в API, показывается ошибка."""
    called = []
    monkeypatch.setattr(
        PrinterMonitorClient, "set_threshold",
        lambda self, threshold: called.append(threshold),
    )
    token = _csrf_token(logged_client)
    for bad in ("-5", "150"):
        html = logged_client.put(
            "/settings/htmx/threshold",
            data={"threshold": bad, "csrf_token": token},
        ).get_data(as_text=True)
        assert "от 0 до 100" in html
    assert not called


def test_settings_threshold_accepts_valid_value(
    logged_client, monkeypatch
):
    monkeypatch.setattr(
        PrinterMonitorClient, "set_threshold",
        lambda self, threshold: {"threshold": threshold},
    )
    html = logged_client.put(
        "/settings/htmx/threshold",
        data={"threshold": "35", "csrf_token": _csrf_token(logged_client)},
    ).get_data(as_text=True)
    assert "Порог установлен: 35%" in html


def test_settings_interval_rejects_out_of_range(
    logged_client, monkeypatch
):
    """Интервал вне 10–86400 сек не уходит в API."""
    called = []
    monkeypatch.setattr(
        PrinterMonitorClient, "set_check_interval",
        lambda self, interval: called.append(interval),
    )
    token = _csrf_token(logged_client)
    for bad in ("0", "999999"):
        html = logged_client.put(
            "/settings/htmx/interval",
            data={"interval": bad, "csrf_token": token},
        ).get_data(as_text=True)
        assert "от 10 до 86400" in html
    assert not called


def test_settings_interval_garbage_falls_back_to_default(
    logged_client, monkeypatch
):
    """Мусор во входе заменяется default (300) и проходит валидацию."""
    captured = {}

    def fake_set_interval(self, interval):
        captured["interval"] = interval
        return {"interval": interval}

    monkeypatch.setattr(
        PrinterMonitorClient, "set_check_interval", fake_set_interval,
    )
    logged_client.put(
        "/settings/htmx/interval",
        data={"interval": "abc", "csrf_token": _csrf_token(logged_client)},
    )
    assert captured["interval"] == 300


# ── Фильтр пользователя в Логах при пустом AD_DOMAIN ──────────


def test_logs_user_filter_without_ad_domain(logged_client, app, monkeypatch):
    """При пустом AD_DOMAIN домен к имени НЕ дописывается.

    Раньше фильтр превращался в "user@" и не совпадал ни с чем.
    """
    captured = {}

    def fake_get_data(self, filename, **kwargs):
        captured.update(kwargs)
        return {"records": [], "pagination": {"total_records": 0}}

    monkeypatch.setattr(LogSpyClient, "get_data", fake_get_data)
    app.config["AD_DOMAIN"] = ""
    logged_client.get("/logs/?user=ivanov")
    assert captured.get("user") == "ivanov"


def test_logs_user_filter_appends_configured_domain(
    logged_client, app, monkeypatch
):
    """Настроенный AD_DOMAIN дописывается к имени без '@'."""
    captured = {}

    def fake_get_data(self, filename, **kwargs):
        captured.update(kwargs)
        return {"records": [], "pagination": {"total_records": 0}}

    monkeypatch.setattr(LogSpyClient, "get_data", fake_get_data)
    app.config["AD_DOMAIN"] = "ZR.LOCAL"
    logged_client.get("/logs/?user=ivanov")
    assert captured.get("user") == "ivanov@ZR.LOCAL"


def test_logs_explicit_domain_not_duplicated(logged_client, app, monkeypatch):
    """Имя с '@' передаётся как есть — домен второй раз не приклеивается."""
    captured = {}

    def fake_get_data(self, filename, **kwargs):
        captured.update(kwargs)
        return {"records": [], "pagination": {"total_records": 0}}

    monkeypatch.setattr(LogSpyClient, "get_data", fake_get_data)
    app.config["AD_DOMAIN"] = "ZR.LOCAL"
    logged_client.get("/logs/?user=ivanov@OTHER.LOCAL")
    assert captured.get("user") == "ivanov@OTHER.LOCAL"


# ── Фабрики клиентов: кэширование на экземпляре приложения ────


def test_factories_cache_clients_on_app(app):
    """Повторный вызов фабрики возвращает того же клиента (keep-alive)."""
    from app.api.factories import (
        get_host_client,
        get_logspy_client,
        get_netcerber_client,
        get_printer_client,
    )

    with app.test_request_context():
        assert get_printer_client() is get_printer_client()
        assert get_host_client() is get_host_client()
        assert get_logspy_client() is get_logspy_client()
        assert get_netcerber_client() is get_netcerber_client()


def test_factories_clients_are_per_app():
    """У разных экземпляров приложения — разные клиенты (изоляция тестов)."""
    from app import create_app
    from app.api.factories import get_printer_client

    first = create_app()
    second = create_app()
    with first.test_request_context():
        first_client = get_printer_client()
    with second.test_request_context():
        second_client = get_printer_client()
    assert first_client is not second_client


# ── Баннеры недоступности в HTMX-фрагментах ───────────────────


def _raise_connection_error(self, *args, **kwargs):
    import requests as requests_lib

    raise requests_lib.ConnectionError("service down")


def test_hosts_htmx_fragment_shows_banner(logged_client, monkeypatch):
    """Фрагмент списка хостов при падении сервиса показывает баннер."""
    monkeypatch.setattr(HostMonitorClient, "get_hosts", _raise_connection_error)
    html = logged_client.get("/hosts/htmx/list").get_data(as_text=True)
    assert "недоступен" in html
    assert "Host Monitor" in html


def test_printers_htmx_fragment_shows_banner(logged_client, monkeypatch):
    monkeypatch.setattr(
        PrinterMonitorClient, "get_printers", _raise_connection_error
    )
    html = logged_client.get("/printers/htmx/list").get_data(as_text=True)
    assert "недоступен" in html
    assert "Printer Monitor" in html


def test_host_stats_fragment_shows_banner(logged_client, monkeypatch):
    monkeypatch.setattr(HostMonitorClient, "get_stats", _raise_connection_error)
    html = logged_client.get("/hosts/stats").get_data(as_text=True)
    assert "недоступен" in html


def test_netcerber_htmx_fragment_shows_banner(logged_client, monkeypatch):
    monkeypatch.setattr(NetCerberClient, "get_devices", _raise_connection_error)
    html = logged_client.get("/netcerber/htmx/list").get_data(as_text=True)
    assert "недоступен" in html
    assert "NetCerber" in html


def test_fragments_have_no_banner_on_success(logged_client):
    """При рабочем сервисе баннер во фрагменте не рендерится."""
    html = logged_client.get("/hosts/htmx/list").get_data(as_text=True)
    assert "недоступен" not in html


# ── Санитизация ошибок API (без утечки внутренней диагностики) ─


def test_stoplist_add_error_is_sanitized(logged_client, monkeypatch):
    """JSON-ошибка не содержит деталей соединения из исключения."""
    import requests as requests_lib

    def boom(self, words):
        raise requests_lib.ConnectionError(
            "http://10.255.0.5:8103/api/v1/stoplist: connection refused"
        )

    monkeypatch.setattr(LogSpyClient, "add_stoplist_words", boom)
    token = _csrf_token(logged_client)
    resp = logged_client.post(
        "/stoplist/add",
        data={"words": "casino\nbet", "csrf_token": token},
    )
    body = resp.get_data(as_text=True)
    assert resp.get_json() == {"error": "LogSpy недоступен"}
    assert "10.255.0.5" not in body


# ── Карточка пользователя: устойчивость параллельных запросов ──


def test_user_detail_survives_activity_failure(logged_client, monkeypatch):
    """Падение серверной статистики включает фолбэк и баннер."""
    import requests as requests_lib

    def real_boom(self, username, filename):
        raise requests_lib.ConnectionError("activity down")

    monkeypatch.setattr(LogSpyClient, "get_ad_user_activity", real_boom)
    monkeypatch.setattr(
        LogSpyClient, "get_data",
        lambda self, filename, **kwargs: {
            "records": [
                {
                    "user": "test@ZR.LOCAL",
                    "domain": "example.com",
                    "size": 2048,
                    "is_blocked": True,
                    "timestamp_human": "2026-08-24 10:00:00",
                },
            ],
            "pagination": {"total_records": 1},
        },
    )
    resp = logged_client.get("/users/testuser")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # Фолбэк посчитал статистику по записям выборки
    assert "2.0 KB" in html or "2 KB" in html
    # И показан баннер недоступности LogSpy
    assert "LogSpy" in html and "недоступен" in html


def test_user_detail_404_when_profile_unavailable(
    logged_client, monkeypatch
):
    """Если профиль не получен — 404, а не страница с пустыми полями."""
    import requests as requests_lib

    def boom(self, username):
        raise requests_lib.ConnectionError("profile down")

    monkeypatch.setattr(LogSpyClient, "get_ad_user", boom)
    resp = logged_client.get("/users/ghost")
    assert resp.status_code == 404
