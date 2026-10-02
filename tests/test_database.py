import asyncio

import pytest

from akinator_bot.db import Database


async def test_unique_start_outcome_and_revision(database):
    await database.upsert_user(1)
    assert await database.start_game("game", 1)
    assert not await database.start_game("game", 1)
    assert await database.record_action("game", 0, 1, "playing")
    assert not await database.record_action("game", 0, 1, "playing")
    assert await database.finish_game("game", "correct")
    assert not await database.finish_game("game", "correct")
    user = await database.get_user(1)
    assert (user.total_guess, user.total_questions, user.correct_guess) == (1, 1, 1)


async def test_terminal_transition_and_outcome_roll_back_together(database):
    await database.upsert_user(1)
    await database.start_game("game", 1)
    await database.conn.execute(
        "CREATE TRIGGER reject_win BEFORE INSERT ON events "
        "WHEN NEW.event_type='game_correct' BEGIN SELECT RAISE(ABORT,'fail'); END"
    )
    await database.conn.commit()
    with pytest.raises(Exception, match="fail"):
        await database.record_action("game", 0, 1, "done", "correct")
    user = await database.get_user(1)
    assert (user.total_questions, user.correct_guess) == (0, 0)
    row = await (await database.conn.execute("SELECT * FROM games")).fetchone()
    assert (row["revision"], row["finished_at"]) == (0, None)


async def test_restart_expires_open_games_and_keeps_user_totals(database):
    await database.upsert_user(1)
    await database.start_game("game", 1)
    await database.record_action("game", 0, 1, "playing")
    await database.close()
    await database.connect()
    row = await (await database.conn.execute("SELECT * FROM games")).fetchone()
    assert row["status"] == "expired"
    assert row["finished_at"] is not None
    user = await database.get_user(1)
    assert (user.total_guess, user.total_questions, user.correct_guess) == (1, 1, 0)


async def test_concurrent_transactions_do_not_mix_users(database):
    async def workflow(user_id):
        await database.upsert_user(user_id)
        sid = str(user_id)
        await database.start_game(sid, user_id)
        for revision in range(10):
            await database.record_action(sid, revision, 1, "playing")
        await database.finish_game(sid, "correct")

    await asyncio.gather(*(workflow(user_id) for user_id in range(1, 51)))
    for user_id in range(1, 51):
        user = await database.get_user(user_id)
        assert (user.total_guess, user.total_questions, user.correct_guess) == (1, 10, 1)


async def test_migrates_old_database_preserving_scores(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE users (user_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, "
            "username TEXT, language_code TEXT, aki_lang TEXT, child_mode INTEGER, "
            "total_guess INTEGER, correct_guess INTEGER, wrong_guess INTEGER, "
            "unfinished_guess INTEGER, total_questions INTEGER, "
            "first_seen_at TEXT, last_seen_at TEXT)"
        )
        conn.execute(
            "INSERT INTO users VALUES(1,'Original',NULL,NULL,NULL,'en',"
            "1,10,5,2,3,100,'2025','2025')"
        )
    db = Database(path)
    await db.connect()
    try:
        user = await db.get_user(1)
        assert (user.aki_theme, user.total_guess, user.correct_guess, user.total_questions) == (
            "c",
            10,
            5,
            100,
        )
    finally:
        await db.close()


async def test_event_retention_preserves_scores_and_open_games(database):
    await database.upsert_user(1)
    await database.start_game("open", 1)
    await database.conn.execute(
        "INSERT INTO events(ts,event_type) VALUES('2000-01-01T00:00:00+00:00','old')"
    )
    await database.conn.commit()
    await database.prune(30)
    assert (await database.get_user(1)).total_guess == 1
    assert await (
        await database.conn.execute("SELECT * FROM games WHERE session_id='open'")
    ).fetchone()
    assert not await (
        await database.conn.execute("SELECT * FROM events WHERE event_type='old'")
    ).fetchone()


async def test_configured_default_theme_is_used_for_new_users(database):
    user = await database.ensure_user(1, default_theme="a")
    assert user.aki_theme == "a"
    await database.set_theme(1, "o")
    user = await database.ensure_user(1, default_theme="a")
    assert user.aki_theme == "o"


async def test_connect_is_idempotent_without_expiring_current_games(database):
    await database.upsert_user(1)
    await database.start_game("live", 1)
    await database.connect()
    row = await (
        await database.conn.execute("SELECT status FROM games WHERE session_id='live'")
    ).fetchone()
    assert row["status"] == "playing"


async def test_inline_invitation_claim_survives_restart(database):
    assert await database.claim_inline("inline-message")
    assert not await database.claim_inline("inline-message")
    await database.close()
    await database.connect()
    assert not await database.claim_inline("inline-message")
