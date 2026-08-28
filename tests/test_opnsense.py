"""Тесты клиента REST API брандмауэра OPNsense (TING).

HTTP-слой заглушается подменой session-объекта на фейк, который пишет
все запросы и возвращает canned-ответы. Проверяем протокол блокировки
по схеме «общий алиас + одно правило»:

- инфраструктура (алиас netview_block_mac + правило netview-block)
  создаётся один раз и не дублируется;
- блок/разблок = добавить/убрать MAC из содержимого алиаса
  (setItem) + перегрузка alias-таблиц (reconfigure);
- допускается миграция остатков старой схемы per-MAC;
- статусы (is_blocked / blocked_macs) читают правило и содержимое алиаса.

Эндпоинты соответствуют живому TING: legacy searchAlias и
moveRuleBefore отсутствуют; setItem требует alias[name]; содержимое
алиаса пишется через перевод строк, читается через запятую.
"""

import pytest

from app.api.opnsense import (
    ALIAS_NAME,
    OPNsenseClient,
    OPNsenseError,
)

MAC = "aa-bb-cc-dd-ee-99"
MAC_CANON = "AA:BB:CC:DD:EE:99"
MAC_HEX = "AABBCCDDEE99"
MAC2_CANON = "00:11:22:33:44:55"

RULE_DESC = "netview-block"


class _FakeResp:
    """Заглушка requests.Response."""

    def __init__(self, payload=None, status=200):
        self._payload = payload
        self.status_code = status

    @property
    def content(self):
        return b"" if self._payload is None else b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OPNsenseError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _SideEffect(Exception):
    """Выброс для проверки «аварийных» веток (сетевой сбой)."""


class _FakeSession:
    """Запоминает все вызовы и раздаёт canned-ответы по URL.

    Значением в `responses` может быть список — тогда ответы выдаются
    по одному за вызов (нужно для эндпоинтов, вызываемых несколько раз).
    """

    def __init__(self, responses=None, fail_on=None):
        self.calls = []  # [(method, url, data)]
        self.responses = responses or {}
        self.fail_on = fail_on  # подстрока URL → сетевая ошибка

    def _handle(self, method, url, data):
        self.calls.append((method, url, data))
        if self.fail_on and self.fail_on in url:
            raise OPNsenseError(f"нет соединения с шлюзом ({self.fail_on})")
        val = self.responses.get(url)
        if val is None:
            raise OPNsenseError(f"неожиданный URL: {url}")
        if isinstance(val, list):
            val = val.pop(0)
        if isinstance(val, _SideEffect):
            raise val
        if isinstance(val, tuple):
            payload, status = val
        else:
            payload, status = val, 200  # голый payload → status 200
        fake = _FakeResp(payload, status)
        if status >= 400:
            fake.raise_for_status()
        return fake

    def get(self, url, timeout=None, auth=None):
        return self._handle("GET", url, None)

    def post(self, url, **kwargs):
        body = kwargs.get("data") if "data" in kwargs else kwargs.get("json")
        return self._handle("POST", url, body)


def _client(session=None):
    c = OPNsenseClient("http://gw.local", "key", "secret", timeout=5)
    c._session = session or _FakeSession()
    return c


BASE = "http://gw.local/api/firewall/filter"
ALIAS = "http://gw.local/api/firewall/alias"
ALIAS_UUID = "alias-uuid-1"
RULE_UUID = "rule-uuid-1"


def _alias_content_payload(content: str) -> dict:
    return {"rows": [{"uuid": ALIAS_UUID, "name": ALIAS_NAME, "content": content}]}


def _alias_rows(*entries: str) -> dict:
    return _alias_content_payload(",".join(entries))


def _rule_rows(*rows: dict) -> dict:
    return {"rows": list(rows)}


def _block_rule_row(seq="1"):
    return {"uuid": RULE_UUID, "description": RULE_DESC, "sequence": seq}


def _other_rule_row(uid=None, desc="allow lan", seq="1"):
    return {"uuid": uid or "other-1", "description": desc, "sequence": seq}


def _get_rule_payload(uid=RULE_UUID):
    return {"rule": {"enabled": "1", "action": {"block": {"selected": True}}}}


