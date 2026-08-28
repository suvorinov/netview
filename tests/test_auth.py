"""Тесты аутентификации и CSRF-защиты."""

import pytest
from conftest import login

from app import auth as auth_module


@pytest.fixture(autouse=True)
def _clean_login_failures():
    """Очистить счётчик неудачных попыток между тестами.

    Лимит живёт в состоянии модуля app.auth и без очистки перетекал бы
    из одного теста в другой (все клиенты ходят с одного IP).
    """
    auth_module._login_failures.clear()
    yield
    auth_module._login_failures.clear()


def _post_login(client, username="admin", password="admin123"):
    """Отправить форму входа напрямую (с CSRF-токеном со страницы)."""
    page = client.get("/login")
    token = _extract_csrf(page.get_data(as_text=True))
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
    )


def test_anonymous_redirect_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_anonymous_cannot_access_htmx(client):
    response = client.get("/hosts/htmx/list")
    assert response.status_code == 302


def test_login_page_has_csrf_token(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'name="csrf_token"' in html


def test_login_without_csrf_rejected(client):
    response = client.post(
        "/login", data={"username": "admin", "password": "admin123"}
    )
    assert response.status_code == 400


def test_login_wrong_password(client):
    response = login(client, password="wrong")
    assert response.status_code == 200
    assert "Неверное имя" in response.get_data(as_text=True)


def test_login_lockout_after_max_failures(client):
    """После лимита неудачных попыток вход блокируется на время окна."""
    for _ in range(auth_module._LOGIN_MAX_FAILURES):
        response = _post_login(client, password="wrong")
        assert "Неверное имя" in response.get_data(as_text=True)

    response = _post_login(client, password="wrong")
    assert "Слишком много неудачных попыток" in response.get_data(as_text=True)


def test_lockout_blocks_correct_password_too(client):
    """Блокировка не раскрывает, верен ли пароль: верный тоже отклонён."""
    for _ in range(auth_module._LOGIN_MAX_FAILURES):
        _post_login(client, password="wrong")

    response = _post_login(client)  # правильный admin:admin123
    assert response.status_code == 200
    assert "Слишком много неудачных попыток" in response.get_data(as_text=True)
    # И пользователь НЕ вошёл
    assert client.get("/").status_code == 302


def test_successful_login_resets_failures(client):
    """Успешный вход сбрасывает счётчик: пара неудач до него не блокирует."""
    _post_login(client, password="wrong")
    _post_login(client, password="wrong")
    assert _post_login(client).status_code == 302  # успешный вход

    # После выхода и выхода из счётчика — снова можно ошибаться
    page = client.get("/")
    token = _extract_csrf(page.get_data(as_text=True))
    client.post("/logout", data={"csrf_token": token})

    for _ in range(auth_module._LOGIN_MAX_FAILURES - 1):
        assert "Неверное имя" in _post_login(client, password="nope").get_data(
            as_text=True
        )


def test_login_success(client):
    response = login(client)
    assert response.status_code == 302


def test_post_without_csrf_rejected(client):
    login(client)
    response = client.post("/printers/check")
    assert response.status_code == 400


def test_post_with_csrf_header_allowed(client):
    login(client)
    token = _extract_meta_csrf(client.get("/"))
    response = client.post("/printers/check", headers={"X-CSRFToken": token})
    # Сервис недоступен в тесте, но CSRF пройден: 200 с сообщением об ошибке
    assert response.status_code == 200


def test_put_with_csrf_field_allowed(client):
    login(client)
    token = _extract_meta_csrf(client.get("/"))
    response = client.put(
        "/settings/htmx/threshold",
        data={"threshold": 25, "csrf_token": token},
    )
    assert response.status_code == 200


def _logout(client) -> None:
    """Выйти через POST-форму (с CSRF-токеном со страницы дашборда)."""
    page = client.get("/")
    token = _extract_csrf(page.get_data(as_text=True))
    client.post("/logout", data={"csrf_token": token})


def test_logout_returns_to_login(client):
    login(client)
    page = client.get("/")
    token = _extract_csrf(page.get_data(as_text=True))
    response = client.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_logout_get_rejected(client):
    """GET /logout больше не разлогинивает (защита от logout CSRF)."""
    login(client)
    response = client.get("/logout")
    assert response.status_code == 405
    # Пользователь остался залогинен
    assert client.get("/").status_code == 200


def test_after_logout_redirects_again(client):
    login(client)
    _logout(client)
    response = client.get("/")
    assert response.status_code == 302


def test_next_redirect_after_login(client):
    page = client.get("/login?next=/hosts/")
    token = _extract_csrf(page.get_data(as_text=True))
    response = client.post(
        "/login?next=/hosts/",
        data={"username": "admin", "password": "admin123", "csrf_token": token},
    )
    assert response.status_code == 302
    assert "/hosts/" in response.headers["Location"]


def test_login_rotates_session_cookie(client):
    """При входе cookie сессии меняется (защита от session fixation)."""
    client.get("/login")
    assert _session_value(client) is not None
    before = _session_value(client)
    login(client)
    assert _session_value(client) != before


def test_session_cookie_flags(client):
    """Флаги cookie сессии: HttpOnly + SameSite=Lax, Secure по умолчанию нет."""
    client.get("/login")
    cookie = client.get_cookie("session")
    assert cookie is not None
    assert cookie.http_only is True
    assert cookie.same_site == "Lax"
    # Внутренние развёртывания по HTTP не должны ломаться по умолчанию
    assert cookie.secure is False


def _session_value(client):
    """Значение session-cookie текущего клиента или None."""
    cookie = client.get_cookie("session")
    return cookie.value if cookie else None


def _extract_csrf(html: str) -> str:
    import re

    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def _extract_meta_csrf(response) -> str:
    import re

    return re.search(
        r'<meta name="csrf-token" content="([^"]+)"',
        response.get_data(as_text=True),
    ).group(1)
