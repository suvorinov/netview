"""Тесты API-клиентов: параметры запросов и обработка ответов.

BaseApiClient тестируется на подменных ответах requests.Response —
без реальной сети. Проверяются контракты: JSON-декодирование,
пустой ответ, HTTP-ошибки, таймауты и невалидный JSON.
"""

import pytest
import requests

from app.api.base import BaseApiClient
from app.api.logspy_client import LogSpyClient


def _response(
    status: int = 200,
    body: bytes = b"",
    content_type: str = "application/json",
) -> requests.Response:
    """Собрать объект Response без сети."""
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp.headers["Content-Type"] = content_type
    return resp


def test_logspy_get_data_caps_limit(monkeypatch):
    """Лимит записей обрезается до максимума, который принимает API LogSpy:
    при limit=1000 сервис отвечает ошибкой валидации 422 (регрессия
    пустого HTML-отчёта о блокировках)."""
    captured: dict = {}

    def fake_get(self, path, params=None):
        captured.update(params or {})
        return {"records": []}

    monkeypatch.setattr(LogSpyClient, "_get", fake_get)

    LogSpyClient("http://test").get_data("access.log", limit=1000)

    assert captured["limit"] == LogSpyClient.MAX_LIMIT == 500


class TestBaseApiClient:
    """Контракты базового клиента: успех и классы ошибок."""

    def test_get_returns_decoded_json(self, monkeypatch):
        client = BaseApiClient("http://svc", timeout=5)
        monkeypatch.setattr(
            client._session,
            "request",
            lambda *a, **kw: _response(body=b'{"ok": true}'),
        )
        assert client._get("/api/x") == {"ok": True}

    def test_url_and_params_passed(self, monkeypatch):
        client = BaseApiClient("http://svc/", timeout=5)
        captured: dict = {}

        def fake_request(method, url, timeout=None, **kwargs):
            captured.update(url=url, timeout=timeout, **kwargs)
            return _response(body=b"[]")

        monkeypatch.setattr(client._session, "request", fake_request)
        result = client._get("/api/v1/hosts", {"page": 2})

        # Завершающий слеш base_url срезан, параметры переданы
        assert captured["url"] == "http://svc/api/v1/hosts"
        assert captured["timeout"] == 5
        assert captured["params"] == {"page": 2}
        assert result == []

    def test_empty_body_returns_none(self, monkeypatch):
        client = BaseApiClient("http://svc")
        monkeypatch.setattr(
            client._session, "request",
            lambda *a, **kw: _response(status=204),
        )
        assert client._delete("/api/x") is None

    def test_http_error_raises(self, monkeypatch):
        client = BaseApiClient("http://svc")
        monkeypatch.setattr(
            client._session, "request",
            lambda *a, **kw: _response(status=500, body=b'{"detail": "boom"}'),
        )
        with pytest.raises(requests.RequestException):
            client._get("/api/x")

    def test_timeout_raises_request_exception(self, monkeypatch):
        client = BaseApiClient("http://svc")

        def slow(*a, **kw):
            raise requests.Timeout("timed out")

        monkeypatch.setattr(client._session, "request", slow)
        # Таймаут — подкласс RequestException: маршруты ловят его как
        # «сервис недоступен».
        with pytest.raises(requests.RequestException):
            client._get("/api/x")

    def test_connection_error_raises(self, monkeypatch):
        client = BaseApiClient("http://svc")

        def down(*a, **kw):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(client._session, "request", down)
        with pytest.raises(requests.RequestException):
            client._post("/api/x", json={"a": 1})

    def test_invalid_json_raises_request_exception(self, monkeypatch):
        client = BaseApiClient("http://svc")
        monkeypatch.setattr(
            client._session, "request",
            lambda *a, **kw: _response(body=b"<html>not json</html>"),
        )
        # requests.JSONDecodeError — подкласс RequestException с
        # requests>=2.27, поэтому маршруты не падают 500-й.
        with pytest.raises(requests.RequestException):
            client._get("/api/x")

    def test_session_reused_between_calls(self, monkeypatch):
        """Один клиент держит одну Session — TCP keep-alive работает."""
        client = BaseApiClient("http://svc")
        session_a = client._session
        monkeypatch.setattr(
            client._session, "request",
            lambda *a, **kw: _response(body=b"{}"),
        )
        client._get("/a")
        client._get("/b")
        assert client._session is session_a
