"""Exercise actual PTB update dispatch and serialization with a fake Bot API."""

import json
from datetime import UTC, datetime

import httpx
from akipy.async_akinator import Akinator
from telegram import Update
from telegram.request import HTTPXRequest

from akinator_bot.app import _post_init, _post_shutdown, _post_stop, build_app


async def test_private_game_full_flow_through_registered_handlers(settings, monkeypatch):
    calls = []

    async def telegram(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        calls.append((endpoint, params))
        result = True
        if endpoint == "getMe":
            result = {"id": 100, "is_bot": True, "first_name": "Test", "username": "test_bot"}
        elif endpoint in {"sendPhoto", "editMessageMedia"}:
            result = {
                "message_id": 10,
                "date": 1,
                "chat": {"id": 1, "type": "private"},
                "photo": [
                    {
                        "file_id": "reusable-photo",
                        "file_unique_id": "unique",
                        "width": 10,
                        "height": 10,
                    }
                ],
            }
        elif endpoint == "sendMessage":
            result = {
                "message_id": 11,
                "date": 1,
                "chat": {"id": 1, "type": "private"},
                "text": params.get("text", ""),
            }
        return 200, json.dumps({"ok": True, "result": result}).encode()

    monkeypatch.setattr(HTTPXRequest, "do_request", telegram)

    async def start(aki, **kwargs):
        aki.uri = "https://en.akinator.com"
        aki.session, aki.identifiant, aki.theme = "session", "identifier", 1
        aki.step, aki.question, aki.progression = 0, "First?", "0"
        return aki

    monkeypatch.setattr(Akinator, "start_game", start)

    async def upstream(**kwargs):
        data = {
            "completion": "OK",
            "id_proposition": 42,
            "name_proposition": "Test character",
            "valide_contrainte": 1,
        }
        return httpx.Response(200, json=data, request=httpx.Request("POST", kwargs["url"]))

    monkeypatch.setattr("akipy.async_akinator.async_request_handler", upstream)
    app = build_app(settings)
    await app.initialize()
    await _post_init(app)
    await app.start()
    try:
        user = {"id": 1, "is_bot": False, "first_name": "Player"}
        message = {
            "message_id": 1,
            "date": int(datetime.now(UTC).timestamp()),
            "chat": {"id": 1, "type": "private"},
            "from": user,
            "text": "/play",
            "entities": [{"type": "bot_command", "offset": 0, "length": 5}],
        }
        await app.process_update(Update.de_json({"update_id": 1, "message": message}, app.bot))
        session = app.bot_data["sessions"].get_user_session(1)
        assert session and session.message_id == 10
        callback = {
            "id": "cb1",
            "from": user,
            "chat_instance": "chat",
            "message": {"message_id": 10, "date": 1, "chat": {"id": 1, "type": "private"}},
            "data": f"a:{session.session_id}:0:0",
        }
        await app.process_update(
            Update.de_json({"update_id": 2, "callback_query": callback}, app.bot)
        )
        assert session.revision == 1
        callback.update(id="cb2", data=f"w:{session.session_id}:1:y")
        await app.process_update(
            Update.de_json({"update_id": 3, "callback_query": callback}, app.bot)
        )
        user_row = await app.bot_data["db"].get_user(1)
        assert (user_row.total_guess, user_row.total_questions, user_row.correct_guess) == (1, 1, 1)
        assert app.bot_data["sessions"].active_count == 0
        endpoints = [endpoint for endpoint, _ in calls]
        assert endpoints.count("answerCallbackQuery") == 2
        assert "sendPhoto" in endpoints and endpoints.count("editMessageMedia") >= 3
    finally:
        await app.stop()
        await _post_stop(app)
        await app.shutdown()
        await _post_shutdown(app)
