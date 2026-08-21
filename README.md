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

- `ANALYSIS_2026-08-19.md` — аудит проекта (приоритеты P1–P4). P1 (аутентификация, CSRF, конфигурация через env, фикс bool-фильтров), P2 (дубли, 500-е ошибки, порог тонера) и P3 (параллельный Dashboard, .dockerignore, локальные статики, тесты, ruff) выполнены.

## Dashboard

- Панель «Принтеры» — топ-5 принтеров с тонером ниже порога (порог из `/settings`).
- Панель «Хосты» — топ-5 хостов с критической загрузкой RAM/Диска (>80%) и ссылка «Показать все (N)».
- Все независимые запросы к сервисам выполняются параллельно (ThreadPoolExecutor).

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

## Конфигурация

Все параметры задаются переменными окружения (`.env` уже в `.gitignore`):

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `SECRET_KEY` | Ключ подписи сессий. Если не задан — генерируется случайный, сессии сбрасываются при перезапуске | — |
| `AUTH_USERS` | Учётные записи для входа: `user:pass,user2:pass2`. Пароль можно хранить pbkdf2-хешем werkzeug | — (вход недоступен) |
| `DHCP_POOL` | Диапазон DHCP-пула `начало,конец` — признак «В DHCP-пуле» в NetCerber | — (признак выключен) |
| `PRINTER_API_URL` | URL Printer Monitor API | `http://localhost:8101` |
| `HOST_API_URL` | URL Host Monitor API | `http://localhost:8102` |
| `LOGSPY_API_URL` | URL LogSpy API | `http://localhost:8103` |
| `NETCERBER_API_URL` | URL NetCerber API | `http://localhost:8104` |
| `AD_DOMAIN` | Домен AD для фильтров логов | — |
| `DEBUG` | Режим отладки (`1`/`true`/`0`) | `false` |

Пример:

```bash
cp .env.example .env
# отредактируйте .env: SECRET_KEY, AUTH_USERS, DHCP_POOL, адреса сервисов
```

`.env` исключён из git и Docker-образа; в репозитории лежит только шаблон `.env.example`.

### Запуск в Docker

```bash
cp .env.example .env   # заполнить реальные значения
make build && make up
```

Compose читает переменные из `.env` (`env_file`). Внутри контейнера `localhost` — сам контейнер, поэтому сервисы на хост-машине доступны по `host.docker.internal` (в compose добавлен `extra_hosts: host-gateway`).

## Безопасность

- Все страницы закрыты аутентификацией (flask-login); вход — по учётным записям из `AUTH_USERS`.
- Все изменяющие запросы (POST/PUT) защищены от CSRF (flask-wtf); HTMX-запросы автоматически подписываются токеном через `X-CSRFToken`.

## Git

Репозиторий инициализирован; чувствительные файлы (`.env`, виртуальное окружение, кэш, БД, логи, ключи/сертификаты) исключены через `.gitignore`. Для смены параметров сервисов рекомендуется вынести `app/config.py` на переменные окружения.

## Makefile

| Команда         | Назначение                        |
| --------------- | --------------------------------- |
| `make install`  | Создать venv и установить зависимости |
| `make install-dev` | Установить dev-зависимости (pytest, ruff) |
| `make run`      | Запустить локально                |
| `make dev`      | Режим разработки (Flask debug)    |
| `make test`     | Запустить тесты (pytest)          |
| `make lint`     | Проверить код линтером (ruff)     |
| `make lint-fix` | Автоисправить замечания линтера   |
| `make build`    | docker compose build              |
| `make up`       | docker compose up -d              |
| `make down`     | docker compose down               |
| `make logs`     | docker compose logs -f            |
| `make stop`     | Остановить контейнеры             |
| `make clean`    | Удалить venv, кэш, Docker-образы  |
| `make restart`  | docker compose restart            |
