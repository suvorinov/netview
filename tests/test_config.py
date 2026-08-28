"""Тесты авто-загрузки .env при локальном запуске (app.config.load_env_file)."""

import os

from app.config import load_env_file


def test_parse_rules(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# комментарий\n"
        "\n"
        "PLAIN=value\n"
        "QUOTED=\"в кавычках\"\n"
        "SINGLE='одинарных'\n"
        "SPACED =  с пробелами  \n"
        "без_равно_игнорируется\n"
        "=без_ключа\n",
        encoding="utf-8",
    )
    parsed = load_env_file(str(env_file))

    assert parsed["PLAIN"] == "value"
    assert parsed["QUOTED"] == "в кавычках"
    assert parsed["SINGLE"] == "одинарных"
    assert parsed["SPACED"] == "с пробелами"
    # Мусорные строки не попали
    assert len(parsed) == 4


def test_existing_env_wins(tmp_path, monkeypatch):
    """Реальное окружение приоритетнее файла: setdefault не перебивает."""
    env_file = tmp_path / ".env"
    env_file.write_text("NV_TEST_KEY=from_file\n", encoding="utf-8")
    monkeypatch.setenv("NV_TEST_KEY", "from_env")

    load_env_file(str(env_file))

    assert os.environ["NV_TEST_KEY"] == "from_env"
    monkeypatch.delenv("NV_TEST_KEY")


def test_missing_file_is_not_an_error(tmp_path):
    """Нет файла (Docker/CI) — тихий пустой результат, не исключение."""
    assert load_env_file(str(tmp_path / "нет-такого.env")) == {}
