"""The real engine, as a child process, with the model on the GPU (ADR-0011, ADR-0016).

These tests run only on the owner's machine, with `uv run pytest -m integration`. The model and
the private sample come from the `NO_GIT` folder beside the repository, and a test skips when
what it needs is missing. Of the sample, only ids and numbers ever reach the output.
"""

import itertools
import json
import re
import statistics
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from jiffin.protocol.framing import read_line, write_message
from jiffin.protocol.jsonrpc import Request, SuccessResponse, parse_response
from jiffin.protocol.messages import (
    INITIALIZE,
    JUDGE,
    PROTOCOL_VERSION,
    REWRITE,
    SHUTDOWN,
    Context,
    EngineSettings,
    InitializeParams,
    JudgeParams,
    Method,
    RewriteParams,
    ShutdownParams,
    Statement,
    Strict,
)

pytestmark = pytest.mark.integration

NO_GIT = Path(__file__).resolve().parents[3] / "NO_GIT"
MODEL = (
    NO_GIT / "rizzo-flow" / "models" / "rizzo-flow" / "spark-x2.5-4b-rizzo-flow-lora-q4_k_m.gguf"
)
SAMPLE = NO_GIT / "sibyl-campione"
MEASURED = NO_GIT / "sibyl-misura" / "risultati" / "alt-rizzo-q4.jsonl"
REWRITTEN = SAMPLE / "asserzioni-rizzo-q4-v2.json"
SETTINGS = EngineSettings(  # ADR-0011
    context_per_question=2048, micro_batch=16, load_mode="direct_io", kv_cache="f16"
)

# Measured on this machine for ADR-0011, with Rizzo Flow's code.
LOADED_MIB, PEAK_MIB = 3_227, 3_245
DELAY_P95_SECONDS = 0.508
NOISE = 0.05
# The delay moves with what else the machine is doing: writing the prompts takes the CPU for
# about a fifth of it. On 2026-09-30 its p95 went from 467 to 561 ms within an hour, with the
# same code. Without the shared prefix, 20 questions would decode three times the tokens.
DELAY_NOISE = 0.25
BUDGET_MIB = 4 * 1024  # ADR-0003
REWRITE_SECONDS = 0.4  # the most #37 expects
# The prototype sent 18 questions per context (yes in A, and yes in B) in micro-batches of 4,
# with 8,192 tokens per question; the engine sends 9, in one micro-batch, with 2,048. On the
# GPU the result of a sum depends on how the batch is laid out, so d moves a little: in the
# prototype's layout the engine gives every d exactly (checked for #36).
PARITY_MAX, PARITY_MEAN = 0.5, 0.1
"""Largest and mean |Δd| allowed; measured on 2026-09-30: 0.371 and 0.082."""

CONTEXT = Context(
    app="vivaldi",
    title="CHANGELOG.md at main · rossi/gestionale",
    address="github.com/rossi/gestionale/blob/main/CHANGELOG.md",
)
STATEMENTS = [
    Statement(id=number, text=text)
    for number, text in enumerate(
        [
            "The user is working on the Rossi project.",
            "The user is reading the changelog of a project.",
            "The user is writing code.",
            "The user is reviewing a pull request.",
            "The user is on the website of a bank.",
            "The user is paying a bill.",
            "The user is writing an email.",
            "The user is in a video call.",
            "The user is editing a spreadsheet.",
            "The user is designing icons.",
            "The user is reading the news.",
            "The user is shopping online.",
            "The user is booking a train.",
            "The user is watching a video that is not about work.",
            "The user is listening to music.",
            "The user is on a social network.",
            "The user is reading documentation.",
            "The user is not working on the Rossi project.",
            "The user is working on a project other than Rossi.",
            "The user is doing something that is not related to work.",
        ],
        start=1,
    )
]
# Invented conditions, none of them among the prompt's examples, with what each statement must
# keep: a name, a negation, an "or" (ADR-0008).
CONDITIONS = {
    "se non sto lavorando al progetto Verdi": ("not", "Verdi"),
    "quando guardo una partita o leggo di calcio": (" or ",),
    "se sono su Amazon": ("Amazon",),
    "quando uso Excel per la contabilità": ("Excel",),
    "se sto facendo una videochiamata su Teams": ("Teams",),
}


