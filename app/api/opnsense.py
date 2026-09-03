"""Клиент REST API шлюза OPNsense (TING) для блокировки устройств.

Шлюз — это OPNsense (белый лейбл «TING») с модулем os-firewall.
Блокировка работает по **MAC** и переживает смену IP: на шлюзе живут
ОДИН алиас-список `netview_block_mac` (type=mac) и ОДНО правило с
источником-этим алиасом, стоящее первым в списке правил LAN. Это ровно
та схема, которую оператор настраивает руками через веб-интерфейс
шлюза (псевдоним → правило → в начало списка), только в общем виде.

Блокировка/разблокировка устройства = добавить/убрать MAC в содержимое
общего алиаса и перегрузить alias-таблицы (reconfigure). Правило при
этом не трогается — перенумерация (sequence) нужна только один раз,
при создании правила.

ВАЖНО (проверено на живом TING): legacy `/api/firewall/alias/searchAlias`
и `/api/firewall/filter/moveRuleBefore` там отсутствуют. Рабочие
endpoint'ы: алиасы — `searchItem`, `getAliasUUID/<name>`, `addItem`,
`setItem/<uuid>`, `delItem/<uuid>`, `reconfigure`; правила — `searchRule`,
`getRule`, `addRule`, `setRule`, `delRule`, `apply`. Особенности форка
(эмпирически):

- `setItem` падает с "Undefined index: name", если не передать
  `alias[name]` в теле запроса;
- содержимое алиаса при записи разделяется переводами строк, при чтении
  (searchItem) элементы отдаются через запятую;
- `sequence` правила — только натуральное число (0 и дроби отклоняются
  валидацией).

Протокол: HTTP Basic auth с парой ключ:секрет (API-ключи OPNsense).
Все методы идемпотентны; сетевые/API-ошибки поднимаются как
OPNsenseError.

Ограничение скорости (шайпер): конфигурация читается через
`/api/trafficshaper/settings/get` (каналы pipes + правила rules),
запись — точечными мутациями контроллера trafficshaper/settings
(`addrule`/`setrule`/`delrule`) с телом JSON `{"rule": {...}}` +
`service/reconfigure` для применения. На TING form-передача addrule
падает с "Undefined index: uuid", а пустые src_port/dst_port/
source_not/destination_not валят валидацию — поля просто не
передаются. Description правила не должен содержать ':' (form-адаптер).
"""

import logging
import time
import uuid as uuid_lib

import requests

from app.api.base import BaseApiClient
from app.utils import normalize_mac

logger = logging.getLogger(__name__)

# Описание нашего единственного правила на шлюзе и маркер алиаса-списка.
# В description OPNsense form-адаптер ломается на символе ':', поэтому в
# маркерах только дефисы (двоеточия из MAC убираются).
RULE_COMMENT = "netview-block"
ALIAS_NAME = "netview_block_mac"
ALIAS_DESCRIPTION = "netview-block-list"

# ── Шейпер (Traffic Shaper, ограничение скорости каналом) ───────
# Правила шейпера NetView: по одному на устройство, description —
# "netview-shape-<MACHEX>" (без ':'). Шейпер матчит по IP (destination),
# поэтому в отличие от блокировки ограничение живёт до смены IP.
SHAPE_RULE_PREFIX = "netview-shape-"
# sequence ставим выше правил оператора (у TING они 1..10), чтобы не
# перекрывать их сетевые правила (yet дожимать канал для пользователя).
SHAPE_SEQUENCE = 90

# Префикс имени LEGACY-алиасов (от старой схемы «алиас+правило на каждый
# MAC»: netview_mac_<MACHEX> и правила netview-block-<MACHEX>). Такие
# остатки переносятся в общий алиас и удаляются при первом использовании.
LEGACY_ALIAS_PREFIX = "netview_mac_"

# Повторы при транзиентных сетевых сбоях (нет соединения/таймаут).
# Шлюз-блокировка — критичная операция: одну повторную попытку с
# экспоненциальной паузой надёжность оправдывает. Все операции шлюза
# идемпотентны по устройству (setItem/reconfigure/apply), поэтому
# повтор на сетевой ошибке безопасен. HTTP-ошибки (4xx/5xx) и ошибки
# формы ответа НЕ повторяются — это не «шум сети», а настоящий ответ
# API, и слепой повтор здесь не поможет.
OPNSENSE_RETRIES = 1
OPNSENSE_RETRY_BASE_DELAY = 0.3


