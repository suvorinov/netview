"""Тесты общих утилит: human_size и sort_items."""

from datetime import UTC, datetime, timedelta

from app.utils import (
    group_devices_by_ip,
    human_size,
    is_in_dhcp_pool,
    is_new_device,
    is_protected_mac,
    is_router_vendor,
    is_unknown_device,
    is_vendor_mismatch,
    normalize_mac,
    parse_dhcp_pool,
    parse_mac_list,
    sort_items,
)

SORT_MAP = {"name": "name", "cpu": "cpu"}


# ── human_size ───────────────────────────────────────────────


def test_human_size_none():
    assert human_size(None) == "—"


def test_human_size_bytes():
    assert human_size(0) == "0 B"
    assert human_size(1023) == "1023 B"


def test_human_size_units():
    assert human_size(1024) == "1.0 KB"
    assert human_size(1536) == "1.5 KB"
    assert human_size(1048576) == "1.0 MB"
    assert human_size(5 * 1024**4) == "5.0 TB"


def test_human_size_string():
    assert human_size("512") == "512 B"
    assert human_size("abc") == "abc"


def test_human_size_negative():
    assert human_size(-5) == "-5"


# ── sort_items ───────────────────────────────────────────────


def test_sort_strings_asc():
    items = [
        {"name": "zeta", "cpu": 50},
        {"name": "Alpha", "cpu": 10},
        {"name": "beta", "cpu": 30},
    ]
    result = sort_items(items, "name", "asc", SORT_MAP)
    assert [i["name"] for i in result] == ["Alpha", "beta", "zeta"]


def test_sort_numbers_desc():
    items = [
        {"name": "a", "cpu": 50},
        {"name": "b", "cpu": 10},
        {"name": "c", "cpu": 30},
    ]
    result = sort_items(items, "cpu", "desc", SORT_MAP)
    assert [i["cpu"] for i in result] == [50, 30, 10]


def test_sort_numeric_strings():
    items = [{"v": "75"}, {"v": "10"}, {"v": "3"}]
    result = sort_items(items, "v", "asc", {"v": "v"})
    assert [i["v"] for i in result] == ["3", "10", "75"]


def test_sort_empty_values_at_end():
    items = [{"x": 5}, {"x": None}, {"x": 1}, {"x": ""}]
    result = sort_items(items, "x", "asc", {"x": "x"})
    assert [i["x"] for i in result] == [1, 5, None, ""]


def test_sort_empty_values_at_end_desc():
    items = [{"x": 5}, {"x": None}, {"x": 1}]
    result = sort_items(items, "x", "desc", {"x": "x"})
    assert [i["x"] for i in result] == [5, 1, None]


def test_sort_unknown_field_unchanged():
    items = [{"name": "b"}, {"name": "a"}]
    assert sort_items(items, "unknown", "asc", SORT_MAP) == items


def test_sort_empty_list():
    assert sort_items([], "name", "asc", SORT_MAP) == []


def test_sort_case_insensitive():
    items = [{"name": "Z"}, {"name": "a"}, {"name": "b"}]
    result = sort_items(items, "name", "asc", SORT_MAP)
    assert [i["name"] for i in result] == ["a", "b", "Z"]


# ── is_router_vendor ─────────────────────────────────────────


def test_router_vendor_markers():
    assert is_router_vendor("TP-LINK TECHNOLOGIES CO.,LTD.")
    assert is_router_vendor("D-Link Corporation")
    assert is_router_vendor("MikroTik") or is_router_vendor("Routerboard")


def test_router_vendor_asus_unknown_hostname_only():
    assert is_router_vendor("ASUSTek COMPUTER INC.", hostname_unknown=True)
    assert not is_router_vendor("ASUSTek COMPUTER INC.", hostname_unknown=False)


def test_router_vendor_other():
    assert not is_router_vendor("Intel Corporate")
    assert not is_router_vendor("KYOCERA Display Corporation")
    assert not is_router_vendor("")


def test_router_vendor_none():
    assert not is_router_vendor(None)


# ── is_vendor_mismatch ───────────────────────────────────────


