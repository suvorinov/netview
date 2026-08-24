.PHONY: help install run dev stop clean build up down logs restart test lint lint-fix

help: ## Показать доступные команды
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости в .venv
	python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

install-dev: ## Установить dev-зависимости (pytest, ruff)
	./.venv/bin/pip install -r requirements-dev.txt

test: ## Запустить тесты
	./.venv/bin/python -m pytest tests/ -v

lint: ## Проверить код линтером
	./.venv/bin/ruff check app/ tests/

lint-fix: ## Автоисправить замечания линтера
	./.venv/bin/ruff check --fix app/ tests/

run: ## Запустить приложение
	./.venv/bin/python run.py

dev: ## Запустить в режиме разработки (hot-reload, отладчик)
	DEBUG=1 ./.venv/bin/python run.py

stop: ## Остановить контейнеры
	docker compose down

clean: ## Удалить .venv, кэш, контейнеры
	rm -rf .venv __pycache__ app/__pycache__ app/**/__pycache__
	docker compose down -v --rmi local 2>/dev/null || true

build: ## Собрать Docker образ
	docker compose build

up: ## Запустить через Docker Compose
	docker compose up -d

down: ## Остановить и удалить контейнеры
	docker compose down

logs: ## Показать логи контейнеров
	docker compose logs -f

restart: ## Перезапустить контейнеры
	docker compose restart