def _retry_transient(fn):
    """Выполнить сетевой вызов с одним повтором на транзиентную ошибку.

    Повторяется только requests.ConnectionError/requests.Timeout —
    «сеть дёрнулась». Ошибки формы ответа/OPNsenseError пробрасываются
    сразу: повтор бессмыслен.

    Args:
        fn: Callable, выполняющий один HTTP-запрос.

    Returns:
        Результат fn().
    """
    attempt = 0
    while True:
        try:
            return fn()
        except requests.RequestException as e:
            # Network-уровень: стоит повторить. HTTP-статусы приходят
            # изнутри raise_for_status как HTTPError — они НЕ транзиентны.
            if attempt >= OPNSENSE_RETRIES or not isinstance(
                e, requests.ConnectionError | requests.Timeout
            ):
                raise
            attempt += 1
            time.sleep(OPNSENSE_RETRY_BASE_DELAY * attempt)


class OPNsenseError(Exception):
    """Ошибка работы со шлюзом OPNsense (сеть, auth, API, CRUD)."""


class OPNsenseClient(BaseApiClient):
    """Клиент REST API брандмауэра шлюза OPNsense.

    Блокировка — общий алиас-список + одно правило первым:

    - block_mac(mac): добавляет MAC в алиас `netview_block_mac` и
      перегружает alias-таблицы; при необходимости создаёт алиас/правило.
    - unblock_mac(mac): убирает MAC из алиаса списка.
    - is_blocked(mac) / blocked_macs(): состояние по содержимому алиаса
      и наличию активного правила.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        timeout: float = 10.0,
    ) -> None:
        """Инициализация клиента.

        Args:
            base_url: URL веб-интерфейса шлюза (например,
                "http://192.168.0.1").
            api_key: Короткий API-ключ OPNsense.
            api_secret: Длинный секрет API-ключа.
            timeout: Таймаут запросов, секунды.
        """
        super().__init__(base_url, timeout=int(timeout))
        self._auth = (api_key, api_secret)

    # ── низкоуровневые помощники ────────────────────────────────
    def _get(self, path: str):
        try:
            resp = _retry_transient(
                lambda: self._session.get(
                    f"{self.base_url}{path}",
                    timeout=self.timeout,
                    auth=self._auth,
                )
            )
            resp.raise_for_status()
            if not resp.content:
                return None
            return resp.json()
        except requests.RequestException as e:
            raise OPNsenseError(f"нет соединения с шлюзом ({e})") from e

    def _post(self, path: str, data: dict | None = None):
        """POST с form-urlencoded (API OPNsense принимает именно это)."""
        try:
            kwargs = {"data": data, "auth": self._auth}
            resp = _retry_transient(
                lambda: self._session.post(
                    f"{self.base_url}{path}",
                    timeout=self.timeout,
                    **kwargs,
                )
            )
            resp.raise_for_status()
            if not resp.content:
                return None
            return resp.json()
        except requests.RequestException as e:
            raise OPNsenseError(f"нет соединения с шлюзом ({e})") from e

    def _post_json(self, path: str, obj: dict):
        """POST с JSON-телом.

        Тело вида {"rule": {...}} нужно для мутаций шейпера (addrule/
        setrule): на TING form-передача для addrule падает с
        "Undefined index: uuid" (проверено на живом шлюзе).
        """
        try:
            resp = _retry_transient(
                lambda: self._session.post(
                    f"{self.base_url}{path}",
                    json=obj,
                    auth=self._auth,
                    timeout=self.timeout,
                )
            )
            resp.raise_for_status()
            if not resp.content:
                return None
            return resp.json()
        except requests.RequestException as e:
            raise OPNsenseError(f"нет соединения с шлюзом ({e})") from e

    def _post_no_body(self, path: str):
        """POST без тела: lighttpd шлюза требует Content-Length: 0."""
        try:
            resp = _retry_transient(
                lambda: self._session.post(
                    f"{self.base_url}{path}",
                    auth=self._auth,
                    timeout=self.timeout,
                    headers={"Content-Length": "0"},
                )
            )
            resp.raise_for_status()
            if not resp.content:
                return None
            return resp.json()
        except requests.RequestException as e:
            raise OPNsenseError(f"нет соединения с шлюзом ({e})") from e

    def _apply(self) -> None:
        """Применить изменения конфига брандмауэра (pf)."""
        payload = self._post_no_body("/api/firewall/filter/apply")
        if str((payload or {}).get("status", "")).strip() != "OK":
            raise OPNsenseError(
                f"применение конфига вернуло неожиданный ответ: {payload}"
            )

    # ── работа с алиасами ───────────────────────────────────────
    def _get_alias_uuid(self, name: str) -> str | None:
        """UUID алиаса по имени (getAliasUUID); None, если его нет.

        Имя алиаса нам известно точно (`netview_block_mac`), поэтому
        вместо поискового searchItem используется прямой lookup по имени:
        заодно обходится отсутствие legacy `searchAlias` на TING.
        """
        try:
            payload = self._get(f"/api/firewall/alias/getAliasUUID/{name}")
        except OPNsenseError:
            raise
        if isinstance(payload, dict):
            return payload.get("uuid")
        return None

    def _alias_rows(self) -> list[dict]:
        """Строки searchItem — все алиасы брандмауэра."""
        try:
            payload = self._get("/api/firewall/alias/searchItem")
        except OPNsenseError:
            raise
        return (payload or {}).get("rows") or []

    def _alias_content(self, name: str) -> list[str]:
        """Список элементов алиаса (content), например MAC-адреса.

        searchItem отдаёт content одним текстом: элементы через запятую.
        Пустого алиаса или отсутствующих записей → пустой список.
        """
        for row in self._alias_rows():
            if row.get("name") == name:
                raw = row.get("content") or ""
                return [x.strip() for x in raw.split(",") if x.strip()]
        return []

    def _set_alias_content(self, uuid: str, macs: list[str]) -> None:
        """Переписать содержимое алиаса (setItem), элементы — с новой строки.

        На TING разделитель при записи — перевод строки, а `setItem`
        требует `alias[name]` в теле (иначе "Undefined index: name").
        """
        words = {
            "alias[name]": ALIAS_NAME,
            "alias[content]": "\n".join(macs),
        }
        payload = self._post(f"/api/firewall/alias/setItem/{uuid}", words)
        if not isinstance(payload, dict) or payload.get("result") != "saved":
            raise OPNsenseError(
                f"обновление алиаса не прошло (ответ: {payload})"
            )

    def _alias_reconfigure(self) -> None:
        """Перегрузить alias-таблицы (после изменения содержимого алиасов)."""
        payload = self._post_no_body("/api/firewall/alias/reconfigure")
        status = str((payload or {}).get("status", "")).strip().lower()
        if status != "ok":
            raise OPNsenseError(
                f"перегрузка алиасов вернула неожиданный ответ: {payload}"
            )

    # ── работа с правилами ──────────────────────────────────────
    def _rule_rows(self) -> list[dict]:
        """Строки searchRule — все правила в порядке применения."""
        try:
            payload = self._get("/api/firewall/filter/searchRule")
        except OPNsenseError:
            raise
        return (payload or {}).get("rows") or []

    def _set_rule_sequence(self, uuid: str, sequence: str) -> None:
        """Переписать sequence правила (setRule) — так TING меняет позицию."""
        payload = self._post(
            f"/api/firewall/filter/setRule/{uuid}",
            {"rule[sequence]": sequence},
        )
        if not isinstance(payload, dict) or payload.get("result") != "saved":
            raise OPNsenseError(
                f"не удалось изменить позицию правила {uuid} (ответ: {payload})"
            )

    def _ensure_rule_first(self, uuid: str) -> bool:
        """Поднять правило uuid наверх списка; True, если что-то менялось.

        TING не поддерживает moveRuleBefore. Порядок задаётся целым
        sequence (1, 2, ...): новые правила получают sequence=1 и при
        совпадении встают ПОСЛЕ существующих с тем же sequence. Чтобы
        наше правило гарантированно стояло первым, все остальные
        сдвигаются на +1 (в обратном порядке — без коллизий), а нашему
        ставится 1.
        """
        rows = self._rule_rows()
        idx = next(
            (i for i, r in enumerate(rows) if r.get("uuid") == uuid), None
        )
        if idx is None:
            raise OPNsenseError(f"правило {uuid} не найдено в списке правил")
        if idx == 0:
            return False  # уже первое
        others = [r for r in rows if r.get("uuid") != uuid]
        # Обратный порядок (по sequence и по месту в списке) — сдвигаем
        # большие значения первыми, чтобы цель (+1) была свободна.
        order = sorted(
            enumerate(others),
            key=lambda item: (
                float(item[1].get("sequence") or 1),
                item[0],
            ),
            reverse=True,
        )
        for _, row in order:
            cur = float(row.get("sequence") or 1)
            self._set_rule_sequence(row["uuid"], str(int(cur) + 1))
        self._set_rule_sequence(uuid, "1")
        return True

    def _find_block_rule_unid(self) -> str | None:
        """UUID нашего правила (description == RULE_COMMENT), или None."""
        for row in self._rule_rows():
            if row.get("description", "").strip() == RULE_COMMENT:
                return row["uuid"]
        return None

    def _add_block_rule(self) -> str:
        """Создать правило блокировки по общему алиасу."""
        words = {
            "rule[enabled]": "1",
            "rule[action]": "block",
            "rule[interface]": "lan",
            "rule[direction]": "in",
            "rule[ipprotocol]": "inet",
            "rule[protocol]": "any",
            "rule[source_net]": ALIAS_NAME,
            "rule[quick]": "1",
            "rule[description]": RULE_COMMENT,
        }
        payload = self._post("/api/firewall/filter/addRule", words)
        rule_uuid = payload.get("uuid") if isinstance(payload, dict) else None
        result = payload.get("result") if isinstance(payload, dict) else None
        if result != "saved" or not rule_uuid:
            raise OPNsenseError(
                f"добавление правила не прошло (ответ: {payload})"
            )
        return rule_uuid

    def _get_rule(self, unid: str) -> dict | None:
        try:
            payload = self._get(f"/api/firewall/filter/getRule/{unid}")
        except OPNsenseError:
            return None
        return payload.get("rule") if isinstance(payload, dict) else None

    # ── создание общей инфраструктуры и миграция ────────────────
    def _migrate_legacy(self) -> bool:
        """Перенести старые «алиас+правило на каждый MAC» в общий алиас.

        Старая схема: алиасы `netview_mac_<MACHEX>` и правила с описанием
        `netview-block-<MACHEX>`. Их MAC складываются в `netview_block_mac`,
        старые правила и алиасы удаляются. Возвращает True, если шлюз
        менялся.
        """
        alias_rows = self._alias_rows()
        legacy_aliases = [
            r for r in alias_rows
            if r.get("name", "").startswith(LEGACY_ALIAS_PREFIX)
        ]
        legacy_rules = [
            r["uuid"] for r in self._rule_rows()
            if r.get("description", "").startswith(RULE_COMMENT + "-")
        ]
        if not legacy_aliases and not legacy_rules:
            return False

        changed = False
        # 1) собрать MAC из старых алиасов (кодируются в имени)
        macs = self._alias_content(ALIAS_NAME)
        for row in legacy_aliases:
            hexpart = row["name"][len(LEGACY_ALIAS_PREFIX):]
            if len(hexpart) == 12 and all(
                c in "0123456789abcdefABCDEF" for c in hexpart
            ):
                macs.append(
                    ":".join(hexpart[i : i + 2] for i in range(0, 12, 2)).upper()
                )
        uuid = self._get_alias_uuid(ALIAS_NAME)
        if uuid:
            self._set_alias_content(uuid, macs)
            changed = True
        # 2) удалить старые правила (сначала — чтобы освободить алиасы)
        for uid in legacy_rules:
            try:
                self._post_no_body(f"/api/firewall/filter/delRule/{uid}")
                changed = True
            except OPNsenseError as e:
                logger.warning("OPNsense: legacy-правило %s не удалено: %s", uid, e)
        # 3) удалить старые алиасы (уже ничем не заняты)
        for row in legacy_aliases:
            try:
                self._post_no_body(f"/api/firewall/alias/delItem/{row['uuid']}")
                changed = True
            except OPNsenseError as e:
                logger.warning("OPNsense: legacy-алиас %s не удалён: %s", row["name"], e)
        if changed:
            logger.info(
                "OPNsense: миграция legacy-блокировок (%d правило, %d алиаса)",
                len(legacy_rules),
                len(legacy_aliases),
            )
        return changed

    def ensure_block_entities(self) -> tuple[str, str]:
        """Гарантировать наличие алиаса-списка и правила; вернуть (alias, rule).

        Создаёт алиас `netview_block_mac`, мигрирует остатки старой
        схемы, создаёт правило (если его нет) и ставит его первым.
        Структурные изменения применяются через apply. Идемпотентно.
        """
        changed = False
        alias_uuid = self._get_alias_uuid(ALIAS_NAME)
        if alias_uuid is None:
            words = {
                "alias[enabled]": "1",
                "alias[name]": ALIAS_NAME,
                "alias[type]": "mac",
                "alias[content]": "",
                "alias[description]": ALIAS_DESCRIPTION,
            }
            payload = self._post("/api/firewall/alias/addItem", words)
            if not isinstance(payload, dict) or payload.get("result") != "saved":
                raise OPNsenseError(
                    f"добавление алиаса не прошло (ответ: {payload})"
                )
            alias_uuid = payload.get("uuid") or alias_uuid
            changed = True
            logger.info("OPNsense: создан алиас %s", ALIAS_NAME)

        if self._migrate_legacy():
            changed = True

        rule_uuid = self._find_block_rule_unid()
        if rule_uuid is None:
            rule_uuid = self._add_block_rule()
            changed = True
        if self._ensure_rule_first(rule_uuid):
            changed = True
        if changed:
            self._apply()
        return alias_uuid, rule_uuid

    # ── публичный API блокировки ────────────────────────────────
    def is_blocked(self, mac: str) -> bool:
        """Заблокирован ли MAC: правило есть и активно, MAC в алиасе."""
        canon = normalize_mac(mac)
        if not canon:
            return False
        unid = self._find_block_rule_unid()
        if unid is None:
            return False
        rule = self._get_rule(unid)
        if rule is None:
            return False
        if not (rule.get("enabled") == "1" and rule["action"]["block"].get("selected")):
            return False
        return any(
            canon.lower() == entry.lower()
            for entry in self._alias_content(ALIAS_NAME)
        )

    def blocked_macs(self) -> set[str]:
        """Множество MAC с активной блокировкой (hex без ':', верхний регистр).

        Если нашего правила нет — по факту никто не заблокирован, даже
        если в алиасе остались записи. Чтение: searchRule + searchItem
        (общий алиас) — константное число запросов.
        """
        unid = self._find_block_rule_unid()
        if unid is None:
            return set()
        rule = self._get_rule(unid)
        if rule is None:
            return set()
        if not (rule.get("enabled") == "1" and rule["action"]["block"].get("selected")):
            return set()
        macs: set[str] = set()
        for entry in self._alias_content(ALIAS_NAME):
            raw = normalize_mac(entry)
            if raw:
                macs.add(raw.replace(":", ""))
        return macs

    def block_mac(self, mac: str) -> str:
        """Заблокировать устройство по MAC (добавить в общий алиас).

        Алиас-список и правило создаются/чинятся автоматически (один
        раз); далее MAC просто добавляется в содержимое алиаса и
        перегружаются alias-таблицы — правило не трогается.

        Returns:
            Строка-статус для отображения оператору.
        """
        canon = normalize_mac(mac)
        if not canon:
            raise OPNsenseError("не удалось нормализовать MAC")
        alias_uuid, _ = self.ensure_block_entities()
        macs = self._alias_content(ALIAS_NAME)
        if any(canon.lower() == m.lower() for m in macs):
            logger.info("OPNsense: устройство %s уже в списке блокировки", canon)
            return f"устройство уже заблокировано: {ALIAS_NAME}"
        macs.append(canon)
        self._set_alias_content(alias_uuid, macs)
        self._alias_reconfigure()
        logger.info("OPNsense: устройство %s добавлено в список блокировки", canon)
        return f"шлюз: правило по MAC {canon} — трафик отсечён"

    def unblock_mac(self, mac: str) -> str:
        """Снять блокировку: убрать MAC из общего алиаса.

        Returns:
            Строка-статус для отображения оператору.
        """
        canon = normalize_mac(mac)
        if not canon:
            return "шлюз: указан некорректный MAC"
        macs = self._alias_content(ALIAS_NAME)
        if not any(canon.lower() == m.lower() for m in macs):
            return "шлюз: блокировок нет"
        remaining = [m for m in macs if canon.lower() != m.lower()]
        uuid = self._get_alias_uuid(ALIAS_NAME)
        if uuid is None:
            return "шлюз: блокировок нет"
        self._set_alias_content(uuid, remaining)
        self._alias_reconfigure()
        logger.info("OPNsense: устройство %s убрано из списка блокировки", canon)
        return "шлюз: правила блокировки сняты"

    # ── ограничение скорости (Traffic Shaper) ────────────────────
    def shaper_get(self) -> dict:
        """Конфигурация шейпера (`/api/trafficshaper/settings/get`).

        Returns:
            Словарь ts: {"pipes": {"pipe": {...}}, "rules": {"rule": {...}},
            "queues": ...}. Поднимает OPNsenseError при сбое сети/API
            или неожиданном формате ответа.
        """
        payload = self._get("/api/trafficshaper/settings/get")
        ts = (payload or {}).get("ts")
        if not isinstance(ts, dict):
            raise OPNsenseError(f"неожиданный ответ шейпера: {payload}")
        return ts

    def shaper_pipes(self) -> list[dict]:
        """Каналы (pipes) шейпера как список [{uuid, name, bandwidth, metric}]."""
        ts = self.shaper_get()
        pipes = ts.get("pipes", {}).get("pipe", {})
        items = pipes.items() if isinstance(pipes, dict) else [
            (p.get("uuid"), p) for p in pipes if isinstance(p, dict)
        ]
        result = []
        for uid, p in items:
            metric = ""
            for entry in (p.get("bandwidthMetric") or {}).values():
                if str(entry.get("selected")) in ("1", "true"):
                    metric = entry.get("value") or ""
                    break
            result.append({
                "uuid": uid,
                "name": str(p.get("description") or uid),
                "bandwidth": str(p.get("bandwidth") or ""),
                "metric": metric,
            })
        return result

    def shaper_rules(self) -> list[dict]:
        """Правила шейпера как список [{uuid, description, enabled, sequence,
        target_uuid, destinations}]."""
        ts = self.shaper_get()
        rules = ts.get("rules", {}).get("rule", {})
        items = rules.items() if isinstance(rules, dict) else [
            (r.get("uuid"), r) for r in rules if isinstance(r, dict)
        ]
        result = []
        for uid, r in items:
            target = r.get("target") if isinstance(r.get("target"), dict) else {}
            target_uuid = next(
                (k for k, v in target.items()
                 if str(v.get("selected")) in ("1", "true")),
                None,
            )
            dst = r.get("destination") if isinstance(r.get("destination"), dict) else {}
            destinations = [
                k for k, v in dst.items()
                if str(v.get("selected")) in ("1", "true")
            ]
            result.append({
                "uuid": uid,
                "description": r.get("description") or "",
                "enabled": str(r.get("enabled")) == "1",
                "sequence": r.get("sequence") or "",
                "target_uuid": target_uuid,
                "destinations": destinations,
            })
        return result

    def shaper_pipe_name(self, channel_uuid: str) -> str | None:
        """Имя канала по uuid; None, если такого канала на шлюзе нет."""
        for pipe in self.shaper_pipes():
            if pipe["uuid"] == channel_uuid:
                return pipe["name"]
        return None

    def _shaper_marker(self, mac: str) -> str:
        """Маркер-описание нашего правила шейпера для этого MAC."""
        canon = normalize_mac(mac) or ""
        return SHAPE_RULE_PREFIX + canon.replace(":", "")

    def _shaper_rule_body(
        self, mac: str, ip: str, channel_uuid: str,
    ) -> dict:
        """Тело правила шейпера для устройства.

        Поля копируют схему правил TING: шейпер матчит destination=IP
        (канал ограничивает трафик к устройству, как у правил оператора).
        Пустые src_port/dst_port/source_not/destination_not намеренно не
        передаются — на TING addrule на них падает с "Undefined index:
        uuid" (проверено на живом шлюзе).
        """
        return {
            "enabled": "1",
            "sequence": str(SHAPE_SEQUENCE),
            "interface": "lan",
            "interface2": "",
            "proto": "ip",
            "direction": "",
            "source": "any",
            "destination": ip,
            "target": channel_uuid,
            "description": self._shaper_marker(mac),
        }

    def _shaper_find(self, mac: str) -> dict | None:
        """Наше правило шейпера для MAC, или None."""
        marker = self._shaper_marker(mac)
        for rule in self.shaper_rules():
            if rule["description"] == marker:
                return rule
        return None

    def shaper_device_status(self, mac: str) -> dict | None:
        """Применённое к устройству правило шейпера, или None.

        Returns:
            Правило из shaper_rules (description == netview-shape-<MAC>)
            или None, если устройству канал не назначен.
        """
        if not normalize_mac(mac):
            return None
        return self._shaper_find(mac)

    def _shaper_reconfigure(self) -> None:
        """Применить изменения конфигурации шейпера (dummynet/etc.)."""
        payload = self._post_no_body("/api/trafficshaper/service/reconfigure")
        status = str((payload or {}).get("status", "")).strip().lower()
        if status != "ok":
            raise OPNsenseError(
                f"применение шейпера вернуло неожиданный ответ: {payload}"
            )

    def shaper_apply(self, mac: str, ip: str, channel_uuid: str) -> str:
        """Установить устройству ограничение скорости каналом.

        Создаёт/обновляет наше правило шейпера (destination=IP →
        канал) и применяет конфигурацию. Идемпотентно.

        Returns:
            Строка-статус для отображения оператору.
        """
        canon = normalize_mac(mac)
        if not canon:
            raise OPNsenseError("не удалось нормализовать MAC")
        if not ip:
            raise OPNsenseError("устройство без IP — правило шейпера применить нельзя")
        if not channel_uuid:
            raise OPNsenseError("не указан канал")
        body = self._shaper_rule_body(canon, ip, channel_uuid)
        existing = self._shaper_find(canon)
        if existing:
            payload = self._post_json(
                f"/api/trafficshaper/settings/setrule/{existing['uuid']}",
                {"rule": body},
            )
            if not isinstance(payload, dict) or payload.get("result") != "saved":
                raise OPNsenseError(
                    f"обновление правила шейпера не прошло (ответ: {payload})"
                )
            logger.info("OPNsense: шейпер %s -> канал %s (правило %s)",
                        canon, channel_uuid, existing["uuid"])
        else:
            body["uuid"] = str(uuid_lib.uuid4())
            payload = self._post_json(
                "/api/trafficshaper/settings/addrule",
                {"rule": body},
            )
            if not isinstance(payload, dict) or payload.get("result") != "saved":
                raise OPNsenseError(
                    f"добавление правила шейпера не прошло (ответ: {payload})"
                )
            logger.info("OPNsense: шейпер %s -> канал %s (правило %s)",
                        canon, channel_uuid, payload.get("uuid"))
        self._shaper_reconfigure()
        return f"шлюз: канал установлен (MAC {canon})"

    def shaper_clear(self, mac: str) -> str:
        """Снять ограничение скорости: удалить наше правило шейпера.

        Returns:
            Строка-статус для отображения оператору.
        """
        canon = normalize_mac(mac)
        if not canon:
            return "шлюз: указан некорректный MAC"
        rule = self._shaper_find(canon)
        if rule is None:
            return "шлюз: ограничение скорости не задано"
        payload = self._post_no_body(
            f"/api/trafficshaper/settings/delrule/{rule['uuid']}"
        )
        if str((payload or {}).get("result", "")).strip() != "deleted":
            raise OPNsenseError(
                f"удаление правила шейпера не прошло (ответ: {payload})"
            )
        self._shaper_reconfigure()
        logger.info("OPNsense: шейпер %s — ограничение снято", canon)
        return "шлюз: ограничение скорости снято"
