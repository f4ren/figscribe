"""The assistant benchmark: its checks, its runner and its command."""

from __future__ import annotations

import json

import pytest

from figscribe.assistant import bench
from figscribe.assistant.chat import Reply, ToolCall
from figscribe.tools import Toolbox

from .fakeserver import chunk, serve, sse


@pytest.mark.parametrize("case", bench.CASES, ids=[c.name for c in bench.CASES])
def test_each_check_passes_only_when_done(case: bench.Case) -> None:
    workspace = bench.example_workspace()
    assert case.check(workspace.project) is not None  # not done from the start
    bench.apply_solution(case, workspace)
    assert case.check(workspace.project) is None


def test_the_cases_cover_every_level() -> None:
    levels = [c.level for c in bench.CASES]
    assert len(bench.CASES) >= 20 and {"easy", "medium", "hard"} <= set(levels)
    assert len({c.name for c in bench.CASES}) == len(bench.CASES)


class SolvingModel:
    """Fulfils a case by calling its reference solution's tools, one call per
    turn, then says it is done; a stand-in for a perfect model. Only for
    cases whose solution creates no objects, as new ids differ per run."""

    name = "solver"

    def __init__(self, case: bench.Case):
        workspace = bench.example_workspace()
        self.calls: list[tuple[str, dict]] = []

        def record(name, arguments):
            self.calls.append((name, arguments))
            return Toolbox(workspace).call(name, arguments)

        case.solution(record, workspace.project)

    def respond(self, turns, on_text):
        if not self.calls:
            return Reply("Done.")
        name, arguments = self.calls.pop(0)
        return Reply("", [ToolCall(f"c{len(turns)}", name, arguments)], "tool_use")


class IdleModel:
    name = "idle"

    def respond(self, turns, on_text):
        return Reply("Sure!")


def test_a_solving_model_passes_and_an_idle_one_fails() -> None:
    case = bench.case("axis-names")
    passed = bench.run_case(case, SolvingModel(case))
    assert passed.passed and passed.rounds == 2 and passed.tool_errors == 0
    failed = bench.run_case(case, IdleModel())
    assert not failed.passed and "x label" in failed.reason
    text = bench.report([passed, failed])
    assert "axis-names" in text and "medium  1/2" in text
    data = json.loads(bench.to_json([passed], "solver"))
    assert data["model"] == "solver" and data["outcomes"][0]["passed"]


def test_a_chat_error_fails_the_case() -> None:
    class Broken:
        name = "broken"

        def respond(self, turns, on_text):
            return Reply("", [], "refusal")

    outcome = bench.run_case(bench.case("grid"), Broken())
    assert not outcome.passed and "declined" in outcome.reason


def test_the_command_runs_against_a_local_server(tmp_path, capsys) -> None:
    """`figscribe bench` against an OpenAI-compatible server that turns the
    grid on and is done."""
    panel = bench.example_workspace().project.figures[0].axes[0].id
    arguments = {"object_id": panel, "path": ["grid"], "value": True}
    tool_call = {
        "index": 0,
        "id": "c1",
        "type": "function",
        "function": {"name": "set_field", "arguments": json.dumps(arguments)},
    }
    answers = [
        sse(chunk({"tool_calls": [tool_call]}), chunk({}, "tool_calls")),
        sse(chunk({"content": "Done."}), chunk({}, "stop")),
    ]
    with serve(lambda method, path, body: answers.pop(0)) as (url, requests):
        target = tmp_path / "result.json"
        code = bench.main(
            [
                "--base-url",
                f"{url}/v1",
                "--model",
                "local",
                "--no-vision",
                "--case",
                "grid",
                "--json",
                str(target),
            ]
        )
    assert code == 0
    out = capsys.readouterr().out
    assert "Model: local at" in out and "easy    1/1" in out
    assert json.loads(target.read_text())["outcomes"][0]["passed"]
    tools = {t["function"]["name"] for t in requests[0][2]["tools"]}
    assert "render_preview" not in tools


def test_the_command_refuses_unknown_cases(capsys) -> None:
    assert bench.main(["--case", "nope"]) == 2
    assert "no case nope" in capsys.readouterr().err
