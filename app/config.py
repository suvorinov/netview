"""Конфигурация приложения NetView.

Все параметры выносятся на переменные окружения, чтобы секреты и адреса
сервисов не попадали в репозиторий. Значения по умолчанию — только для
локальной разработки.
"""

import os
import secrets


def _env_bool(name: str, default: bool = False) -> bool:
    """Прочитать переменную окружения как булево значение.

    Принимаются: 1/0, true/false, yes/no (без учёта регистра).
    """
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    """Базовая конфигурация приложения.

    Attributes:
        SECRET_KEY: Секретный ключ Flask. Если не задан через env,
            генерируется случайный — сессии сбрасываются при перезапуске.
        SECRET_KEY_IS_RANDOM: True, если ключ сгенерирован автоматически.
        PRINTER_API_URL: URL Printer Monitor API.
        HOST_API_URL: URL Host Monitor API.
        LOGSPY_API_URL: URL LogSpy API.
        NETCERBER_API_URL: URL NetCerber API.
        AD_DOMAIN: Домен Active Directory (для подстановки в фильтры логов).
        AUTH_USERS: Учётные записи для входа в формате "user:pass,user2:pass2".
            Пароль может быть передан как pbkdf2-хеш werkzeug
            (сгенерировать: python -c "from werkzeug.security import
            generate_password_hash; print(generate_password_hash('pass'))").
        DEBUG: Режим отладки (включается через DEBUG=1).
    """

    SECRET_KEY_IS_RANDOM = "SECRET_KEY" not in os.environ
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    # Внутренние сервисы задаются через env-переменные; дефолт — локальная
    # разработка (сервисы на том же хосте).
    PRINTER_API_URL = os.environ.get("PRINTER_API_URL", "http://localhost:8101")
    HOST_API_URL = os.environ.get("HOST_API_URL", "http://localhost:8102")
    LOGSPY_API_URL = os.environ.get("LOGSPY_API_URL", "http://localhost:8103")
    NETCERBER_API_URL = os.environ.get("NETCERBER_API_URL", "http://localhost:8104")
    AD_DOMAIN = os.environ.get("AD_DOMAIN", "")

    # Формат: "user1:pass1,user2:pass2"
    AUTH_USERS = os.environ.get("AUTH_USERS", "")

    DEBUG = _env_bool("DEBUG", default=False)
