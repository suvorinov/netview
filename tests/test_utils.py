"""Тесты общих утилит: human_size и sort_items."""

from datetime import UTC, datetime, timedelta

from app.utils import (
    human_size,
    is_in_dhcp_pool,
    is_new_device,
    is_router_vendor,
    is_unknown_device,
    parse_dhcp_pool,
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
