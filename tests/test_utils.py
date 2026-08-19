"""Тесты общих утилит: human_size и sort_items."""

from app.utils import human_size, sort_items

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