class EngineProcess:
    """The engine started and spoken to as the app does, without timeouts or restarts."""

    def __init__(self) -> None:
        self.idle_mib = gpu_used_mib()
        self.process = subprocess.Popen(
            [sys.executable, "-m", "jiffin.engine"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        self._ids = itertools.count(1)
        self.call(
            INITIALIZE,
            InitializeParams(protocol=PROTOCOL_VERSION, model_path=str(MODEL), settings=SETTINGS),
        )
        self.loaded_mib = gpu_used_mib() - self.idle_mib

    def call[R: Strict | None](self, method: Method[Any, R], params: Strict) -> R:
        assert self.process.stdin is not None and self.process.stdout is not None
        write_message(
            self.process.stdin, Request(id=next(self._ids), method=method.name, params=params)
        )
        line = read_line(self.process.stdout)
        assert line is not None, "the engine closed its stdout"
        response = parse_response(line, method.result)
        assert isinstance(response, SuccessResponse), response
        return response.result

    def judge(self, context: Context, statements: list[Statement]) -> dict[int, float]:
        result = self.call(JUDGE, JudgeParams(context=context, statements=statements))
        return {score.id: score.d for score in result.scores}

    def rewrite(self, condition: str) -> str:
        return self.call(REWRITE, RewriteParams(condition=condition)).statement

    def close(self) -> int:
        """Shut down, close stdin as the app does, and return the exit code."""
        assert self.process.stdin is not None
        self.call(SHUTDOWN, ShutdownParams())
        self.process.stdin.close()
        return self.process.wait(timeout=60)


def gpu_used_mib() -> int:
    """Memory in use on the whole GPU: on Windows nvidia-smi does not tell it per process."""
    query = ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]
    return int(subprocess.run(query, capture_output=True, text=True, check=True).stdout.split()[0])


@pytest.fixture(scope="module")
def engine() -> Iterator[EngineProcess]:
    if not MODEL.is_file():
        pytest.skip(f"the model is not in {MODEL}")
    started = EngineProcess()
    yield started
    assert started.close() == 0


def test_vram_with_20_statements_per_call_and_rewriting(engine: EngineProcess) -> None:
    judging = engine.loaded_mib
    for _ in range(10):
        engine.judge(CONTEXT, STATEMENTS)
        judging = max(judging, gpu_used_mib() - engine.idle_mib)
    both = judging
    for condition in CONDITIONS:
        engine.rewrite(condition)
        engine.judge(CONTEXT, STATEMENTS)
        both = max(both, gpu_used_mib() - engine.idle_mib)
    print(
        f"VRAM: {engine.loaded_mib} MiB loaded, {judging} MiB at peak judging, "
        f"{both} MiB at peak judging and rewriting"
    )
    assert engine.loaded_mib <= LOADED_MIB * (1 + NOISE)
    assert judging <= PEAK_MIB * (1 + NOISE)
    assert both <= BUDGET_MIB


def test_judge_delay_for_20_statements(engine: EngineProcess) -> None:
    for _ in range(3):  # warm-up
        engine.judge(CONTEXT, STATEMENTS)
    delays = []
    for _ in range(40):
        started = time.perf_counter()
        engine.judge(CONTEXT, STATEMENTS)
        delays.append(time.perf_counter() - started)
    p50, p95 = statistics.median(delays), statistics.quantiles(delays, n=20)[-1]
    print(f"judge, 20 statements: p50 {p50 * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms")
    assert p95 <= DELAY_P95_SECONDS * (1 + DELAY_NOISE)


def test_rewrite_keeps_names_negations_and_alternatives(engine: EngineProcess) -> None:
    for condition, kept in CONDITIONS.items():
        statement = engine.rewrite(condition)
        print(f"{condition!r} -> {statement!r}")
        assert statement.startswith("The user ") and statement.endswith(".")
        assert all(words in statement for words in kept), statement


def test_rewrite_time(engine: EngineProcess) -> None:
    times = []
    for condition in CONDITIONS:
        started = time.perf_counter()
        engine.rewrite(condition)
        times.append(time.perf_counter() - started)
    print(f"rewrite: p50 {statistics.median(times) * 1000:.0f} ms, max {max(times) * 1000:.0f} ms")
    assert max(times) <= REWRITE_SECONDS


def test_d_matches_what_the_prototype_measured(engine: EngineProcess) -> None:
    private = (MEASURED, SAMPLE / "etichette.json", SAMPLE / "asserzioni.json")
    if not all(path.is_file() for path in private):
        pytest.skip(f"the private sample is not in {NO_GIT}")
    sample = json.loads((SAMPLE / "etichette.json").read_text(encoding="utf-8"))
    rewritten = json.loads((SAMPLE / "asserzioni.json").read_text(encoding="utf-8"))
    # The prototype's variant `json / en / f2 / sa`, without its runs on an empty context.
    measured = {
        (row["ctx"], row["rem"]): row["d"]
        for row in map(json.loads, MEASURED.read_text(encoding="utf-8").splitlines())
        if (row["stato"], row["lingua"], row["form"], row["ordine"]) == ("json", "en", "f2", "sa")
        and row["ctx"] != "__vuoto__"
    }
    reminders = [reminder["id"] for reminder in sample["reminders"]]
    statements = [
        Statement(id=number, text=rewritten[reminder]["en"])
        for number, reminder in enumerate(reminders)
    ]
    differences = []
    for sampled in sample["contexts"]:
        context = Context(
            app=sampled["app"],
            title=sampled.get("title") or "",
            address=sampled.get("address_bar") or None,
        )
        for number, d in engine.judge(context, statements).items():
            differences.append(abs(d - measured[(sampled["id"], reminders[number])]))
    differences.sort()
    mean = statistics.fmean(differences)
    print(
        f"parity on {len(differences)} pairs: |d - measured| max {differences[-1]:.3f}, "
        f"p99 {differences[int(0.99 * len(differences))]:.3f}, mean {mean:.3f}"
    )
    assert len(differences) == len(measured) == 954
    assert differences[-1] <= PARITY_MAX
    assert mean <= PARITY_MEAN


def test_rewrites_match_what_the_prototype_wrote(engine: EngineProcess) -> None:
    if not all(path.is_file() for path in (SAMPLE / "etichette.json", REWRITTEN)):
        pytest.skip(f"the private sample is not in {NO_GIT}")
    reminders = json.loads((SAMPLE / "etichette.json").read_text(encoding="utf-8"))["reminders"]
    theirs = json.loads(REWRITTEN.read_text(encoding="utf-8"))
    # The condition is what comes before "ricordami", as the prototype took it.
    condition = re.compile(r"^\s*((?:quando|se)\b.*?)[\s,]+ricordami\b", re.IGNORECASE | re.DOTALL)
    same = 0
    for reminder in reminders:
        match = condition.match(reminder["text"])
        assert match is not None
        same += engine.rewrite(match.group(1).strip()) == theirs[reminder["id"]]["en"]
    print(f"rewrites equal to the prototype's: {same} of {len(reminders)}")
    assert same == len(reminders)
