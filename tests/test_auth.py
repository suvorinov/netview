"""Тесты аутентификации и CSRF-защиты."""

from conftest import login


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


def test_logout_returns_to_login(client):
    login(client)
    response = client.get("/logout")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_after_logout_redirects_again(client):
    login(client)
    client.get("/logout")
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


def _extract_csrf(html: str) -> str:
    import re

    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def _extract_meta_csrf(response) -> str:
    import re

    return re.search(
        r'<meta name="csrf-token" content="([^"]+)"',
        response.get_data(as_text=True),
    ).group(1)