def _no_block_entities(session):
    """Стейт фейка: на шлюзе пусто (нет алиаса и правила)."""
    session.responses.setdefault(
        f"{ALIAS}/getAliasUUID/{ALIAS_NAME}", ({}, 200))
    session.responses.setdefault(
        f"{ALIAS}/searchItem", ({"rows": []}, 200))
    session.responses.setdefault(
        f"{ALIAS}/addItem", ({"result": "saved", "uuid": ALIAS_UUID}, 200))
    session.responses.setdefault(
        f"{ALIAS}/setItem/{ALIAS_UUID}", ({"result": "saved"}, 200))
    session.responses.setdefault(
        f"{ALIAS}/reconfigure", ({"status": "ok"}, 200))
    session.responses.setdefault(
        f"{BASE}/getRule/{RULE_UUID}", (_get_rule_payload(), 200))
    session.responses.setdefault(
        f"{BASE}/addRule", ({"result": "saved", "uuid": RULE_UUID}, 200))
    session.responses.setdefault(
        f"{BASE}/apply", ({"status": "OK"}, 200))


def test_block_creates_alias_and_rule_once_then_adds_mac():
    s = _FakeSession()
    _no_block_entities(s)
    # searchRule: наше правило отсутствует (миграция не находит legacy) →
    # поиск правила не находит → после создания rule стоит первым
    s.responses[f"{BASE}/searchRule"] = [
        _rule_rows(),                       # миграция: сканирование legacy
        _rule_rows(),                       # поиск правила (нет)
        _rule_rows(_block_rule_row()),      # после создания — уже первое
    ]
    s.responses[f"{ALIAS}/searchItem"] = [
        ({"rows": []}, 200),                # миграция: путой поиск алиасов
        _alias_content_payload(""),         # текущее содержимое (пусто)
    ]
    c = _client(s)

    status = c.block_mac(MAC)

    assert "MAC" in status
    # алиас создан с пустым содержимым
    add_alias = next(call for call in s.calls if call[1] == f"{ALIAS}/addItem")
    assert add_alias[2]["alias[name]"] == ALIAS_NAME
    assert add_alias[2]["alias[type]"] == "mac"
    assert add_alias[2]["alias[content]"] == ""
    # правило source=алиас, quick
    add_rule = next(call for call in s.calls if call[1] == f"{BASE}/addRule")
    assert add_rule[2]["rule[source_net]"] == ALIAS_NAME
    assert add_rule[2]["rule[action]"] == "block"
    assert add_rule[2]["rule[description]"] == RULE_DESC
    # содержимое обновляется через setItem (перевод строк), затем reconfigure
    set_item = next(call for call in s.calls if call[1] == f"{ALIAS}/setItem/{ALIAS_UUID}")
    assert set_item[2] == {"alias[name]": ALIAS_NAME, "alias[content]": MAC_CANON}
    assert any(call[1] == f"{ALIAS}/reconfigure" for call in s.calls)


def test_block_reuses_existing_entities_and_appends_mac():
    s = _FakeSession(
        {
            f"{ALIAS}/getAliasUUID/{ALIAS_NAME}": ({"uuid": ALIAS_UUID}, 200),
            f"{ALIAS}/searchItem": [
                _alias_rows(MAC_CANON),                 # миграция: есть legacy-скан
                _alias_rows(MAC_CANON),                 # содержимое перед блоком
            ],
            f"{BASE}/searchRule": _rule_rows(_block_rule_row()),
            f"{BASE}/getRule/{RULE_UUID}": (_get_rule_payload(), 200),
            f"{ALIAS}/setItem/{ALIAS_UUID}": ({"result": "saved"}, 200),
            f"{ALIAS}/reconfigure": ({"status": "ok"}, 200),
        }
    )
    c = _client(s)

    status = c.block_mac(MAC2_CANON)

    assert "MAC" in status
    set_item = next(call for call in s.calls if call[1] == f"{ALIAS}/setItem/{ALIAS_UUID}")
    assert set_item[2]["alias[content]"] == f"{MAC_CANON}\n{MAC2_CANON}"
    # ни addItem, ни addRule не вызывались
    assert not [c[1] for c in s.calls if "addItem" in c[1] or "addRule" in c[1]]


