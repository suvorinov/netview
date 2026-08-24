"""Точка входа приложения NetView."""

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Режим отладки — только через DEBUG=1 в окружении (make dev).
    # Отладчик Werkzeug даёт интерактивную консоль при исключении,
    # поэтому наружу по умолчанию он не включается.
    app.run(host="0.0.0.0", debug=app.config["DEBUG"], port=5000)