def test_mismatch_router_vendor_with_known_hostname():
    """Роутерный вендор + разрешённое имя ПК = рассинхрон записи
    (кейс: DHCP выдал адрес роутера Windows-хосту zr-37)."""
    assert is_vendor_mismatch("TP-LINK TECHNOLOGIES CO.,LTD.", True)
    assert is_vendor_mismatch("D-Link Corporation", True)


def test_mismatch_router_vendor_unknown_hostname_is_not_mismatch():
    """Неразрешённый hostname у роутерного вендора — норма, это просто роутер."""
    assert not is_vendor_mismatch("TP-LINK TECHNOLOGIES CO.,LTD.", False)
    assert not is_vendor_mismatch("MikroTik", False)


def test_mismatch_asustek_never():
    """ASUSTek + разрешённое имя — обычный ПК с платой ASUS, не конфликт."""
    assert not is_vendor_mismatch("ASUSTek COMPUTER INC.", True)
    assert not is_vendor_mismatch("ASUSTek COMPUTER INC.", False)


def test_mismatch_other_vendors():
    assert not is_vendor_mismatch("Intel Corporate", True)
    assert not is_vendor_mismatch("", True)
    assert not is_vendor_mismatch(None, True)


# ── normalize_mac / parse_mac_list / is_protected_mac ────────


