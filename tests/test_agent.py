"""The AI agent, against a scripted stand-in for OpenRouter: no network, no credits."""

import json

import pytest

from dwg_sheets.agent import MAX_ROUNDS, Agent, AgentError, ProfileCache, summarize
from dwg_sheets.sheets import DEFAULT_SCALE_PATTERN, DEFAULT_TITLE_PATTERN, Rect

SHEET_NO = r"Sheet no:\s*(\S+)"


def text(s, x, y):
    return {"text": s, "at": [x, y]}


def drawing(label="Sheet no:", n=3):
    """`n` sheets side by side, each a 42 x 29.7 frame with a title text and a 1:100 scale."""
    rects, texts = [], []
    for i in range(n):
        x = 50 * i
        rects.append(Rect(x, 0, x + 42, 29.7))
        texts += [text(f"{label} S-{i + 1:02d}", x + 35, 3), text("Scale 1:100", x + 35, 2), text("Wall", x + 5, 20)]
    return rects, texts


def call(name, **args):
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def reply(*calls, cost=0.001, content=None):
    message = {"role": "assistant", "content": content, "tool_calls": list(calls) or None}
    return {"choices": [{"message": message}], "usage": {"cost": cost}}


class ScriptedChat:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, body):
        self.requests.append(json.loads(json.dumps(body)))  # a copy: the agent keeps appending to its messages
        if not self.responses:
            raise AssertionError("the agent asked more than the script holds")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_agent_tests_a_pattern_then_uses_it():
    rects, texts = drawing()
    chat = ScriptedChat(
        reply(call("try_profile", title_pattern=SHEET_NO)),
        reply(call("use_profile", title_pattern=SHEET_NO)),
    )
    found = Agent(chat, "test/model").detect(rects, texts)

    assert (found.title_pattern, found.scale_pattern, found.status) == (SHEET_NO, DEFAULT_SCALE_PATTERN, "improved")
    assert found.cost_usd == pytest.approx(0.002)
    first = chat.requests[0]
    assert first["model"] == "test/model"
    assert first["tool_choice"] == "required"
    assert "Sheet no: S-#" in first["messages"][1]["content"]  # texts are folded by shape
    assert '"sheets_found": 0' in first["messages"][1]["content"]  # the built-in result is shown
    # The trial ran the real sheet finder and its answer went back to the model.
    tool_reply = chat.requests[1]["messages"][-1]
    assert tool_reply["role"] == "tool" and tool_reply["tool_call_id"] == "call_try_profile"
    trial = json.loads(tool_reply["content"])
    assert trial["sheets_found"] == 3
    assert trial["sheet_names"][0] == "S-01 (1:100)"


def test_builtin_patterns_are_kept_when_the_model_does_no_better():
    rects, texts = drawing(label="PL. NR.")
    chat = ScriptedChat(reply(call("use_profile", title_pattern=r"PL\. NR\. (S-01)")))  # finds only one sheet
    found = Agent(chat).detect(rects, texts)
    assert (found.title_pattern, found.status) == (DEFAULT_TITLE_PATTERN, "agreed")


def test_failures_fall_back_to_the_builtin_patterns():
    rects, texts = drawing()
    found = Agent(ScriptedChat(AgentError("OpenRouter answered 402: no credits"))).detect(rects, texts)
    assert (found.title_pattern, found.status, found.cost_usd) == (DEFAULT_TITLE_PATTERN, "failed", None)

    bad = ScriptedChat(reply(call("use_profile", title_pattern="Sheet no: (unclosed")))
    assert Agent(bad).detect(rects, texts).status == "failed"

    no_group = ScriptedChat(reply(call("use_profile", title_pattern="Sheet no")))
    assert Agent(no_group).detect(rects, texts).status == "failed"


def test_an_invalid_trial_is_reported_to_the_model():
    rects, texts = drawing()
    chat = ScriptedChat(
        reply(call("try_profile", title_pattern="(")),
        reply(call("use_profile", title_pattern=SHEET_NO)),
    )
    assert Agent(chat).detect(rects, texts).status == "improved"
    assert "not a valid regular expression" in json.loads(chat.requests[1]["messages"][-1]["content"])["error"]


def test_the_last_turn_must_answer():
    rects, texts = drawing()
    tries = [reply(call("try_profile", title_pattern=SHEET_NO)) for _ in range(MAX_ROUNDS - 1)]
    chat = ScriptedChat(*tries, reply(call("use_profile", title_pattern=SHEET_NO)))
    assert Agent(chat).detect(rects, texts).status == "improved"
    assert chat.requests[-1]["tool_choice"] == {"type": "function", "function": {"name": "use_profile"}}
    assert all(r["tool_choice"] == "required" for r in chat.requests[:-1])


def test_a_reply_without_a_tool_call_is_asked_again():
    rects, texts = drawing()
    chat = ScriptedChat(reply(content="I think it is Sheet no"), reply(call("use_profile", title_pattern=SHEET_NO)))
    assert Agent(chat).detect(rects, texts).status == "improved"
    assert chat.requests[1]["messages"][-1] == {
        "role": "user",
        "content": "Answer with a tool call: try_profile or use_profile.",
    }


def test_no_answer_in_time_falls_back():
    rects, texts = drawing()
    chat = ScriptedChat(*[reply(content="hmm") for _ in range(MAX_ROUNDS)])
    assert Agent(chat).detect(rects, texts).status == "failed"


def test_answers_are_cached_per_drawing_and_model(tmp_path):
    rects, texts = drawing()
    cache = ProfileCache(tmp_path / "profiles")
    first = ScriptedChat(reply(call("use_profile", title_pattern=SHEET_NO)))
    assert Agent(first, "a/model", cache).detect(rects, texts).status == "improved"

    again = ScriptedChat()  # any call would fail the test
    found = Agent(again, "a/model", cache).detect(rects, texts)
    assert (found.title_pattern, found.status, found.cost_usd) == (SHEET_NO, "cached", None)

    other_model = ScriptedChat(reply(call("use_profile", title_pattern=SHEET_NO)))
    Agent(other_model, "b/model", cache).detect(rects, texts)
    assert len(other_model.requests) == 1

    stored = json.loads(next((tmp_path / "profiles").glob("*.json")).read_text())
    assert set(stored) == {"title_pattern", "scale_pattern"}  # only patterns, no drawing texts


def test_cache_purges_old_answers(tmp_path):
    cache = ProfileCache(tmp_path, max_age_seconds=60)
    cache.put("k", {"title_pattern": "x"})
    cache.purge(now=(tmp_path / "k.json").stat().st_mtime + 30)
    assert cache.get("k")
    cache.purge(now=(tmp_path / "k.json").stat().st_mtime + 120)
    assert cache.get("k") is None


def test_summary_folds_numbers_and_stays_small():
    texts = [text(f"{i}.{i % 10}", 0, 0) for i in range(20_000)] + [text("PLANSA NR. 7", 0, 0)]
    rects = [Rect(0, 0, 10 * i, 5 * i) for i in range(1, 30)]
    summary = summarize(texts, rects)
    assert summary.startswith("20001 texts, 2 distinct shapes")
    assert '20000 | "#.#"' in summary
    assert '1 | "PLANSA NR. #" | ["PLANSA NR. 7"]' in summary
    assert "290 x 145" in summary  # the largest rectangles
    assert len(summary) < 45_000
