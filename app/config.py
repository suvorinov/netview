"""Конфигурация приложения NetView.

Все параметры выносятся на переменные окружения, чтобы секреты и адреса
сервисов не попадали в репозиторий. Значения по умолчанию — только для
локальной разработки.

Файл .env (см. .env.example) читается автоматически при локальном запуске
(make run / make dev / python run.py). Docker-развёртывание в нём не
нуждается: переменные туда приносит compose (env_file), а сам .env в
образ не копируется.
"""

import os
import secrets


def load_env_file(path: str = ".env") -> dict[str, str]:
    """Прочитать файл переменных окружения вида KEY=VALUE.

    Вызывается автоматически из этого модуля, поэтому локальный запуск
    подхватывает .env так же, как это делает docker compose. Правила:

    - существующие переменные окружения имеют приоритет (setdefault):
      то, что задано снаружи, файл не перебивает;
    - строки-комментарии (#) и пустые — пропускаются;
    - обрамляющие одинарные/двойные кавычки у значения снимаются;
    - строки без "=" игнорируются.

    Args:
        path: Путь к файлу относительно текущего каталога.

    Returns:
        Разобранные пары {ключ: значение} (только валидные строки).
    """
    parsed: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return parsed  # файла нет — это норма (Docker, CI)
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key:
            continue
        parsed[key] = value
        os.environ.setdefault(key, value)
    return parsed


# Читаем до определения Config: класс ниже читает os.environ на импорте.
load_env_file()


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
        DHCP_POOL: Диапазон DHCP-пула "начало,конец" (признак в NetCerber).
        DEBUG: Режим отладки (включается через DEBUG=1).
        SESSION_COOKIE_HTTPONLY/SAMESITE/SECURE: Флаги cookie-сессии;
            SECURE включайте только при работе через HTTPS.
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

    # Таймауты запросов к сервисам, секунды. Единый формат для всех
    # клиентов: каждый настраивается отдельной переменной, чтоб не менять
    # код под специфику одного сервиса. Дефолт каждого — его естественное
    # значение (см. конструкторы клиентов). LogSpy по умолчанию 60 с:
    # запрос сведений о пользователе (/api/v1/data) парсит большой
    # лог-файл и на медленной машине может отвечать дольше 15 с.
    PRINTER_TIMEOUT = float(os.environ.get("PRINTER_TIMEOUT", "60"))
    HOST_TIMEOUT = float(os.environ.get("HOST_TIMEOUT", "10"))
    LOGSPY_TIMEOUT = float(os.environ.get("LOGSPY_TIMEOUT", "60"))
    NETCERBER_TIMEOUT = float(os.environ.get("NETCERBER_TIMEOUT", "15"))

    # Диапазон DHCP-пула в формате "192.168.0.31,192.168.0.199".
    # Используется как признак "устройство в DHCP-пуле" в NetCerber.
    # Пустая строка — признак выключен.
    DHCP_POOL = os.environ.get("DHCP_POOL", "")

    # Формат: "user1:pass1,user2:pass2"
    AUTH_USERS = os.environ.get("AUTH_USERS", "")

    DEBUG = _env_bool("DEBUG", default=False)

    # Флаги cookie-сессии.
    # SAMESITE=Lax включён всегда: дополнительный слой защиты от CSRF
    # поверх flask-wtf, обычные переходы по ссылкам не ломает.
    # SECURE (cookie только по HTTPS) выключен по умолчанию, чтобы не
    # сломать внутренние развёртывания по HTTP; при работе через HTTPS
    # задайте SESSION_COOKIE_SECURE=1 в окружении.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=False)

    # ── OPNsense (TING): блокировка на шлюзе по MAC ─────────────
    # Рубеж защиты на самом шлюзе (OPNsense, модуль os-firewall):
    # алиас type=mac + правило action=block (source=алиас) в начале
    # списка режут весь трафик роугера — интернет и LAN, по MAC.
    OPNSENSE_ENABLED = _env_bool("OPNSENSE_ENABLED", default=False)
    # Ограничение скорости на шлюзе (Traffic Shaper): управление
    # «каналами» из карточки устройства. Включается отдельно от
    # блокировки (креды те же, API trafficshaper/settings).
    OPNSENSE_SHAPER_ENABLED = _env_bool("OPNSENSE_SHAPER_ENABLED", default=False)
    # URL веб-интерфейса шлюза, например "http://192.168.0.1".
    OPNSENSE_URL = os.environ.get("OPNSENSE_URL", "")
    # Пара API-ключ:секрет (System → Access → Users → API keys).
    OPNSENSE_KEY = os.environ.get("OPNSENSE_KEY", "")
    OPNSENSE_SECRET = os.environ.get("OPNSENSE_SECRET", "")
    # Таймаут запросов к шлюзу, секунды.
    OPNSENSE_TIMEOUT = float(os.environ.get("OPNSENSE_TIMEOUT", "10"))
    # Защищённые MAC через запятую — блокировка на шлюзе запрещена.
    OPNSENSE_PROTECTED_MACS = os.environ.get("OPNSENSE_PROTECTED_MACS", "")