def test_normalize_mac_formats():
    assert normalize_mac("aabbccddeeff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"


def test_normalize_mac_invalid():
    assert normalize_mac("") is None
    assert normalize_mac(None) is None
    assert normalize_mac("zz:zz:zz:zz:zz:zz") is None
    assert normalize_mac("AA:BB:CC:DD:EE") is None


def test_parse_mac_list():
    macs = parse_mac_list(" aa-bb-cc-dd-ee-01 , AABBCCDDEE02, мусор, aa:bb:cc:dd:ee:01 ")
    assert macs == ("AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02")


def test_is_protected_mac():
    protected = parse_mac_list("AA:BB:CC:DD:EE:FF")
    assert is_protected_mac("aabbccddeeff", protected)
    assert not is_protected_mac("11:22:33:44:55:66", protected)
    assert not is_protected_mac(None, protected)
    # Строка конфига напрямую тоже допустима
    assert is_protected_mac("AA:BB:CC:DD:EE:FF", "AA-BB-CC-DD-EE-FF")


# ── group_devices_by_ip ──────────────────────────────────────


def _dev(id_, ip, mac, last_seen):
    return {
        "id": id_,
        "ip_address": ip,
        "mac_address": mac,
        "hostname": f"host-{id_}",
        "last_seen": last_seen,
        "first_seen": "2026-08-01T00:00:00",
    }


def test_group_keeps_freshest_per_ip():
    devices = [
        _dev(1, "192.168.0.37", "AA", "2026-08-20T10:00:00"),
        _dev(2, "192.168.0.37", "BB", "2026-08-24T09:00:00"),
        _dev(3, "192.168.0.50", "CC", "2026-08-23T09:00:00"),
    ]
    groups = group_devices_by_ip(devices)

    assert len(groups) == 2
    fresh = next(g for g in groups if g["ip_address"] == "192.168.0.37")
    assert fresh["mac_address"] == "BB"  # свежайшая запись — первичная
    assert [h["mac_address"] for h in fresh["_history"]] == ["AA"]


def test_group_history_sorted_newest_first():
    devices = [
        _dev(1, "10.0.0.1", "AA", "2026-08-10T00:00:00"),
        _dev(2, "10.0.0.1", "BB", "2026-08-22T00:00:00"),
        _dev(3, "10.0.0.1", "CC", "2026-08-15T00:00:00"),
    ]
    primary = group_devices_by_ip(devices)[0]

    assert primary["mac_address"] == "BB"
    assert [h["mac_address"] for h in primary["_history"]] == ["CC", "AA"]


def test_group_tie_broken_by_id():
    """Равные last_seen: свежее та запись, что создана позже (больше id)."""
    devices = [
        _dev(7, "10.0.0.5", "AA", "2026-08-24T00:00:00"),
        _dev(9, "10.0.0.5", "BB", "2026-08-24T00:00:00"),
    ]
    primary = group_devices_by_ip(devices)[0]
    assert primary["mac_address"] == "BB"
    assert [h["mac_address"] for h in primary["_history"]] == ["AA"]


def test_group_single_records_untouched():
    devices = [_dev(1, "10.0.0.9", "AA", "2026-08-24T00:00:00")]
    groups = group_devices_by_ip(devices)
    assert len(groups) == 1
    assert "_history" not in groups[0]


def test_group_missing_last_seen_falls_back_to_first_seen():
    d_old = _dev(1, "10.0.0.9", "AA", "")
    d_old["first_seen"] = "2026-08-02T00:00:00"
    d_new = _dev(2, "10.0.0.9", "BB", "")
    d_new["first_seen"] = "2026-08-20T00:00:00"
    primary = group_devices_by_ip([d_old, d_new])[0]
    assert primary["mac_address"] == "BB"


def test_group_input_order_preserved():
    devices = [
        _dev(1, "10.0.0.30", "AA", "2026-08-24T00:00:00"),
        _dev(2, "10.0.0.20", "BB", "2026-08-24T00:00:00"),
        _dev(3, "10.0.0.30", "CC", "2026-08-25T00:00:00"),
    ]
    ips = [g["ip_address"] for g in group_devices_by_ip(devices)]
    assert ips == ["10.0.0.30", "10.0.0.20"]


# ── is_unknown_device ────────────────────────────────────────


def test_unknown_device_empty_hostname():
    assert is_unknown_device({"hostname": ""})


def test_unknown_device_marker():
    assert is_unknown_device({"hostname": "Неизвестное устройство"})


def test_known_device():
    assert not is_unknown_device({"hostname": "zr-10.zr.local"})


def test_unknown_device_missing_key():
    assert is_unknown_device({})


# ── is_new_device ────────────────────────────────────────────


def test_new_device_recent():
    recent = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    assert is_new_device({"first_seen": recent})


def test_new_device_old():
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    assert not is_new_device({"first_seen": old})


def test_new_device_naive():
    naive = (datetime.now() - timedelta(days=1)).isoformat()
    assert is_new_device({"first_seen": naive})


def test_new_device_missing_or_broken():
    assert not is_new_device({})
    assert not is_new_device({"first_seen": "не-дата"})


# ── DHCP pool ─────────────────────────────────────────────────


def test_parse_dhcp_pool_valid():
    assert parse_dhcp_pool("192.168.0.31,192.168.0.199") == (
        "192.168.0.31", "192.168.0.199",
    )
    assert parse_dhcp_pool(" 192.168.0.31 , 192.168.0.199 ") == (
        "192.168.0.31", "192.168.0.199",
    )


def test_parse_dhcp_pool_invalid():
    assert parse_dhcp_pool("") is None
    assert parse_dhcp_pool(None) is None
    assert parse_dhcp_pool("192.168.0.31") is None
    assert parse_dhcp_pool("abc,def") is None
    assert parse_dhcp_pool("1.2.3.4,999.0.0.1") is None


def test_is_in_dhcp_pool():
    pool = ("192.168.0.31", "192.168.0.199")
    assert is_in_dhcp_pool("192.168.0.100", pool)
    assert is_in_dhcp_pool("192.168.0.31", pool)
    assert is_in_dhcp_pool("192.168.0.199", pool)
    assert not is_in_dhcp_pool("192.168.0.30", pool)
    assert not is_in_dhcp_pool("192.168.0.200", pool)
    assert not is_in_dhcp_pool("10.0.0.5", pool)


def test_is_in_dhcp_pool_disabled_or_broken():
    assert not is_in_dhcp_pool("192.168.0.100", None)
    assert not is_in_dhcp_pool("192.168.0.100", ("bad", "end"))
    assert not is_in_dhcp_pool("не-адрес", ("192.168.0.31", "192.168.0.199"))
    assert not is_in_dhcp_pool(None, ("192.168.0.31", "192.168.0.199"))


# ── Шаблонные фильтры ────────────────────────────────────────


def test_time_ago_handles_tz_aware(app):
    """Дата со смещением таймзоны не роняет фильтр (раньше — TypeError)."""
    time_ago = app.jinja_env.filters["time_ago"]
    assert time_ago("2026-08-21T10:00:00+03:00")
    assert time_ago(None) == "—"


def test_time_ago_naive_string(app):
    """Наивная дата по-прежнему обрабатывается (30 секунд — «только что»)."""
    time_ago = app.jinja_env.filters["time_ago"]
    recent = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    assert time_ago(recent) == "только что"
