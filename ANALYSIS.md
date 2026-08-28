# Анализ проекта NetView

> Дата анализа: 2026-08-28
> Ветка: master (ahead of origin/master)
> Тесты: **193 passed** (6.13s)
> Линтер: **All checks passed** (ruff 0.8.4)
> Строк кода Python: **~7200** (app/ + tests/)

---

## Содержание

1. [Обзор проекта](#1-обзор-проекта)
2. [Архитектура](#2-архитектура)
3. [Структура файлов](#3-структура-файлов)
4. [Сильные стороны](#4-сильные-стороны)
5. [Проблемы и замечания (P1 — критичные)](#5-проблемы-p1--критичные)
6. [Проблемы и замечания (P2 — стоит исправить)](#6-проблемы-p2--стоит-исправить)
7. [Проблемы и замечания (P3 — улучшения)](#7-проблемы-p3--улучшения)
8. [Детальный обзор модулей](#8-детальный-обзор-модулей)
9. [Тестирование](#9-тестирование)
10. [Инфраструктура и деплой](#10-инфраструктура)
11. [Итоговые рекомендации](#11-итоговые-рекомендации)

---

## 1. Обзор проекта

**NetView** — веб-панель мониторинга IT-инфраструктуры на Flask. Агрегирует данные из 4 микросервисов (Printer Monitor, Host Monitor, LogSpy, NetCerber) в единый интерфейс с HTMX-управлением.

| Параметр | Значение |
|---|---|
| Python | 3.12 |
| Framework | Flask 3.1.1 |
| Frontend | HTMX 2.x + TailwindCSS 3.4 (прекомпилированный) |
| Авторизация | flask-login + flask-wtf (CSRF) |
| HTTP-клиент | requests 2.32.3 (с TCP keep-alive) |
| Сервер | uvicorn 0.34.0 (WSGI bridge) |
| Тесты | pytest 8.3.4 (193 теста) |
| Линтер | ruff 0.8.4 (E, F, W, I, UP, B) |
| CI | GitHub Actions (ruff + pytest + CSS freshness) |

---

## 2. Архитектура

### Общая схема

```
                    ┌──────────────────────┐
                    │      NetView UI      │
                    │  Flask + HTMX + Tail │
                    └──────────┬───────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                   │
   ┌────────┴─────┐  ┌───────┴────────┐  ┌──────┴───────┐  ┌──────────────┐
   │ Printer Mon. │  │  Host Monitor  │  │    LogSpy    │  │  NetCerber   │
   │   :8101      │  │    :8102       │  │    :8103     │  │    :8104     │
   └──────────────┘  └────────────────┘  └──────────────┘  └──────────────┘
                                                                 │
                                                        ┌────────┴────────┐
                                                        │  OPNsense FW    │
                                                        │  (блокировка)   │
                                                        └─────────────────┘
```

### Паттерны

- **Application Factory** (`create_app`) — тестирование и конфигурация через инъекцию
- **Blueprint per domain** — каждый модуль (printers, hosts, logs, netcerber, users, settings, stoplist) в отдельном blueprint
- **Centralized Client Factories** — `app/api/factories.py` с кэшированием клиентов на `app.extensions["api_clients"]` (TCP keep-alive, переиспользование `requests.Session`)
- **Resilience Pattern** — каждый route оборачивает вызовы сервисов в `try/except RequestException` → показывает баннер «Сервис недоступен», никогда не падает. Data-shape ошибки намеренно не ловятся (это «наши баги»)
- **Concurrency** — Dashboard, карточка пользователя и health-check используют `ThreadPoolExecutor` для параллельных запросов
- **In-process cache** — TTL-кэш для счётчиков чипов NetCerber (30 сек)

---

## 3. Структура файлов

```
netview/
├── app/
│   ├── __init__.py          (156 строк)  — фабрика, фильтры шаблонов, middleware
│   ├── config.py            (140 строк)  — конфигурация из env, hand-rolled .env loader
│   ├── auth.py              (197 строк)  — аутентификация, brute-force защита
│   ├── utils.py             (376 строк)  — чистые утилиты (MAC, IP, human_size, sort)
│   ├── asgi.py              (7 строк)    — WSGI→ASGI мост для uvicorn
│   ├── api/
│   │   ├── base.py          (86 строк)   — BaseApiClient с requests.Session
│   │   ├── factories.py     (73 строк)   — фабрики клиентов с кэшем
│   │   ├── printer_client.py (88 строк)  — Printer Monitor API
│   │   ├── host_client.py   (60 строк)   — Host Monitor API
│   │   ├── logspy_client.py (164 строк)  — LogSpy API (AD, стоп-лист, логи)
│   │   ├── netcerber_client.py (127 строк) — NetCerber API
│   │   └── opnsense.py      (274 строк)  — OPNsense firewall API
│   └── routes/
│       ├── dashboard.py     (232 строк)  — агрегированный Dashboard
│       ├── printers.py      (116 строк)  — список принтеров
│       ├── hosts.py         (133 строк)  — мониторинг хостов
│       ├── logs.py          (137 строк)  — просмотр логов Squid
│       ├── netcerber.py     (1233 строк) — мониторинг устройств сети ⚠️
│       ├── settings.py      (219 строк)  — настройки.threshold/interval
│       ├── users.py         (420 строк)  — пользователи AD
│       └── stoplist.py      (84 строк)   — управление стоп-листом
├── tests/
│   ├── conftest.py          (54 строки)
│   ├── test_auth.py         (209 строк)
│   ├── test_clients.py      (151 строк)
│   ├── test_config.py       (45 строк)
│   ├── test_opnsense.py     (248 строк)
│   ├── test_routes.py       (1834 строк) ⚠️
│   └── test_utils.py        (359 строк)
├── mikrotik_api_minimal.py  (78 строк)   — утилита MikroTik API (не интегрирована)
├── run.py                   (11 строк)
├── Dockerfile               (14 строк)
├── docker-compose.yml       (19 строк)
├── Makefile                 (55 строк)
├── requirements.txt         (5 зависимостей)
├── requirements-dev.txt     (2 зависимости)
└── ruff.toml                (9 строк)
```

---

## 4. Сильные стороны

### Архитектурные решения

1. **Последовательный resilience-паттерн** — каждый route одинаково обрабатывает недоступность сервисов; баннер вместо падения. Это профессиональный уровень проектирования для панелей мониторинга.

2. **TCP keep-alive через `requests.Session`** — Dashboard делает ~10 запросов к сервисам за одну загрузку. Переиспользование соединения экономит handshake для каждого.

3. **Hand-rolled `.env` loader без зависимостей** — осознанный выбор (KISS). Нет `python-dotenv` — меньше точек отказа. Приоритет `os.environ` > `.env` файла.

4. **Фабрики с кэшированием** — 17 дублированных `_get_*_client()` хелперов заменены на единый `_cached_client()`. Клиенты живут на экземпляре приложения, что гарантирует keep-alive.

5. **Намеренное разделение ошибок** — data-shape ошибки намеренно не ловятся (это баги разработчика, нужно чинить), а сетевые — показывают баннер. Это документировано и последовательно.

### Качество кода

6. **Обширная документация в коде** — почти каждое неочевидное решение объяснено комментарием (зачем `session.clear()` при логине, почему MAC без двоеточий в маркере OPNsense, почему `Content-Length: 0` для apply).

7. **Последовательные именования** — `htmx_*` для HTMX-фрагментов, `_` для приватных функций, консистентная структура модулей.

8. **Безопасность** — CSRF на всех mutation-запросах, защита от brute-force с sliding window, defense от session fixation (`session.clear()`), open-redirect guard в `next` параметре, санитизация ошибок.

9. **CI/CD** — GitHub Actions с ruff + pytest + проверка свежести CSS (templates ↔ compiled CSS).

---

## 5. Проблемы P1 — критичные

### P1-1. `netcerber.py` — 1233 строки, монолитный модуль

**Проблема**: Крупнейший модуль проекта содержит маршруты устройств, маршруты сканирования, логику OPNsense, кэширование, фильтры, обогащение данных — всё в одном файле.

**Влияние**: Сложность навигации, риски merge-конфликтов, трудность тестирования изолированно.

**Рекомендация**: Разделить на подмодули:
```
app/routes/netcerber/
├── __init__.py       # netcerber_bp, общие константы
├── devices.py        # маршруты устройств (authorize, delete, flags)
├── scans.py          # журнал сканирований, baseline
├── opnsense.py       # хелперы OPNsense (вынести из routes)
└── utils.py          # _resolve_ad, _scheduler_status, _device_flags
```

### P1-2. `test_routes.py` — 1834 строки, один файл

**Проблема**: Единый файл содержит 193 теста со всеми модулями, гигантским autouse fixture на 100+ строк.

**Влияние**: Сложность поддержки, хрупкость fixture (monkeypatch всего подряд), риск каскадных сбоев.

**Рекомендация**: Разделить по доменам:
```
tests/
├── test_dashboard.py
├── test_printers.py
├── test_hosts.py
├── test_netcerber_devices.py
├── test_netcerber_scans.py
├── test_users.py
├── test_logs.py
├── test_settings.py
└── test_stoplist.py
```

### P1-3. Утечка внутренних данных через ошибки OPNsense

**Проблема**: В `netcerber.py` (строки ~601, ~650) `detail = str(e)` рендерит сообщение `OPNsenseError` в UI. Это может содержать URL шлюза или внутренние детали.

**Пример**: Блокировка показывает "обновление алиаса не прошло (ответ: ...)", разблокировка — "Connection refused to http://192.168.0.1/...".

**Рекомендация**: Санитизировать ошибки OPNsense так же, как это сделано для LogSpy/NetCerber:
```python
except OPNsenseError:
    detail = "Шлюз недоступен"
```

### P1-4. URL path injection в API-клиентах

**Проблема**: Пользовательский ввод подставляется в URL без экранирования:
- `printer_client.get_printer(ip)` → `GET /api/printers/{ip}`
- `host_client.get_host(hostname)` → `GET /api/v1/hosts/{hostname}`
- `logspy_client.ad_resolve_ip(ip)` → `GET /api/v1/ad/resolve/{ip}`
- `logspy_client.remove_stoplist_word(word)` → `DELETE /api/v1/stoplist/{word}`

Если `ip` или `word` содержит `/` или спецсимволы, URL ломается.

**Рекомендация**: Использовать `urllib.parse.quote(str(value), safe="")`:
```python
from urllib.parse import quote
def get_printer(self, ip):
    return self._get(f"/api/printers/{quote(str(ip), safe='')}")
```

---

## 6. Проблемы P2 — стоит исправить

### P2-1. Приватная функция `_opnsense_problems` импортируется кросс-модульно

**Проблема**: `app/__init__.py:19` импортирует `from app.routes.netcerber import _opnsense_problems` — приватная функция используется за пределами модуля.

**Рекомендация**: Либо сделать публичной (`opnsense_problems`), либо вынести в общий модуль (например, `app/config.py` или `app/routes/netcerber/opnsense.py`).

### P2-2. Brute-force защита работает только в рамках одного процесса

**Проблема**: Словарь `_login_failures` хранится в памяти процесса. При запуске нескольких uvicorn-воркеров каждый воркер имеет свой счётчик.

**Статус**: Задокументировано как осознанный tradeoff для внутренней панели. При масштабировании на несколько воркеров нужно перейти на Redis/file-based.

### P2-3. `_parse_users()` вызывается при каждом запросе

**Проблема**: `load_user()` (вызывается при каждом запросе через `@login_manager.user_loader`) парсит строку `AUTH_USERS` каждый раз.

**Рекомендация**: Кэшировать результат парсинга (TTL или lazy cache):
```python
_users_cache: dict[str, str] | None = None

def _parse_users():
    global _users_cache
    if _users_cache is None:
        _users_cache = {...}
    return _users_cache
```

### P2-4. `Config` читается при импорте модуля, а не при создании приложения

**Проблема**: `Config` определяется на уровне модуля (`config.py`), все переменные читаются в момент `import`. Это значит:
- `SECRET_KEY` генерируется один раз при первом import
- Тесты должны переопределять через `app.config.update()`
- Невозможно создать два приложения с разной конфигурацией

**Рекомендация**: Перенести чтение env в `__init__` класса или `from_env()` classmethod.

### P2-5. Settings: 3 последовательных запроса к Printer Monitor

**Проблема**: `settings_page()` делает 3 последовательных GET-запроса (threshold, interval, status) — можно запустить параллельно.

**Рекомендация**: Использовать тот же `_run_parallel` паттерн, что уже есть в `dashboard.py` и `users.py`.

### P2-6. `mikrotik_api_minimal.py` — мёртвая утилита

**Проблема**: 78 строк standalone-скрипта, не интегрирован с приложением, не импортируется, не тестируется.

**Рекомендация**: Либо удалить, либо перенести в `tools/` с пометкой в README.

---

## 7. Проблемы P3 — улучшения

### P3-1. Дублирование `_run_parallel` хелперов

**Проблема**: `_run_task()` в `dashboard.py` и `_run_parallel()` в `users.py` — похожая логика параллельного выполнения с обработкой ошибок. Можно вынести в общий модуль.

### P3-2. Тип `unavailable_services` — list vs set

**Проблема**: В `hosts.py` это `list`, в `dashboard.py` и `users.py` — `set`. Небольшая несогласованность.

### P3-3. `human_size()` возвращает `str(b)` для отрицательных значений

**Проблема**: `human_size(-5)` вернёт `"-5"` вместо форматированной строки. Задокументировано, но можно вернуть `"—"` как для `None`.

### P3-4. `_is_number` использует `float()` для проверки

**Проблема**: `"inf"`, `"nan"` пройдут проверку. Для целочисленной сортировки можно использовать `int()` с except.

### P3-5. `_COUNTS_CACHE_TTL` — простой dict без автоматической инвалидации

**Проблема**: Кэш хранится в `app.extensions` с ручной проверкой `time.time() - ts > TTL`. При garbage collection нет автоматической очистки.

### P3-6. Ruff: B904 игнорируется

**Проблема**: `raise X from e` chaining не проверяется линтером. В коде он используется во многих местах, но не везде.

### P3-7. Нет type hints на уровне пакетов

**Проблема**: `__init__.py` в `api/` и `routes/` пустые, нет `__all__`. Экспорт не определён.

### P3-8. README ссылается на удалённый `ANALYSIS_2026-08-24.md`

**Проблема**: Файл удалён из рабочей директории, но README (строка 70) всё ещё ссылается на него.

---

## 8. Детальный обзор модулей

### `app/__init__.py` (156 строк) — Фабрика приложения

- Application factory `create_app()` — корректно настроен
- Фильтры шаблонов: `datetime`, `human_size`, `time_ago`
- `time_ago` — корректно обрабатывает tz-aware и naive datetime
- Error handler 500 с fallback на plain text (если шаблон сломан)
- `before_request` — принудительная аутентификация
- `after_request` — логирование 404

### `app/auth.py` (197 строк) — Аутентификация

- Sliding-window brute-force защита (5 попыток / 60 сек)
- `threading.Lock` для потокобезопасности
- Session fixation defense: `session.clear()` перед `login_user`
- Open-redirect guard: `next` параметр проверяется на `/` начало
- POST-only logout (защита от CSRF logout через `<img>`)

### `app/config.py` (140 строк) — Конфигурация

- Hand-rolled `.env` loader (без `python-dotenv`)
- Приоритет: `os.environ` > `.env` файл
- Случайный `SECRET_KEY` с предупреждением
- Session cookie: HttpOnly, SameSite=Lax, опциональный Secure

### `app/utils.py` (376 строк) — Утилиты

Чистые, хорошо протестированные функции:
- `human_size()` — байты в человекочитаемый формат
- `normalize_mac()` / `parse_mac_list()` / `is_protected_mac()` — MAC-адреса
- `group_devices_by_ip()` — группировка дублей с историей
- `sort_items()` — умная сортировка (числа как float, строки case-insensitive)
- `is_router_vendor()` / `is_vendor_mismatch()` — эвристики для роутеров
- `time_ago` —.relative time на русском

### `app/api/base.py` (86 строк) — Базовый HTTP-клиент

- `requests.Session` для keep-alive
- Обработка пустого тела → `None`
- `raise_for_status()` для не-2xx ответов

### `app/api/factories.py` (73 строк) — Фабрики клиентов

- Кэширование на `app.extensions["api_clients"]`
- Единый `_cached_client()` хелпер
- `get_logspy_client()` — special-cased (нужен `LOGSPY_TIMEOUT`)

### `app/api/opnsense.py` (475 строк) — OPNsense клиент

- Идиоматичный API: `block_mac()`, `unblock_mac()`, `blocked_macs()`, `is_blocked()` — блокировка по **MAC** общим алиасом `netview_block_mac` (type=mac) + одно правило `source=алиас`, поднятое в начало списка через целое `sequence`/`setRule` (на TING нет `moveRuleBefore`)
- Инфраструктура доздаётся идемпотентно: `ensure_block_entities()` — алиас + правило + `apply`; блок/разблок — `setItem/<uuid>` (элементы через перевод строк, в теле обязателен `alias[name]`; на чтение `searchItem` — элементы через запятую) + `reconfigure`
- Миграция остатков старой схемы (`netview_mac_*` алиасы и правила `netview-block-<MACHEX>`) в общий алиас
- `_apply()` — apply конфигурации после структурных изменений
- `Content-Length: 0` — документированное требование lighttpd
- Чтение статуса: `searchRule` + `getRule` (правило активно) + `searchItem` (содержимое алиаса) — константное число запросов

### `app/routes/dashboard.py` (232 строк) — Дашборд

- 10 параллельных запросов через `ThreadPoolExecutor`
- Пост-обработка: метрики принтеров, хостов, AD, логов, стоп-листа, NetCerber
- Топ-5 критических принтеров/хостов

### `app/routes/netcerber.py` (1233 строк) — Устройства сети

- Самый большой модуль (⚠️ — кандидат на разделение)
- Чипы-фильтры: роутеры, новые, неизвестные, DHCP, расхождение, дубли
- OPNsense блокировка/разблокировка
- Журнал сканирований с baseline
- Планировщик сканов
- TTL-кэш для счётчиков чипов (30 сек)

### `app/routes/users.py` (420 строк) — Пользователи AD

- Параллельные запросы AD + LogSpy
- UPN extraction из `distinguishedName`
- Экспорт отчёта по заблокированным доменам
- Fallback-статистика из последних 500 записей

---

## 9. Тестирование

### Покрытие

| Модуль | Строк | Тестов | Статус |
|---|---|---|---|
| `test_utils.py` | 359 | ~40 | ✅ Unit-тесты чистых функций |
| `test_config.py` | 45 | 6 | ✅ `.env` парсер |
| `test_auth.py` | 209 | ~20 | ✅ Аутентификация, CSRF, lockout |
| `test_clients.py` | 151 | 13 | ✅ HTTP-клиенты без сети |
| `test_opnsense.py` | 248 | ~15 | ✅ OPNsense протокол |
| `test_routes.py` | 1834 | ~100 | ✅ Все страницы + HTMX |
| **Итого** | **2846** | **193** | **All passed** |

### Сильные стороны тестов

1. **Deterministic окружение** — `conftest.py` устанавливает фиксированные env перед import приложения
2. **Fake HTTP-клиенты** — `_FakeSession` в `test_opnsense.py`, `_response()` в `test_clients.py` — тесты без сети
3. **Parametrized render tests** — `PAGES` и `HTMX_FRAGMENTS` проверяют рендер всех страниц
4. **Edge cases** — timezone bugs, lockout, session fixation, open redirect, error sanitization
5. **`_iso()` хелпер** — генерирует даты относительно «сейчас», тесты «не стареют»

### Замечания к тестам

1. **`test_routes.py` слишком большой** — 1834 строки, один autouse fixture monkeypatch'ит все клиенты. Стоит разделить.
2. **Большой autouse fixture** — хрупкий: переопределения тестов накладываются друг на друга.
3. **Нет интеграционных тестов** — все тесты unit с monkeypatch. Нет тестов с реальным Flask test client и реальными шаблонами (rendering tests есть, но все данные — моковые).
4. **Нет тестов для `mikrotik_api_minimal.py`** — утилита не покрыта тестами.

---

## 10. Инфраструктура

### Docker

- **Dockerfile**: `python:3.12-slim`, копирует `app/`, `run.py`, `requirements.txt`
- **docker-compose.yml**: `host.docker.internal:host-gateway` для доступа к сервисам на хосте
- **Healthcheck**: GET `/` → 302→200 (логин) — проверяет что процесс жив

### CI (GitHub Actions)

- **ruff check** — линтинг app/ и tests/
- **pytest** — все тесты
- **CSS freshness** — пересобирает CSS и сравнивает с закоммиченным

### Makefile

| Команда | Назначение |
|---|---|
| `make install` | venv + зависимости |
| `make test` | pytest |
| `make lint` | ruff check |
| `make css` | Tailwind CLI → app.css |
| `make dev` | DEBUG=1 run.py |
| `make build/up/down` | Docker |

---

## 11. Итоговые рекомендации

### Приоритет P1 (критично)

| # | Проблема | Сложность | Время |
|---|---|---|---|
| P1-1 | Разделить `netcerber.py` (1233 строки) | Высокая | 2-3 часа |
| P1-2 | Разделить `test_routes.py` (1834 строки) | Средняя | 1-2 часа |
| P1-3 | Санитизация ошибок OPNsense в UI | Низкая | 15 мин |
| P1-4 | `urllib.parse.quote` в API-клиентах | Низкая | 30 мин |

### Приоритет P2 (стоит исправить)

| # | Проблема | Сложность | Время |
|---|---|---|---|
| P2-1 | `_opnsense_problems` → публичная или вынести | Низкая | 15 мин |
| P2-2 | Brute-force → Redis (если масштабирование) | Высокая | 2-3 часа |
| P2-3 | Кэш `_parse_users()` | Низкая | 10 мин |
| P2-4 | Config → read at creation time | Средняя | 1 час |
| P2-5 | Settings: параллельные запросы | Низкая | 20 мин |
| P2-6 | Удалить/перенести `mikrotik_api_minimal.py` | Низкая | 5 мин |

### Приоритет P3 (улучшения)

| # | Проблема | Сложность | Время |
|---|---|---|---|
| P3-1 | Вынести `_run_parallel` в общий модуль | Низкая | 20 мин |
| P3-2 | Согласовать тип `unavailable_services` | Низкая | 5 мин |
| P3-3 | `human_size()` для отрицательных | Низкая | 5 мин |
| P3-4 | `_is_number` → `int()` вместо `float()` | Низкая | 5 мин |
| P3-5 | TTL-кэш → `cachetools` или auto-cleanup | Средняя | 30 мин |
| P3-6 | Включить B904 в ruff | Низкая | 15 мин |
| P3-7 | Добавить `__all__` в `__init__.py` | Низкая | 10 мин |
| P3-8 | Обновить README (удалить ссылку на ANALYSIS) | Низкая | 5 мин |

### Общая оценка проекта

Проект демонстрирует **высокий уровень архитектурной культуры**:

- Последовательные паттерны (resilience, factories, HTMX fragments)
- Обширная документация решений в коде
- Безопасность «из коробки» (CSRF, brute-force, fixation, redirect guard)
- 193 теста с deterministic окружением
- CI с linter + tests + CSS freshness check
- Чистые утилиты с хорошим покрытием

Основные направления для улучшения — разделение крупных модулей (`netcerber.py`, `test_routes.py`) и мелкие проблемы безопасности (URL injection, error leakage).
