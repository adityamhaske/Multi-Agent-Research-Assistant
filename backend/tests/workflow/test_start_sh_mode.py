"""`start.sh` picks real mode whenever a real run would have somewhere to go.

The defect this pins: the script looked only for Google, Anthropic or OpenAI keys. A setup
routed entirely through `custom:` (OmniRoute, any OpenAI-compatible endpoint), OpenRouter or
a keyless Ollama route had none, so it exported `LLM_MODE=fake` — which outranks `.env`'s
`LLM_MODE=real` under Compose — and every run answered every question with the scripted
demo report. Its check now mirrors `app/config.py::_validate_secrets`: a key for a keyed
provider, or a `MODEL_*` route to a keyless one.

The block under test is cut from `start.sh` itself, not restated here, so the test runs the
shipped logic; it fails loudly if the block can no longer be found. `.env`'s own
`LLM_MODE=real` is deliberately not read as a choice — `.env.example` ships it, so honouring
it would remove the no-key demo fallback for every new user — and keys saved in the app's
Settings live in the database, which the script cannot see; the fallback warning says so.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

START_SH = Path(__file__).resolve().parents[3] / "start.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="start.sh is a bash script; no bash here")


def _mode_block() -> str:
    lines = START_SH.read_text().splitlines()
    begin = next(
        (i for i, line in enumerate(lines) if line.startswith("# Decide the LLM mode")), None
    )
    assert begin is not None, "start.sh no longer has its mode-decision block"
    end = next(i for i in range(begin, len(lines)) if lines[i] == "fi")
    helpers = [line for line in lines if line.startswith(("say()", "ok()", "warn()"))]
    return "\n".join(
        ['RESET=""; GREEN=""; YELLOW=""', *helpers, *lines[begin : end + 1]]
        + ['echo "decided=${LLM_MODE:-unset}"']
    )


def _decide(tmp_path: Path, env: str, *, fake_flag: bool = False) -> tuple[str, str]:
    (tmp_path / ".env").write_text(env)
    out = subprocess.run(
        [BASH, "-euo", "pipefail", "-c", _mode_block()],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "FAKE": "1" if fake_flag else ""},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    decided = out.strip().splitlines()[-1].removeprefix("decided=")
    return decided, out


# `unset` means the script exported nothing, so Compose reads `.env`'s `LLM_MODE=real`.
@pytest.mark.parametrize(
    "env",
    [
        "LLM_MODE=real\nCUSTOM_API_KEY=sk-test\nCUSTOM_BASE_URL=http://localhost:20128/v1\n",
        "LLM_MODE=real\nOPENROUTER_API_KEY=sk-or-test\n",
        "LLM_MODE=real\nGOOGLE_API_KEY=AIza-test\n",
        "LLM_MODE=real\nMODEL_PLANNER=custom:auto/best-fast\n",
        'LLM_MODE=real\nMODEL_EXECUTOR="custom:gpt-x"\n',
        "LLM_MODE=real\nMODEL_PLANNER=ollama:qwen2.5:7b\n",
    ],
    ids=["custom-key", "openrouter-key", "google-key", "custom-route", "quoted-route", "ollama"],
)
def test_a_setup_a_real_run_can_reach_is_left_in_real_mode(tmp_path, env):
    decided, out = _decide(tmp_path, env)
    assert decided == "unset", out
    assert "Mode: real" in out


@pytest.mark.parametrize(
    "env",
    [
        "LLM_MODE=real\nGOOGLE_API_KEY=\n",
        "LLM_MODE=real\n# CUSTOM_API_KEY=sk-test\n# MODEL_PLANNER=custom:auto\n",
        "LLM_MODE=real\n",
    ],
    ids=["empty-key", "commented-out", "nothing"],
)
def test_a_setup_with_nowhere_to_go_falls_back_to_the_demo_and_says_what_that_costs(tmp_path, env):
    decided, out = _decide(tmp_path, env)
    assert decided == "fake", out
    assert "scripted demo" in out
    assert "Settings" in out, "a key saved in Settings is unused in fake mode — say so"


def test_the_fake_flag_wins_even_with_a_key(tmp_path):
    decided, out = _decide(tmp_path, "LLM_MODE=real\nCUSTOM_API_KEY=sk-test\n", fake_flag=True)
    assert decided == "fake", out
