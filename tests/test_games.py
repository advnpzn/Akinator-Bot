import asyncio
from unittest.mock import AsyncMock

import akipy
import httpx
import pytest

from akinator_bot.game import UpstreamBusy
from akinator_bot.sessions import GamePhase


def proposal(game, *, exhausted=False):
    game.aki.win = True
    game.aki.no_question = exhausted
    game.aki.name_proposition = "A character"
    game.aki.id_proposition = "42"
    game.session.phase = GamePhase.PROPOSITION


async def test_answer_is_counted_once_and_old_button_is_not_replayed(game, upstream):
    request = upstream({"completion": "OK", "question": "Next?", "step": 1, "progression": "10"})
    assert await game.controller.action(None, game.session, 0, "0")
    assert not await game.controller.action(None, game.session, 0, "0")
    assert request.await_count == 1
    assert game.session.revision == 1
    assert (await game.db.get_user(1)).total_questions == 1


async def test_failed_answer_does_not_change_statistics_or_keep_uncertain_session(game, upstream):
    upstream({"completion": "KO"})
    assert not await game.controller.action(None, game.session, 0, "0")
    assert (await game.db.get_user(1)).total_questions == 0
    assert game.manager.active_count == 0
    assert game.aki.client is None
    row = await (await game.db.conn.execute("SELECT status FROM games")).fetchone()
    assert row["status"] == "failed"


async def test_back_only_decrements_after_success(game, upstream):
    request = upstream({"completion": "OK", "question": "Next?", "step": 1})
    await game.controller.action(None, game.session, 0, "0")
    request.return_value = httpx.Response(
        200,
        json={"completion": "OK", "question": "First?", "step": 0},
        request=httpx.Request("POST", "https://en.akinator.com/cancel_answer"),
    )
    await game.controller.action(None, game.session, 1, "b")
    assert game.session.questions == 0
    assert (await game.db.get_user(1)).total_questions == 0
    await game.controller.action(None, game.session, 2, "b")
    assert request.await_count == 2
    assert game.session.revision == 2
    assert game.manager.active_count == 1


@pytest.mark.parametrize(
    ("response", "outcome"),
    [
        ({"completion": "OK", "id_proposition": 42, "valide_contrainte": 0}, "blocked"),
        ({"completion": "SOUNDLIKE"}, "soundlike"),
    ],
)
async def test_terminal_states_close_game_without_proposing_or_recording_win(
    game, upstream, response, outcome
):
    upstream(response)
    await game.controller.action(None, game.session, 0, "0")
    assert game.manager.active_count == 0
    assert (await game.db.get_user(1)).correct_guess == 0
    row = await (await game.db.conn.execute("SELECT status FROM games")).fetchone()
    assert row["status"] == outcome


async def test_choose_records_one_correct_game(game, upstream):
    proposal(game)
    request = upstream({})
    await game.controller.action(None, game.session, 0, "y", confirm=True)
    user = await game.db.get_user(1)
    assert (user.correct_guess, user.unfinished_guess) == (1, 0)
    assert request.await_args.kwargs["url"].endswith("/choice")
    assert not await game.controller.action(None, game.session, 0, "y", confirm=True)
    assert request.await_count == 1


async def test_confirmation_error_does_not_become_a_win(game, upstream):
    proposal(game)
    upstream({}, status=503)
    await game.controller.action(None, game.session, 0, "y", confirm=True)
    assert (await game.db.get_user(1)).correct_guess == 0
    assert game.manager.active_count == 0


async def test_excluding_guess_can_continue_questions(game, upstream):
    proposal(game)
    request = upstream({"completion": "OK", "question": "Try again?", "step": 4})
    await game.controller.action(None, game.session, 0, "n", confirm=True)
    assert request.await_args.kwargs["url"].endswith("/exclude")
    assert game.session.phase == GamePhase.PLAYING
    assert game.session.revision == 1
    assert (await game.db.get_user(1)).wrong_guess == 0


