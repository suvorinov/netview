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
    monkeypatch.setattr(
        NetCerberClient, "export_devices",
        lambda self, fmt="csv": "MAC,IP\n00:11:22:33:44:55,192.168.0.201\n",
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
                "first_seen": "2026-08-19T09:00:00",
                "is_authorized": False,
            },
            {
                "id": 2,
                "ip_address": "192.168.0.202",
                "hostname": "zr-pc-01.zr.local",
                "vendor": "ASUSTek COMPUTER INC.",
                "mac_address": "aa:bb:cc:dd:ee:02",
                "first_seen": "2026-06-01T09:00:00",
                "is_authorized": False,
            },
            {
                "id": 3,
                "ip_address": "192.168.0.203",
                "hostname": "zr-printer-01.zr.local",
                "vendor": "KYOCERA Display Corporation",
                "mac_address": "aa:bb:cc:dd:ee:03",
                "first_seen": "2026-08-19T09:00:00",
                "is_authorized": False,
            },
            {
                "id": 4,
                "ip_address": "192.168.0.100",
                "hostname": "zr-pc-02.zr.local",
                "vendor": "MSI",
                "mac_address": "aa:bb:cc:dd:ee:04",
                "first_seen": "2026-06-01T09:00:00",
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


def test_netcerber_export_csv(logged_client):
    """Экспорт отдаёт CSV-файл."""
    resp = logged_client.get("/netcerber/export?format=csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type
    assert "00:11:22:33:44:55" in resp.get_data(as_text=True)


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
                    "first_seen": "2026-06-01T09:00:00",
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
    def boom(self):
        raise ConnectionError("down")

    monkeypatch.setattr(HostMonitorClient, "get_stats", boom)
    html = logged_client.get("/settings/").get_data(as_text=True)
    assert "Недоступен" in html


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
