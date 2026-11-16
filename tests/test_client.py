import json

import httpx
import pytest

from owui_pop import client


def fake_owui(answers, fail_polls=0, status=200):
    """A tiny Open WebUI: saves the chat, then each poll shows the next piece of the answer."""
    state = {"chat": None, "polls": 0, "fails": fail_polls, "posts": []}

    def handle(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "POST" and path == "/api/v1/chats/new":
            state["chat"] = json.loads(req.content)["chat"]
            return httpx.Response(200, json={"id": "c1"})
        if req.method == "POST" and path == "/api/chat/completions":
            state["posts"].append(json.loads(req.content))
            return httpx.Response(status, json={})
        if req.method == "POST" and path == "/api/v1/chats/c1":
            state["chat"] = json.loads(req.content)["chat"]
            return httpx.Response(200, json={})
        if req.method == "GET" and path == "/api/v1/chats/c1":
            if state["fails"]:
                state["fails"] -= 1
                return httpx.Response(502)
            i = min(state["polls"], len(answers) - 1)
            state["polls"] += 1
            chat = state["chat"]
            aid = chat["history"]["currentId"]
            node = dict(chat["history"]["messages"][aid], content=answers[i], done=i == len(answers) - 1, parentId=None)
            chat["history"]["messages"][aid] = node
            return httpx.Response(200, json={"chat": chat})
        return httpx.Response(404)

    return state, httpx.Client(transport=httpx.MockTransport(handle), base_url="http://owui")


def turn(c, messages, **kw):
    got = []
    chat_id = client.run_turn("http://owui", "sk", "m", ["t1"], None, messages, got.append, lambda: False, c,
                              sleep=lambda s: None, **kw)
    return chat_id, got


def test_a_turn_streams_the_answer_and_relinks_the_question():
    state, c = fake_owui(["Hel", "Hello <details>tool</details>", "Hello there"])
    msgs = [client.new_message("user", "hi"), client.new_message("assistant")]
    chat_id, got = turn(c, msgs)
    assert chat_id == "c1"
    assert got == ["Hel", "Hello", "Hello there"]
    assert state["posts"][0]["tool_ids"] == ["t1"] and state["posts"][0]["chat_id"] == "c1"
    hist = state["chat"]["history"]["messages"]
    assert hist[msgs[1]["id"]]["parentId"] == msgs[0]["id"]  # put back after Open WebUI dropped it


def test_slow_polls_are_not_a_failed_answer():
    _, c = fake_owui(["done"], fail_polls=3)
    chat_id, got = turn(c, [client.new_message("user", "q"), client.new_message("assistant")])
    assert chat_id == "c1" and got == ["done"]


def test_a_refused_key_says_so():
    _, c = fake_owui(["x"], status=401)
    with pytest.raises(client.TurnError, match="refused the API key"):
        turn(c, [client.new_message("user", "q"), client.new_message("assistant")])


def test_stopping_returns_nothing():
    _, c = fake_owui(["a", "b", "c"])
    msgs = [client.new_message("user", "q"), client.new_message("assistant")]
    assert client.run_turn("http://owui", "sk", "m", [], None, msgs, lambda t: None, lambda: True, c, sleep=lambda s: None) is None


def test_clean_drops_reasoning_even_while_it_is_written():
    assert client.clean("<details type='reasoning'>thinking") == ""
    assert client.clean("A\n\n\n\nB") == "A\n\nB"


def test_check_lists_models_or_explains():
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"id": "a"}, {"x": 1}]})))
    assert client.check("http://owui", "k", ok) == client.Check(True, ["a"])
    down = httpx.Client(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("no"))))
    assert client.check("http://owui", "k", down).error == "Couldn't reach the server."


def test_build_chat_is_a_straight_line():
    msgs = [client.new_message("user", "a"), client.new_message("assistant", "b"), client.new_message("user", "c")]
    chat = client.build_chat("m", msgs, now=1)
    hist = chat["history"]["messages"]
    assert hist[msgs[1]["id"]]["parentId"] == msgs[0]["id"]
    assert hist[msgs[0]["id"]]["childrenIds"] == [msgs[1]["id"]]
    assert chat["history"]["currentId"] == msgs[2]["id"]
