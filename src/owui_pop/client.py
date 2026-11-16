"""Talking to Open WebUI, without any Qt, so it can be tested on its own.

A turn runs server-side, the way the web page does it: the chat is saved first, then
``/api/chat/completions`` is called with the chat id, so Open WebUI runs the model's tools and
writes the answer into the saved chat. The pop-up polls that chat to show the answer as it grows.
"""
from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import httpx

POLL_S = 0.5
TURN_LIMIT_S = 600
MAX_MISSES = 10


class TurnError(Exception):
    """A turn that could not finish, in words a person can act on."""


@dataclass
class Check:
    ok: bool
    models: list[str]
    error: str = ""


def _h(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"} if key else {}


def describe(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (401, 403):
            return f"The server refused the API key ({code})."
        return f"The server answered with an error ({code})."
    if isinstance(e, httpx.TimeoutException):
        return "The server took too long to answer."
    if isinstance(e, httpx.HTTPError):
        return "Couldn't reach the server."
    return str(e) or e.__class__.__name__


def check(url: str, key: str, client: httpx.Client | None = None) -> Check:
    """Settings → Test: the models this key can use, or why not."""
    c = client or httpx.Client(timeout=8)
    try:
        r = c.get(url.rstrip("/") + "/api/models", headers=_h(key))
        r.raise_for_status()
        data = r.json().get("data") or []
        return Check(True, [m["id"] for m in data if isinstance(m, dict) and isinstance(m.get("id"), str)])
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        return Check(False, [], describe(e))
    finally:
        if client is None:
            c.close()


def account_model(url: str, key: str, client: httpx.Client) -> str:
    """The account's default model: its own setting, then the admin default, then the first model."""
    base, h = url.rstrip("/"), _h(key)
    ui = (client.get(base + "/api/v1/users/user/settings", headers=h).json() or {}).get("ui") or {}
    models = [m for m in (ui.get("models") or []) if m]
    if not models:
        d = client.get(base + "/api/config", headers=h).json().get("default_models") or ""
        models = [m for m in d.split(",") if m]
    if not models:
        models = [m["id"] for m in client.get(base + "/api/models", headers=h).json()["data"]]
    return models[0] if models else ""


def model_tools(url: str, key: str, model: str, client: httpx.Client) -> list[str]:
    """The tools attached to the model. The web page sends these with every chat; without them
    only tools a filter forces on would run."""
    for m in client.get(url.rstrip("/") + "/api/models", headers=_h(key)).json().get("data", []):
        if m.get("id") == model:
            return ((m.get("info") or {}).get("meta") or {}).get("toolIds") or []
    return []


def new_message(role: str, content: str = "") -> dict:
    return {"role": role, "content": content, "id": str(uuid.uuid4())}


def build_chat(model: str, messages: list[dict], now: int | None = None) -> dict:
    """An Open WebUI chat object, a straight line of messages, from [{'role','content','id'}]."""
    now = int(time.time()) if now is None else now
    hist: dict[str, dict] = {}
    order, prev = [], None
    for m in messages:
        msg = {"id": m["id"], "parentId": prev, "childrenIds": [], "role": m["role"], "content": m["content"], "timestamp": now}
        if m["role"] == "user":
            msg["models"] = [model]
        else:
            msg["model"] = model
            msg["done"] = bool(m["content"])
        if prev:
            hist[prev]["childrenIds"].append(m["id"])
        hist[m["id"]] = msg
        order.append(msg)
        prev = m["id"]
    return {"title": messages[0]["content"][:60] if messages else "", "models": [model], "messages": order,
            "history": {"messages": hist, "currentId": prev}, "timestamp": now * 1000}


def clean(text: str) -> str:
    """The answer without the tool-call and reasoning blocks some servers put in the content."""
    text = re.sub(r"<details[^>]*>.*?</details>", "", text, flags=re.DOTALL)
    text = re.sub(r"<details[^>]*>.*$", "", text, flags=re.DOTALL)  # one still being written
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def relink(chat: dict, messages: list[dict]) -> bool:
    """Open WebUI 0.13 saves the answer with parentId null, so the web page starts the thread at the
    answer and hides the question. Puts the links back; True when something changed."""
    hist = chat.get("history", {}).get("messages", {})
    prev, changed = None, False
    for m in messages:
        node = hist.get(m["id"])
        if node is None:
            continue
        if node.get("parentId") != prev:
            node["parentId"] = prev
            changed = True
        if prev and m["id"] not in hist[prev].setdefault("childrenIds", []):
            hist[prev]["childrenIds"].append(m["id"])
            changed = True
        prev = m["id"]
    return changed


def run_turn(url: str, key: str, model: str, tool_ids: list[str], chat_id: str | None, messages: list[dict],
             on_update: Callable[[str], None], stopped: Callable[[], bool], client: httpx.Client,
             sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> str | None:
    """One question and answer. messages ends with the empty assistant message to fill.
    Returns the chat id, or None when stopped. Raises TurnError."""
    base, h = url.rstrip("/"), _h(key)
    answer_id = messages[-1]["id"]
    try:
        chat = build_chat(model, messages)
        if chat_id:
            client.post(f"{base}/api/v1/chats/{chat_id}", json={"chat": chat}, headers=h).raise_for_status()
        else:
            r = client.post(f"{base}/api/v1/chats/new", json={"chat": chat}, headers=h)
            r.raise_for_status()
            chat_id = r.json()["id"]
        r = client.post(f"{base}/api/chat/completions", headers=h, json={
            "model": model, "stream": True, "chat_id": chat_id, "id": answer_id, "tool_ids": tool_ids,
            "session_id": "owui-pop-" + uuid.uuid4().hex[:8],
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages[:-1]],
            "background_tasks": {"title_generation": len(messages) <= 2, "tags_generation": False,
                                 "follow_up_generation": False}})
        r.raise_for_status()
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise TurnError(describe(e)) from e

    last, started, misses = None, clock(), 0
    while not stopped():
        if clock() - started > TURN_LIMIT_S:
            raise TurnError("No answer after 10 minutes.")
        sleep(POLL_S)
        if stopped():
            return None
        try:  # one slow or failed poll is not a failed answer
            node = client.get(f"{base}/api/v1/chats/{chat_id}", headers=h, timeout=30).json()["chat"]["history"]["messages"].get(answer_id, {})
            misses = 0
        except (httpx.HTTPError, ValueError, KeyError) as e:
            misses += 1
            if misses >= MAX_MISSES:
                raise TurnError(describe(e)) from e
            continue
        text = clean(node.get("content", ""))
        if text != last:
            on_update(text)
            last = text
        if node.get("done"):
            try:
                full = client.get(f"{base}/api/v1/chats/{chat_id}", headers=h, timeout=30).json()["chat"]
                if relink(full, messages):
                    client.post(f"{base}/api/v1/chats/{chat_id}", json={"chat": full}, headers=h, timeout=30)
            except (httpx.HTTPError, ValueError, KeyError):
                pass  # only the web view's thread order; the answer is saved
            return chat_id
    return None
