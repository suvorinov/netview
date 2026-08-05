"""Конфигурация приложения NetView."""


class Config:
    """Базовая конфигурация приложения.

    Attributes:
        SECRET_KEY: Секретный ключ Flask.
        PRINTER_API_URL: URL Printer Monitor API.
        HOST_API_URL: URL Host Monitor API.
        DEBUG: Режим отладки.
    """

    SECRET_KEY = "change-me"
    PRINTER_API_URL = "http://localhost:8101"
    HOST_API_URL = "http://localhost:8102"
    LOGSPY_API_URL = "http://localhost:8103"
    NETCERBER_API_URL = "http://localhost:8104"
    AD_DOMAIN = "AD.LOCAL"
    DEBUG = True