def test_block_idempotent_when_mac_already_listed():
    s = _FakeSession(
        {
            f"{ALIAS}/getAliasUUID/{ALIAS_NAME}": ({"uuid": ALIAS_UUID}, 200),
            f"{ALIAS}/searchItem": [
                _alias_rows(MAC_CANON),
                _alias_rows(MAC_CANON),
            ],
            f"{BASE}/searchRule": _rule_rows(_block_rule_row()),
            f"{BASE}/getRule/{RULE_UUID}": (_get_rule_payload(), 200),
        }
    )
    c = _client(s)

    status = c.block_mac(MAC)

    assert "уже" in status
    assert not [c[1] for c in s.calls if "setItem" in c[1] or "reconfigure" in c[1]]


def test_block_recreates_missing_rule():
    """Правило снесли вручную — при блокировке создаётся заново."""
    s = _FakeSession(
        {
            f"{ALIAS}/getAliasUUID/{ALIAS_NAME}": ({"uuid": ALIAS_UUID}, 200),
            f"{ALIAS}/searchItem": [
                _alias_rows(),
                _alias_content_payload(MAC_CANON),
            ],
            f"{ALIAS}/addItem": ({"result": "saved", "uuid": ALIAS_UUID}, 200),
            f"{ALIAS}/setItem/{ALIAS_UUID}": ({"result": "saved"}, 200),
            f"{ALIAS}/reconfigure": ({"status": "ok"}, 200),
            f"{BASE}/getRule/{RULE_UUID}": (_get_rule_payload(), 200),
            f"{BASE}/addRule": ({"result": "saved", "uuid": RULE_UUID}, 200),
            f"{BASE}/apply": ({"status": "OK"}, 200),
        }
    )
    s.responses[f"{BASE}/searchRule"] = [
        _rule_rows(),                    # миграция: сканирование legacy
        _rule_rows(),                    # поиск правила (отсутствует)
        _rule_rows(_block_rule_row()),   # после создания — первое
    ]
    c = _client(s)

    c.block_mac(MAC)

    assert any(call[1] == f"{BASE}/addRule" for call in s.calls)
    assert any(call[1] == f"{BASE}/apply" for call in s.calls)


def test_unblock_removes_mac_and_reconfigures():
    s = _FakeSession(
        {
            f"{ALIAS}/getAliasUUID/{ALIAS_NAME}": ({"uuid": ALIAS_UUID}, 200),
            f"{ALIAS}/searchItem": [
                _alias_rows(MAC_CANON, MAC2_CANON),   # миграция-скан
                _alias_rows(MAC_CANON, MAC2_CANON),   # содержимое перед разблоком
            ],
            f"{BASE}/searchRule": _rule_rows(),
            f"{ALIAS}/setItem/{ALIAS_UUID}": ({"result": "saved"}, 200),
            f"{ALIAS}/reconfigure": ({"status": "ok"}, 200),
        }
    )
    c = _client(s)

    status = c.unblock_mac(MAC)

    assert "сняты" in status
    set_item = next(call for call in s.calls if call[1] == f"{ALIAS}/setItem/{ALIAS_UUID}")
    assert set_item[2]["alias[content]"] == MAC2_CANON
    assert any(call[1] == f"{ALIAS}/reconfigure" for call in s.calls)


def test_unblock_when_not_blocked_is_quiet():
    s = _FakeSession(
        {
            f"{ALIAS}/searchItem": [{"rows": []}],
        }
    )
    c = _client(s)
    status = c.unblock_mac(MAC)
    assert "нет" in status
    assert not [c[1] for c in s.calls if "setItem" in c[1] or "reconfigure" in c[1]]


def test_is_blocked_requires_rule_and_mac():
    s = _FakeSession(
        {
            f"{ALIAS}/searchItem": _alias_rows(MAC_CANON),
            f"{BASE}/searchRule": _rule_rows(_block_rule_row()),
            f"{BASE}/getRule/{RULE_UUID}": (_get_rule_payload(), 200),
        }
    )
    c = _client(s)
    assert c.is_blocked(MAC) is True
    assert c.is_blocked(MAC2_CANON) is False


