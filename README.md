# NetView

**NetView** — это веб-панель мониторинга IT-инфраструктуры, построенная на Flask. Предоставляет единый интерфейс для контроля состояния принтеров, хостов, пользователей Active Directory, логов Squid и управления стоп-листом.

## Архитектура проекта

```
netview/
├── app/
│   ├── __init__.py          # Фабрика Flask-приложения, фильтры шаблонов (human_size, time_ago)
│   ├── config.py            # Конфигурация (URL сервисов, secret key)
│   ├── api/                 # HTTP-клиенты для внутренних сервисов
│   │   ├── printer_client.py
│   │   ├── host_client.py
│   │   ├── logspy_client.py
│   │   └── netcerber_client.py
│   ├── routes/              # Blueprint страниц
│   │   ├── dashboard.py     # / — сводка со всех сервисов
│   │   ├── printers.py      # /printers/
│   │   ├── hosts.py         # /hosts/   — мониторинг хостов (сортировка, HTMX)
│   │   ├── logs.py          # /logs/    — просмотр логов Squid
│   │   ├── netcerber.py     # /netcerber/ — мониторинг устройств сети
│   │   ├── settings.py      # /settings/— настройки threshold/interval
│   │   ├── users.py         # /users/   — пользователи AD и их активность
│   │   └── stoplist.py      # /stoplist/— управление стоп-листом
│   ├── templates/           # Jinja2-шаблоны (TailwindCSS + HTMX)
│   │   ├── base.html        # Базовый макет с сайтбаром
│   │   ├── partials/        # HTMX-фрагменты (списки, детали, баннеры недоступности)
│   │   └── errors/
│   └── static/css/
├── docker-compose.yml       # Docker Compose с healthcheck
├── Dockerfile               # ASGI-сборка через uvicorn
├── requirements.txt
├── Makefile
└── run.py
```

## Интерфейс

- **Dashboard** — агрегированная статистика по принтерам, хостам, AD и логам
- **Принтеры** — список устройств с уровнем тонера, сортировка через HTMX
- **Хосты** — таблица с CPU/RAM/Disk, статусом ONLINE/OFFLINE; для выключенных хостов — баннер с датой последнего контакта и «устаревшие» (серые) метрики
- **Пользователи** — просмотр AD-пользователей с активностью в Squid (включая заблокированные запросы), авторитетные счётчики запросов и блокировок
- **Логи Squid** — поиск и фильтрация по user/domain/status, сортировка, человекочитаемые размеры (KB/MB/GB)
- **NetCerber** — мониторинг устройств локальной сети, авторизация, журнал сканирований
- **Стоп-лист** — добавление/удаление стоп-слов для блокировки
- **Настройки** — порог тонера, интервал проверки принтеров

При недоступности какого-либо сервиса на страницах отображается баннер «Сервис недоступен» — вместо «тихих нулей».

### Используемые технологии

- Flask 3.x, Jinja2, TailwindCSS 4 (CDN)
- HTMX 2.x — асинхронная подгрузка и сортировка без JS
- FontAwesome 6 (CDN)

### Зависимые сервисы

NetView агрегирует данные из четырёх внутренних микросервисов:

| Сервис             | Клиент                  | URL (по умолчанию)  |
| ------------------ | ----------------------- | ------------------- |
| Printer Monitor    | `PrinterMonitorClient`  | `:8101`             |
| Host Monitor       | `HostMonitorClient`     | `:8102`             |
| LogSpy             | `LogSpyClient`          | `:8103`             |
| NetCerber          | `NetCerberClient`       | `:8104`             |

## Анализ и рефакторинг

- `ANALYSIS.md` — первичный аудит проекта (слабые места, ошибки отображения).
- `ANALYSIS_2026-08-05.md` — повторный аудит после серии исправлений, предложения по рефакторингу (приоритеты P1–P4).

## Быстрый старт

```bash
# Локально
make install   # python3 -m venv .venv && pip install -r requirements.txt
make run       # ./venv/bin/python run.py

# Docker
make build
make up
```

Приложение будет доступно на порту **5000**.

## Git

Репозиторий инициализирован; чувствительные файлы (`.env`, виртуальное окружение, кэш, БД, логи, ключи/сертификаты) исключены через `.gitignore`. Для смены параметров сервисов рекомендуется вынести `app/config.py` на переменные окружения.

## Makefile

| Команда         | Назначение                        |
| --------------- | --------------------------------- |
| `make install`  | Создать venv и установить зависимости |
| `make run`      | Запустить локально                |
| `make dev`      | Режим разработки (Flask debug)    |
| `make build`    | docker compose build              |
| `make up`       | docker compose up -d              |
| `make down`     | docker compose down               |
| `make logs`     | docker compose logs -f            |
| `make stop`     | Остановить контейнеры             |
| `make clean`    | Удалить venv, кэш, Docker-образы  |
| `make restart`  | docker compose restart            |
