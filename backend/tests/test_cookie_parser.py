"""Tests for parse_cookie_input() multi-format cookie parser."""

from plugins.builtin.gallery_dl._credentials import parse_cookie_input


def test_browser_format():
    assert parse_cookie_input("auth_token=abc; ct0=xyz") == {"auth_token": "abc", "ct0": "xyz"}


def test_per_line():
    assert parse_cookie_input("auth_token=abc\nct0=xyz") == {"auth_token": "abc", "ct0": "xyz"}


def test_json():
    assert parse_cookie_input('{"auth_token": "abc"}') == {"auth_token": "abc"}


def test_empty_string():
    assert parse_cookie_input("") == {}


def test_value_with_equals():
    assert parse_cookie_input("token=abc=123") == {"token": "abc=123"}


def test_trailing_semicolons():
    assert parse_cookie_input("a=1; b=2;") == {"a": "1", "b": "2"}


def test_mixed_empty_lines():
    assert parse_cookie_input("a=1\n\nb=2\n") == {"a": "1", "b": "2"}


def test_single_key_value():
    assert parse_cookie_input("token=abc") == {"token": "abc"}


def test_whitespace_only():
    assert parse_cookie_input("   ") == {}


def test_json_with_multiple_keys():
    result = parse_cookie_input('{"a": "1", "b": "2"}')
    assert result == {"a": "1", "b": "2"}
