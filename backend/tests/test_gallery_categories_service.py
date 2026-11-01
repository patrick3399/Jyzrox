import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy import text

from services.gallery_categories import (
    BUILTIN_CATEGORIES,
    PALETTE,
    RESERVED_NAMES,
    load_category_map,
    resolve_category,
    resolve_with_map,
)

_MAP = {"cosplay": "Cosplay", "artist cg": "Artist CG", "non-h": "Non-H"}


def test_resolve_with_map_matches_case_insensitively_and_returns_registry_name():
    assert resolve_with_map("cosplay", _MAP) == "Cosplay"
    assert resolve_with_map("COSPLAY", _MAP) == "Cosplay"
    assert resolve_with_map("artist cg", _MAP) == "Artist CG"


def test_resolve_with_map_trims_surrounding_whitespace():
    assert resolve_with_map("  Cosplay\t", _MAP) == "Cosplay"


def test_resolve_with_map_miss_returns_none():
    assert resolve_with_map("Novel", _MAP) is None


def test_resolve_with_map_unusable_values_return_none():
    assert resolve_with_map(None, _MAP) is None
    assert resolve_with_map("", _MAP) is None
    assert resolve_with_map("   ", _MAP) is None
    assert resolve_with_map(5000, _MAP) is None
    assert resolve_with_map("Cos/play", _MAP) is None
    assert resolve_with_map("Cos\\play", _MAP) is None
    assert resolve_with_map("x" * 65, _MAP) is None


async def test_resolve_category_skips_the_query_for_unusable_input():
    db = AsyncMock()
    assert await resolve_category(db, "") is None
    assert await resolve_category(db, None) is None
    db.execute.assert_not_called()


async def test_load_category_map_and_resolve_category_use_the_registry_table(db_session):
    await db_session.execute(
        text("INSERT INTO gallery_categories (name, color, sort_order, is_builtin) VALUES ('Novel', 'teal', 11, 0)")
    )
    await db_session.commit()

    assert await load_category_map(db_session) == {"novel": "Novel"}
    assert await resolve_category(db_session, "NOVEL") == "Novel"
    assert await resolve_category(db_session, "Cosplay") is None


def test_builtin_colors_are_all_in_the_palette():
    assert {color for _, color, _ in BUILTIN_CATEGORIES} <= set(PALETTE)
    assert "gray" in PALETTE


def test_reserved_names_include_the_uncategorized_filter_token():
    assert "__uncategorized__" in RESERVED_NAMES


def test_builtin_list_matches_the_migration_seed():
    path = Path(__file__).resolve().parent.parent / "migrations" / "versions" / "0029_gallery_categories.py"
    spec = importlib.util.spec_from_file_location("migration_0029", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.BUILTIN_CATEGORIES == BUILTIN_CATEGORIES
