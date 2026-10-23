import asyncio
import json

from wallbreaker.agent.loop import AgentEvents, run_turn
from wallbreaker.agent.messages import (
    ReasoningDelta,
    StopEvent,
    TextDelta,
    ToolUseEvent,
    user,
)
from wallbreaker.config import Config
from wallbreaker.session import RunLog, load_run_log
from wallbreaker.tools import shell
from wallbreaker.tools.registry import ToolContext, ToolRegistry


class ScriptedProvider:
    def __init__(self, script):
        self.script = script
        self.calls = 0

    async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
        events = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        for ev in events:
            yield ev


def test_registry_execute_invokes_tool_logger():
    logged = []
    ctx = ToolContext(config=Config(default_profile="x", profiles={}))
    ctx.tool_logger = lambda n, a, c, e: logged.append((n, a, c, e))
    reg = ToolRegistry(ctx)

    async def handler(args, ctx):
        return "result-text"

    reg.add("mytool", "d", {"type": "object"}, handler)
    asyncio.run(reg.execute("mytool", {"x": 1}))
    assert logged == [("mytool", {"x": 1}, "result-text", False)]


def test_tool_logger_fires_on_error():
    logged = []
    ctx = ToolContext(config=Config(default_profile="x", profiles={}))
    ctx.tool_logger = lambda n, a, c, e: logged.append((n, e))
    reg = ToolRegistry(ctx)

    async def boom(args, ctx):
        raise ValueError("nope")

    reg.add("boom", "d", {"type": "object"}, boom)
    asyncio.run(reg.execute("boom", {}))
    assert logged and logged[0][1] is True  # is_error propagated


def test_loop_surfaces_reasoning():
    provider = ScriptedProvider([
        [
            ReasoningDelta("let me think about "),
            ReasoningDelta("the objective step by step"),
            TextDelta("here is my answer"),
            StopEvent("end_turn"),
        ],
    ])
    seen = []
    events = AgentEvents(on_reasoning=lambda t: seen.append(t))
    asyncio.run(run_turn(provider, None, [user("hi")], events=events))
    assert seen == ["let me think about the objective step by step"]


def test_runlog_persists_reasoning_event(tmp_path):
    log = RunLog(directory=str(tmp_path))
    log.reasoning("the brain's chain of thought", source="brain")
    log.reasoning("", source="brain")  # blank is skipped
    lines = [json.loads(x) for x in log.path.read_text().splitlines() if x.strip()]
    reasoning = [r for r in lines if r.get("kind") == "reasoning"]
    assert len(reasoning) == 1
    assert reasoning[0]["text"] == "the brain's chain of thought"
    assert reasoning[0]["source"] == "brain"


def test_runlog_tool_events_roundtrip(tmp_path):
    log = RunLog(directory=str(tmp_path))
    log.user("do X")
    log.tool_call("swarm", {"action": "siege"})
    log.tool_result("swarm", "SWARM SIEGE - held", False)
    lines = [json.loads(x) for x in log.path.read_text().splitlines() if x.strip()]
    kinds = [r["kind"] for r in lines]
    assert kinds == ["user", "tool_call", "tool_result"]
    assert lines[1]["tool"] == "swarm" and lines[1]["args"]["action"] == "siege"
