"""Общие фикстуры для тестов NetView."""

import os
import re

import pytest

os.environ["SECRET_KEY"] = "test-secret"
os.environ["AUTH_USERS"] = "admin:admin123"

from app import create_app  # noqa: E402


@pytest.fixture()
def app():
    app = create_app()
    app.config.update(TESTING=True)
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username="admin", password="admin123"):
    """Войти в приложение через форму логина, вернуть ответ."""
    page = client.get("/login")
    token = re.search(
        r'name="csrf_token" value="([^"]+)"',
        page.get_data(as_text=True),
    ).group(1)
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
    )


@pytest.fixture()
def logged_client(client):
    login(client)
    return client
