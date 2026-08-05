"""Инициализация приложения NetView.

Модуль содержит фабричную функцию create_app для создания
экземпляра Flask-приложения.
"""

import logging
from datetime import datetime

from flask import Flask, request

from app.config import Config
from app.routes.dashboard import dashboard_bp
from app.routes.printers import printers_bp
from app.routes.hosts import hosts_bp
from app.routes.settings import settings_bp
from app.routes.users import users_bp
from app.routes.logs import logs_bp
from app.routes.stoplist import stoplist_bp
from app.routes.netcerber import netcerber_bp

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
        if b is None:
            return "—"
        try:
            b = int(b)
        except (TypeError, ValueError):
            return str(b)
        if b < 0:
            return str(b)
        if b < 1024:
            return f"{b} B"
        for unit in ("KB", "MB", "GB", "TB", "PB"):
            b /= 1024
            if b < 1024:
                if b >= 100:
                    return f"{b:.0f} {unit}"
                return f"{b:.1f} {unit}"
        return f"{b:.1f} EB"

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

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(printers_bp, url_prefix="/printers")
    app.register_blueprint(hosts_bp, url_prefix="/hosts")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(logs_bp, url_prefix="/logs")
    app.register_blueprint(stoplist_bp, url_prefix="/stoplist")
    app.register_blueprint(netcerber_bp, url_prefix="/netcerber")

    @app.before_request
    def log_unknown_requests():
        """Логировать неизвестные запросы с User-Agent."""
        pass

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