async def test_excluding_exhausted_guess_ends_soundlike(game, upstream):
    proposal(game, exhausted=True)
    upstream({"step": 15})
    await game.controller.action(None, game.session, 0, "n", confirm=True)
    assert game.manager.active_count == 0
    row = await (await game.db.conn.execute("SELECT status FROM games")).fetchone()
    assert row["status"] == "soundlike"


async def test_admission_busy_preserves_current_game_and_counts(game, monkeypatch):
    monkeypatch.setattr(
        game.controller.games, "answer", AsyncMock(side_effect=UpstreamBusy("busy"))
    )
    await game.controller.action(None, game.session, 0, "0")
    assert game.session.phase == GamePhase.PLAYING
    assert game.session.revision == 0
    assert game.manager.active_count == 1
    assert (await game.db.get_user(1)).total_questions == 0


async def test_invalid_answer_never_reaches_upstream(game, upstream):
    request = upstream({})
    await game.controller.action(None, game.session, 0, "invalid")
    assert request.await_count == 0
    assert game.manager.active_count == 1


async def test_cancel_waits_for_active_request_before_closing_client(game, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def request(**kwargs):
        entered.set()
        await release.wait()
        assert game.aki.client is not None and not game.aki.client.is_closed
        return httpx.Response(
            200,
            json={"completion": "OK", "question": "Next?", "step": 1},
            request=httpx.Request("POST", kwargs["url"]),
        )

    monkeypatch.setattr("akipy.async_akinator.async_request_handler", request)
    action = asyncio.create_task(game.controller.action(None, game.session, 0, "0"))
    await entered.wait()
    cancel = asyncio.create_task(game.controller.cancel(None, game.session))
    await asyncio.sleep(0)
    assert not cancel.done()
    assert game.aki.client is not None
    release.set()
    await asyncio.gather(action, cancel)
    assert game.manager.active_count == 0
    assert game.aki.client is None


async def test_failed_render_does_not_replay_accepted_action(game, upstream):
    request = upstream({"completion": "OK", "question": "Next?", "step": 1})
    game.renderer.edit.side_effect = RuntimeError("Telegram unavailable")
    with pytest.raises(RuntimeError):
        await game.controller.action(None, game.session, 0, "0")
    game.renderer.edit.side_effect = None
    await game.controller.action(None, game.session, 0, "0")
    assert request.await_count == 1
    assert (await game.db.get_user(1)).total_questions == 1


async def test_failed_terminal_render_still_closes_and_preserves_outcome(game, upstream):
    proposal(game)
    upstream({})
    game.renderer.edit.side_effect = RuntimeError("Telegram unavailable")
    with pytest.raises(RuntimeError):
        await game.controller.action(None, game.session, 0, "y", confirm=True)
    assert game.manager.active_count == 0
    assert (await game.db.get_user(1)).correct_guess == 1


async def test_invalid_confirmation_preserves_proposal(game, upstream):
    proposal(game)
    request = upstream({})
    assert not await game.controller.action(None, game.session, 0, "garbage", confirm=True)
    assert game.manager.active_count == 1
    assert request.await_count == 0


async def test_ambiguous_transport_error_is_not_retried(game, monkeypatch):
    request = AsyncMock(side_effect=httpx.ReadTimeout("uncertain response"))
    monkeypatch.setattr("akipy.async_akinator.async_request_handler", request)
    await game.controller.action(None, game.session, 0, "0")
    assert request.await_count == 1
    assert game.manager.active_count == 0


async def test_recoverable_invalid_choice_keeps_game(game, monkeypatch):
    request = AsyncMock(side_effect=akipy.InvalidChoiceError("rejected"))
    monkeypatch.setattr("akipy.async_akinator.async_request_handler", request)
    await game.controller.action(None, game.session, 0, "0")
    assert game.manager.active_count == 1
    assert game.session.revision == 0
