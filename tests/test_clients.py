"""Тесты API-клиентов: параметры запросов к внутренним сервисам."""

from app.api.logspy_client import LogSpyClient


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
