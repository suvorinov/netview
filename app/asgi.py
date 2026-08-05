"""ASGI entrypoint for uvicorn (WSGI-to-ASGI bridge)."""

from uvicorn.middleware.wsgi import WSGIMiddleware

from app import create_app

application = WSGIMiddleware(create_app())
