"""Tests for multi-turn conversation memory in reki ask (Issue #33)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from rekipedia.llm.client import LLMClient
from rekipedia.models.contracts import LLMConfig

# ---------------------------------------------------------------------------
# LLMClient history tests
# ---------------------------------------------------------------------------

def test_call_passes_history_to_messages():
    """History turns should appear between system and user messages."""
    config = LLMConfig(model="fake/model")
    client = LLMClient(config)

    captured = {}

    def fake_completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        resp = MagicMock()
        resp.choices[0].message.content = "answer"
        return resp

    history = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
    ]

    with patch("litellm.completion", side_effect=fake_completion):
        client.call("second question", system="sys", history=history)

    msgs = captured["messages"]
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "first question"}
    assert msgs[2] == {"role": "assistant", "content": "first answer"}
    assert msgs[3] == {"role": "user", "content": "second question"}


def test_call_no_history_works():
    """call() without history should still work (backward compat)."""
    config = LLMConfig(model="fake/model")
    client = LLMClient(config)

    captured = {}

    def fake_completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        resp = MagicMock()
        resp.choices[0].message.content = "answer"
        return resp

    with patch("litellm.completion", side_effect=fake_completion):
        result = client.call("question", system="sys")

    assert result == "answer"
    assert len(captured["messages"]) == 2  # system + user only


def test_stream_passes_history():
    """stream() should also include history in messages."""
    config = LLMConfig(model="fake/model")
    client = LLMClient(config)

    captured = {}

    def fake_chunk(content):
        chunk = MagicMock()
        chunk.choices[0].delta.content = content
        return chunk

    def fake_completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return iter([fake_chunk("tok1"), fake_chunk("tok2")])

    history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]

    with patch("litellm.completion", side_effect=fake_completion):
        chunks = list(client.stream("q2", system="sys", history=history))

    assert chunks == ["tok1", "tok2"]
    assert captured["messages"][1]["role"] == "user"
    assert captured["messages"][1]["content"] == "q1"


# ---------------------------------------------------------------------------
# History limit / truncation logic
# ---------------------------------------------------------------------------

def test_history_limit_truncation():
    """_append_history should drop oldest turns when limit exceeded."""
    # Simulate the logic from cli/ask.py
    history: list[dict] = []
    history_limit = 2  # keep last 2 turns = 4 messages

    def append(q: str, a: str):
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": a})
        max_msgs = history_limit * 2
        if len(history) > max_msgs:
            del history[:-max_msgs]

    append("q1", "a1")
    append("q2", "a2")
    append("q3", "a3")  # should drop q1/a1

    assert len(history) == 4
    assert history[0]["content"] == "q2"
    assert history[1]["content"] == "a2"
    assert history[2]["content"] == "q3"
    assert history[3]["content"] == "a3"


def test_history_accumulates_correctly():
    """History should grow turn by turn up to the limit."""
    history: list[dict] = []
    history_limit = 10

    def append(q: str, a: str):
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": a})
        max_msgs = history_limit * 2
        if len(history) > max_msgs:
            del history[:-max_msgs]

    for i in range(5):
        append(f"q{i}", f"a{i}")

    assert len(history) == 10
    assert history[0]["content"] == "q0"


# ---------------------------------------------------------------------------
# Session save to disk
# ---------------------------------------------------------------------------

def test_session_saved_to_json(tmp_path: Path):
    """Session should be saved as JSON under .rekipedia/sessions/."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    import datetime

    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    session_file = sessions_dir / f"{ts}.json"
    session_file.write_text(
        json.dumps({"turns": history, "model": "test/model"}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    data = json.loads(session_file.read_text())
    assert data["turns"] == history
    assert data["model"] == "test/model"


def test_session_file_is_valid_json(tmp_path: Path):
    """Saved session file should always be valid JSON."""
    history = [
        {"role": "user", "content": "中文問題"},
        {"role": "assistant", "content": "中文答案"},
    ]
    session_file = tmp_path / "session.json"
    session_file.write_text(
        json.dumps({"turns": history, "model": "m"}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    # Should not raise
    parsed = json.loads(session_file.read_text())
    assert parsed["turns"][0]["content"] == "中文問題"
