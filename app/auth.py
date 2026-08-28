"""Аутентификация NetView.

Пользователи задаются переменной окружения AUTH_USERS в формате:
    "admin:secret,user2:pass2"

Пароль можно хранить открытым текстом (внутренняя сеть) или в виде
pbkdf2-хеша werkzeug — тогда запись выглядит так:
    "admin:pbkdf2:sha256:260000$<salt>$<hash>"
Сгенерировать хеш:
    python -c "from werkzeug.security import generate_password_hash; \
    print(generate_password_hash('my-password'))"
"""

import hmac
import logging
import threading
import time

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
from werkzeug.security import check_password_hash

auth_bp = Blueprint("auth", __name__)

logger = logging.getLogger(__name__)

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Войдите, чтобы продолжить"
login_manager.login_message_category = "info"

# Защита от перебора паролей: не более _LOGIN_MAX_FAILURES неудачных
# попыток за окно _LOGIN_WINDOW_SECONDS с одного IP. Скользящее окно
# вместо паузы в обработчике: запрос отклоняется сразу и не удерживает
# поток сервера. Счётчики живут в памяти процесса и сбрасываются при
# перезапуске — для внутренней панели этого достаточно. Lock нужен:
# Flask обрабатывает запросы в нескольких потоках.
_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 60.0
_login_failures: dict[str, list[float]] = {}
_login_lock = threading.Lock()


class User(UserMixin):
    """Минимальная модель пользователя для Flask-Login.

    Единственный источник истины — строка AUTH_USERS из конфигурации.
    """

    def __init__(self, username: str) -> None:
        self.id = username


def _parse_users() -> dict[str, str]:
    """Разобрать AUTH_USERS ("user:pass,user2:pass2") в словарь.

    Returns:
        Словарь {имя: пароль}. Пусто, если пользователи не настроены.
    """
    users: dict[str, str] = {}
    raw = current_app.config.get("AUTH_USERS", "")
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            logger.warning("AUTH_USERS: пропущена запись без ':' — %r", entry)
            continue
        name, password = entry.split(":", 1)
        users[name.strip()] = password
    return users


def _verify_password(password: str, stored: str) -> bool:
    """Сравнить введённый пароль с хранимым.

    Хеши pbkdf2 (werkzeug) проверяются через check_password_hash,
    открытые пароли — через constant-time сравнение.
    """
    if stored.startswith("pbkdf2:"):
        return check_password_hash(stored, password)
    return hmac.compare_digest(stored, password)


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    """Загрузить пользователя по id (имени) для Flask-Login."""
    users = _parse_users()
    return User(user_id) if user_id in users else None


def _has_configured_users() -> bool:
    return bool(_parse_users())


def _client_key() -> str:
    """Ключ лимита попыток: IP клиента (или заглушка, если его нет)."""
    return request.remote_addr or "unknown"


def _register_failure(key: str) -> bool:
    """Записать неудачную попытку входа с ключа key.

    Args:
        key: Идентификатор источника попыток (IP).

    Returns:
        True, если лимит попыток за окно превышен — вход нужно
        отклонить сообщением о блокировке, не проверяя пароль
        (иначе блокировка не мешает перебору).
    """
    now = time.monotonic()
    with _login_lock:
        recent = [
            ts for ts in _login_failures.get(key, [])
            if now - ts < _LOGIN_WINDOW_SECONDS
        ]
        recent.append(now)
        _login_failures[key] = recent
        return len(recent) > _LOGIN_MAX_FAILURES


def _reset_failures(key: str) -> None:
    """Успешный вход сбрасывает счётчик неудачных попыток."""
    with _login_lock:
        _login_failures.pop(key, None)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Страница входа и обработчик формы.

    При успешном входе возвращает на страницу, с которой пользователь
    пришёл (параметр next), либо на главную.
    """
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not _has_configured_users():
            logger.warning("Попытка входа, но AUTH_USERS не настроен")
            flash("Вход не настроен: задайте AUTH_USERS", "error")
        else:
            users = _parse_users()
            stored = users.get(username)
            ip_key = _client_key()
            if _register_failure(ip_key):
                logger.warning(
                    "Превышен лимит попыток входа (IP %s): %s", ip_key, username
                )
                flash(
                    "Слишком много неудачных попыток. Попробуйте через минуту",
                    "error",
                )
            elif stored and _verify_password(password, stored):
                _reset_failures(ip_key)
                # Сброс старой сессии перед входом — защита от session
                # fixation: злоумышленник не может подсунуть жертве
                # заранее известный идентификатор сессии.
                session.clear()
                login_user(User(username))
                logger.info("Вход: %s (IP %s)", username, ip_key)
                next_url = request.args.get("next")
                if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect(url_for("dashboard.index"))
            else:
                logger.warning("Неудачный вход (IP %s): %s", ip_key, username)
                flash("Неверное имя пользователя или пароль", "error")

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Выйти из системы.

    Только POST (с CSRF-токеном): GET-ссылка позволяла разлогинить
    пользователя картинкой `<img src="/logout">` на сторонней странице.
    """
    name = current_user.id if current_user.is_authenticated else None
    logout_user()
    if name:
        logger.info("Выход: %s", name)
    return redirect(url_for("auth.login"))
