"""Schema-level tests for the novel module tables (Task 4).

These exercise the conftest SQLite schema mirror of novel_read_progress and
users.novel_prefs directly, independent of the router (added in Task 5).
"""

from sqlalchemy import text


async def test_novel_read_progress_upsert_roundtrip(db_session):
    await db_session.execute(
        text("INSERT INTO novel_read_progress (user_id, file_path, position) VALUES (:u, :p, :pos)"),
        {"u": 1, "p": "作品A/第01章.md", "pos": "act:0|offset:0"},
    )
    await db_session.commit()
    # upsert to a new position
    await db_session.execute(
        text(
            "INSERT INTO novel_read_progress (user_id, file_path, position) "
            "VALUES (:u, :p, :pos) "
            "ON CONFLICT (user_id, file_path) DO UPDATE SET position = :pos"
        ),
        {"u": 1, "p": "作品A/第01章.md", "pos": "act:1|offset:42"},
    )
    await db_session.commit()
    row = (
        await db_session.execute(
            text("SELECT position FROM novel_read_progress WHERE user_id=:u AND file_path=:p"),
            {"u": 1, "p": "作品A/第01章.md"},
        )
    ).first()
    assert row[0] == "act:1|offset:42"


async def test_users_novel_prefs_column_exists(db_session):
    await db_session.execute(
        text("INSERT INTO users (username, password_hash, novel_prefs) VALUES (:n, :h, :prefs)"),
        {"n": "reader1", "h": "x", "prefs": '{"font": 18}'},
    )
    await db_session.commit()
    row = (await db_session.execute(text("SELECT novel_prefs FROM users WHERE username=:n"), {"n": "reader1"})).first()
    assert row[0] == '{"font": 18}'