def test_is_blocked_false_without_rule():
    s = _FakeSession(
        {
            f"{ALIAS}/searchItem": _alias_rows(MAC_CANON),
            f"{BASE}/searchRule": _rule_rows(),
        }
    )
    assert _client(s).is_blocked(MAC) is False


def test_blocked_macs_returns_hex_set():
    s = _FakeSession(
        {
            f"{ALIAS}/searchItem": _alias_rows(MAC_CANON, "00:11:22:33:44:55"),
            f"{BASE}/searchRule": _rule_rows(_block_rule_row()),
            f"{BASE}/getRule/{RULE_UUID}": (_get_rule_payload(), 200),
        }
    )
    assert _client(s).blocked_macs() == {MAC_HEX, "001122334455"}


def test_blocked_macs_empty_without_rule():
    s = _FakeSession(
        {
            f"{ALIAS}/searchItem": _alias_rows(MAC_CANON),
            f"{BASE}/searchRule": _rule_rows(),
        }
    )
    assert _client(s).blocked_macs() == set()


def test_migrate_folds_legacy_per_mac_entities():
    """Остатки старой схемы переносятся в общий алиас и удаляются."""
    legacy_alias_uuid = "legacy-alias"
    legacy_alias_row = {
        "uuid": legacy_alias_uuid,
        "name": "netview_mac_aabbccddee99",
        "content": MAC_CANON,
    }
    our_alias_row = {"uuid": ALIAS_UUID, "name": ALIAS_NAME, "content": ""}
    s = _FakeSession(
        {
            f"{ALIAS}/getAliasUUID/{ALIAS_NAME}": ({"uuid": ALIAS_UUID}, 200),
            f"{ALIAS}/searchItem": [
                {"rows": [legacy_alias_row, our_alias_row]},  # миграция: сканирование
                {"rows": [{"uuid": ALIAS_UUID, "name": ALIAS_NAME, "content": ""}]},
                {"rows": [{"uuid": ALIAS_UUID, "name": ALIAS_NAME,
                           "content": MAC_CANON}]},           # после миграции
            ],
            f"{ALIAS}/setItem/{ALIAS_UUID}": [
                ({"result": "saved"}, 200),   # перенос legacy MAC
                ({"result": "saved"}, 200),   # добавление нового MAC
            ],
            f"{ALIAS}/delItem/{legacy_alias_uuid}": ({"result": "deleted"}, 200),
            f"{ALIAS}/reconfigure": ({"status": "ok"}, 200),
            f"{BASE}/delRule/legacy-rule": ({"result": "deleted"}, 200),
            f"{BASE}/addRule": ({"result": "saved", "uuid": RULE_UUID}, 200),
            f"{BASE}/getRule/{RULE_UUID}": (_get_rule_payload(), 200),
            f"{BASE}/apply": ({"status": "OK"}, 200),
        }
    )
    # searchRule: миграция видит legacy-правило, поиск нашего — пусто,
    # после создания наше правило первое
    s.responses[f"{BASE}/searchRule"] = [
        _rule_rows({"uuid": "legacy-rule", "description": "netview-block-aabbccddee99"}),
        _rule_rows(),
        _rule_rows(_block_rule_row()),
    ]
    c = _client(s)

    c.block_mac(MAC2_CANON)

    # последний setItem собирает legacy MAC + новый
    set_item = [call for call in s.calls if call[1] == f"{ALIAS}/setItem/{ALIAS_UUID}"][-1]
    entries = set_item[2]["alias[content]"].split("\n")
    assert MAC_CANON in entries and MAC2_CANON in entries
    assert any(call[1] == f"{ALIAS}/delItem/{legacy_alias_uuid}" for call in s.calls)
    assert any(call[1] == f"{BASE}/delRule/legacy-rule" for call in s.calls)


