"""Инициализация приложения NetView.

Модуль содержит фабричную функцию create_app для создания
экземпляра Flask-приложения.
"""

import logging
from datetime import datetime

from flask import Flask, redirect, request, url_for
from flask_login import current_user
from flask_wtf import CSRFProtect

from app.auth import auth_bp, login_manager
from app.config import Config
from app.routes.dashboard import dashboard_bp
from app.routes.hosts import hosts_bp
from app.routes.logs import logs_bp
from app.routes.netcerber import netcerber_bp
from app.routes.printers import printers_bp
from app.routes.settings import settings_bp
from app.routes.stoplist import stoplist_bp
from app.routes.users import users_bp
from app.utils import human_size

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app(config_class=Config) -> Flask:
    """Фабричная функция для создания приложения.

    Args:
        config_class: Класс конфигурации. По умолчанию Config.

    Returns:
        Настроенный экземпляр Flask.
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    if config_class.SECRET_KEY_IS_RANDOM:
        logger.warning(
            "SECRET_KEY не задан в окружении — сгенерирован случайный, "
            "сессии будут сбрасываться при перезапуске"
        )
    if not config_class.AUTH_USERS:
        logger.warning("AUTH_USERS не задан — вход в систему будет невозможен")

    @app.template_filter("datetime")
    def _format_datetime(value):
        if not value:
            return "—"
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except (ValueError, TypeError):
                return value
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @app.template_filter("human_size")
    def _format_human_size(b):
        return human_size(b)

    @app.template_filter("time_ago")
    def _format_time_ago(value):
        if not value:
            return "—"
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except (ValueError, TypeError):
                return value
        diff = datetime.now() - value
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "только что"
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days > 0:
            return f"{days} дн. {hours} ч."
        if hours > 0:
            return f"{hours} ч. {minutes} мин."
        return f"{minutes} мин."

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(printers_bp, url_prefix="/printers")
    app.register_blueprint(hosts_bp, url_prefix="/hosts")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(logs_bp, url_prefix="/logs")
    app.register_blueprint(stoplist_bp, url_prefix="/stoplist")
    app.register_blueprint(netcerber_bp, url_prefix="/netcerber")

    login_manager.init_app(app)
    CSRFProtect(app)

    @app.before_request
    def require_login():
        """Требовать аутентификацию на всех страницах, кроме входа и статики.

        HTMX-фрагменты и API тоже закрыты: неавторизованный запрос получит
        редирект на страницу входа.
        """
        if current_user.is_authenticated:
            return None
        # Разрешённые без входа: страница логина и статические файлы.
        if request.endpoint in ("auth.login", "static") or request.endpoint is None:
            return None
        return redirect(url_for("auth.login", next=request.full_path))

    @app.after_request
    def log_response(response):
        """Логировать ответы с информацией о клиенте."""
        if response.status_code == 404:
            logger.warning(
                "404 от %s | %s %s | User-Agent: %s",
                request.remote_addr,
                request.method,
                request.path,
                request.user_agent.string
            )
        return response

    return app
