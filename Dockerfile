FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Точечная копия: в образ не попадают README, анализ, git и т.п.
COPY app/ ./app/
COPY run.py .

EXPOSE 5000

CMD ["python", "-m", "uvicorn", "app.asgi:application", "--host", "0.0.0.0", "--port", "5000"]