def test_block_mac_raises_when_set_item_fails():
    s = _FakeSession(
        {
            f"{ALIAS}/getAliasUUID/{ALIAS_NAME}": ({"uuid": ALIAS_UUID}, 200),
            f"{ALIAS}/searchItem": [
                {"rows": []},  # миграция: сканирование вызов
                {"rows": [{"uuid": ALIAS_UUID, "name": ALIAS_NAME, "content": ""}]},
            ],
            f"{BASE}/searchRule": _rule_rows(_block_rule_row()),
            f"{ALIAS}/setItem/{ALIAS_UUID}": ({"result": "failed"}, 200),
        }
    )
    c = _client(s)
    with pytest.raises(OPNsenseError):
        c.block_mac(MAC)


def test_raises_on_network_error():
    c = _client(_FakeSession(fail_on="searchItem"))
    with pytest.raises(OPNsenseError):
        c.block_mac(MAC)


# ── шейпер (ограничение скорости) ───────────────────────────────

TS = "http://gw.local/api/trafficshaper"
PIPE_1M = "pipe-1mbit"
PIPE_2M = "pipe-2mbit"
RULE_SHAPE_UUID = "shape-rule-uuid-1"
MARKER = "netview-shape-" + MAC_HEX
IP = "192.168.0.95"


def _pipe_body(name, bandwidth="1", metric="Mbit/s", enabled="1"):
    def _metric(value, selected):
        return {"value": value, "selected": 1 if selected else 0}

    return {
        "number": "10000",
        "enabled": enabled,
        "bandwidth": bandwidth,
        "bandwidthMetric": {
            "Kbit": _metric("kbit/s", metric == "kbit/s"),
            "Mbit": _metric("Mbit/s", metric == "Mbit/s"),
            "Gbit": _metric("Gbit/s", False),
        },
        "description": name,
    }


def _rule_body(desc, target, destinations, enabled="1", seq="90"):
    return {
        "description": desc,
        "enabled": enabled,
        "sequence": seq,
        "source": {"any": {"value": "any", "selected": 1}},
        "destination": {d: {"value": d, "selected": 1} for d in destinations},
        "interface": {"lan": {"value": "LAN", "selected": 1}},
        "target": {
            PIPE_1M: {"value": "1Mbit", "selected": 1 if target == PIPE_1M else 0},
            PIPE_2M: {"value": "2Mbit", "selected": 1 if target == PIPE_2M else 0},
        },
    }


def _ts_get_payload(pipes=None, rules=None):
    return {
        "ts": {
            "pipes": {"pipe": pipes or {}},
            "queues": [],
            "rules": {"rule": rules or {}},
        }
    }


def test_shaper_pipes_parses_channels():
    s = _FakeSession(
        {
            f"{TS}/settings/get": _ts_get_payload(
                pipes={
                    PIPE_1M: _pipe_body("1Mbit", "1", "Mbit/s"),
                    PIPE_2M: _pipe_body("2Mbit", "2", "Mbit/s"),
                }
            ),
        }
    )
    c = _client(s)
    assert c.shaper_pipes() == [
        {"uuid": PIPE_1M, "name": "1Mbit", "bandwidth": "1", "metric": "Mbit/s"},
        {"uuid": PIPE_2M, "name": "2Mbit", "bandwidth": "2", "metric": "Mbit/s"},
    ]
    assert c.shaper_pipe_name(PIPE_2M) == "2Mbit"
    assert c.shaper_pipe_name("nope") is None


def test_shaper_device_status_finds_rule_by_marker():
    s = _FakeSession(
        {
            f"{TS}/settings/get": _ts_get_payload(
                rules={RULE_SHAPE_UUID: _rule_body(MARKER, PIPE_2M, [IP])}
            ),
        }
    )
    c = _client(s)
    status = c.shaper_device_status(MAC)
    assert status["uuid"] == RULE_SHAPE_UUID
    assert status["target_uuid"] == PIPE_2M
    assert status["destinations"] == [IP]
    assert status["enabled"] is True
    assert c.shaper_device_status(MAC2_CANON) is None


def test_shaper_apply_creates_rule_via_json_addrule():
    s = _FakeSession(
        {
            f"{TS}/settings/get": _ts_get_payload(
                pipes={PIPE_1M: _pipe_body("1Mbit", "1", "Mbit/s")}
            ),
            f"{TS}/settings/addrule": ({"result": "saved", "uuid": "new-uuid"}, 200),
            f"{TS}/service/reconfigure": ({"status": "ok"}, 200),
        }
    )
    c = _client(s)
    msg = c.shaper_apply(MAC, IP, PIPE_1M)
    assert "канал установлен" in msg
    addrule = next(call for call in s.calls if call[1] == f"{TS}/settings/addrule")
    body = addrule[2]["rule"]
    assert body["destination"] == IP
    assert body["target"] == PIPE_1M
    assert body["description"] == MARKER
    assert body["interface"] == "lan"
    assert body["direction"] == ""
    assert body["source"] == "any"
    assert body["sequence"] == "90"
    assert body["enabled"] == "1"
    assert "src_port" not in body and "dst_port" not in body
    assert body["uuid"]  # uuid_lib подставил клиент
    assert any(call[1] == f"{TS}/service/reconfigure" for call in s.calls)


def test_shaper_apply_updates_existing_rule_via_setrule():
    s = _FakeSession(
        {
            f"{TS}/settings/get": _ts_get_payload(
                rules={RULE_SHAPE_UUID: _rule_body(MARKER, PIPE_1M, [IP])}
            ),
            f"{TS}/settings/setrule/{RULE_SHAPE_UUID}": ({"result": "saved"}, 200),
            f"{TS}/service/reconfigure": ({"status": "ok"}, 200),
        }
    )
    c = _client(s)
    c.shaper_apply(MAC, IP, PIPE_2M)
    assert not [call for call in s.calls if call[1].endswith("addrule")]
    setrule = next(
        call for call in s.calls if call[1] == f"{TS}/settings/setrule/{RULE_SHAPE_UUID}"
    )
    assert setrule[2]["rule"]["target"] == PIPE_2M
    assert setrule[2]["rule"]["destination"] == IP
    assert any(call[1] == f"{TS}/service/reconfigure" for call in s.calls)


def test_shaper_apply_raises_when_ip_missing():
    c = _client(_FakeSession())
    with pytest.raises(OPNsenseError):
        c.shaper_apply(MAC, "", PIPE_1M)


def test_shaper_apply_raises_when_addrule_fails():
    s = _FakeSession(
        {
            f"{TS}/settings/get": _ts_get_payload(),
            f"{TS}/settings/addrule": ({"result": "failed"}, 200),
        }
    )
    c = _client(s)
    with pytest.raises(OPNsenseError, match="добавление"):
        c.shaper_apply(MAC, IP, PIPE_1M)


def test_shaper_clear_deletes_rule_and_reconfigures():
    s = _FakeSession(
        {
            f"{TS}/settings/get": _ts_get_payload(
                rules={RULE_SHAPE_UUID: _rule_body(MARKER, PIPE_2M, [IP])}
            ),
            f"{TS}/settings/delrule/{RULE_SHAPE_UUID}": ({"result": "deleted"}, 200),
            f"{TS}/service/reconfigure": ({"status": "ok"}, 200),
        }
    )
    c = _client(s)
    msg = c.shaper_clear(MAC)
    assert "снято" in msg
    assert any(call[1] == f"{TS}/settings/delrule/{RULE_SHAPE_UUID}" for call in s.calls)
    assert any(call[1] == f"{TS}/service/reconfigure" for call in s.calls)


def test_shaper_clear_when_no_rule_is_quiet():
    s = _FakeSession({f"{TS}/settings/get": _ts_get_payload()})
    c = _client(s)
    assert "не задано" in c.shaper_clear(MAC)
    assert not [
        call for call in s.calls if "delrule" in call[1] or "reconfigure" in call[1]
    ]


def test_shaper_apply_raises_when_reconfigure_fails():
    s = _FakeSession(
        {
            f"{TS}/settings/get": _ts_get_payload(
                rules={RULE_SHAPE_UUID: _rule_body(MARKER, PIPE_2M, [IP])}
            ),
            f"{TS}/settings/setrule/{RULE_SHAPE_UUID}": ({"result": "saved"}, 200),
            f"{TS}/service/reconfigure": ({"status": "failed"}, 200),
        }
    )
    c = _client(s)
    with pytest.raises(OPNsenseError, match="применение шейпера"):
        c.shaper_apply(MAC, IP, PIPE_1M)
