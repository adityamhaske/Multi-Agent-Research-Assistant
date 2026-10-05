"""A deterministic OpenAI-compatible provider, for driving the real pipeline over real HTTP.

Fake mode (`LLM_MODE=fake`) never builds a provider client, so it cannot exercise the defect
class that lives in one: an SDK's process-wide async HTTP client whose pooled keep-alive
connections belong to the event loop that opened them. This server lets a test run
`LLM_MODE=real` end to end — the real factory, the real `ChatOpenAI` and its cached client,
real HTTP/1.1 keep-alive — with no network, no key and no spend.

Each agent role is routed to its own model name (`custom:planner`, `custom:executor`, …), so
the request's `model` field says who is asking. Answers come from the same scripts fake mode
uses (`research_engine.fakes`), with one exception: the executor. Real mode verifies every
submitted snippet against text a tool actually returned, so a scripted executor that submits
from memory — as fake mode's does — would have every citation struck. This one researches
the way a real model must: it reads a page through the real tool path, then quotes it.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from research_engine.fakes import fake_model

ROLES = ("planner", "executor", "critic", "synthesizer", "chat")

#: A model message the executor can only quote after reading the page — and the URL it reads.
#: `https://example.com/fixture/<task>` matches the sources fake mode's synthesizer cites.
PAGE_URL = "https://example.com/fixture/{task}"
PAGE_TEXT = "Fixture page {task}. The measured adoption rate was {rate} percent in 2025."
QUOTE = "The measured adoption rate was {rate} percent in 2025."

FAILURE_MESSAGE = "upstream provider unavailable (scripted test failure)"


def page_for(task: int) -> dict:
    """What the fixture `read_webpage` returns for a task's page."""
    return {
        "url": PAGE_URL.format(task=task),
        "title": f"Fixture page {task}",
        "text": PAGE_TEXT.format(task=task, rate=40 + task),
        "error": None,
    }


def _as_langchain(messages: list[dict]) -> list:
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        content = content or ""
        role = m.get("role")
        if role in ("system", "developer"):
            out.append(SystemMessage(content=content))
        elif role == "user":
            out.append(HumanMessage(content=content))
        elif role == "tool":
            out.append(ToolMessage(content=content, tool_call_id=m.get("tool_call_id", "")))
        else:
            out.append(AIMessage(content=content))
    return out


def _task_of(messages: list[dict]) -> int:
    for m in messages:
        if m.get("role") == "user":
            found = re.search(r"Task (\d+):", str(m.get("content") or ""))
            if found:
                return int(found.group(1))
    return 1


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def _evidence(task: int) -> list[dict]:
    return [
        {
            "source_url": PAGE_URL.format(task=task),
            "source_title": f"Fixture page {task}",
            "snippet": QUOTE.format(rate=40 + task),
            "key_fact": f"Adoption was {40 + task} percent in 2025.",
        }
    ]


def scripted_reply(role: str, body: dict) -> dict:
    """The assistant message this role answers `body` with."""
    messages = body.get("messages") or []
    task = _task_of(messages)
    if role == "executor":
        if body.get("response_format"):
            # The forced-submission fallback, asked as structured output.
            return {"role": "assistant", "content": json.dumps({"evidence": _evidence(task)})}
        has_read = any(m.get("role") == "tool" for m in messages)
        forced = (
            (body.get("tool_choice") or {}) if isinstance(body.get("tool_choice"), dict) else {}
        )
        if has_read or (forced.get("function") or {}).get("name") == "submit_evidence":
            return _tool_call("submit_evidence", {"evidence": _evidence(task)}, f"submit-{task}")
        return _tool_call("read_webpage", {"url": PAGE_URL.format(task=task)}, f"read-{task}")
    reply = fake_model(role)._reply(_as_langchain(messages))
    return {"role": "assistant", "content": str(reply.content)}


class FakeProvider:
    """The server, plus what a test needs to know about the traffic it saw.

    `fail_roles` makes requests from those roles fail as a provider would — a 400 with an
    error body, which the SDK raises without retrying, so a test sees one deterministic failure
    rather than a backoff schedule. `fail_tasks` narrows that to the executor's requests for
    those plan tasks, so one research task can fail while its siblings are still working —
    the shape that let a session close collide with a sibling's write. `latency` holds every
    successful reply, to keep those siblings mid-flight.
    """

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.connections = 0
        self.fail_roles: set[str] = set()
        self.fail_tasks: set[int] = set()
        self.latency = 0.0
        self._lock = threading.Lock()
        provider = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                with provider._lock:
                    provider.connections += 1

            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                role = str(body.get("model", ""))
                # Counted on arrival, before responding: counted after, the client could read
                # the reply and a test assert on the count while this thread had not appended.
                task = _task_of(body.get("messages") or [])
                with provider._lock:
                    provider.requests.append(role)
                    failing = role in provider.fail_roles and (
                        not provider.fail_tasks or task in provider.fail_tasks
                    )
                if failing:
                    status = 400
                    payload = {
                        "error": {
                            "message": FAILURE_MESSAGE,
                            "type": "invalid_request_error",
                            "code": "scripted_failure",
                        }
                    }
                else:
                    time.sleep(provider.latency)
                    status = 200
                    message = scripted_reply(role, body)
                    payload = {
                        "id": f"chatcmpl-{len(provider.requests)}",
                        "object": "chat.completion",
                        "created": 0,
                        "model": role,
                        "choices": [
                            {
                                "index": 0,
                                "message": message,
                                "finish_reason": "tool_calls"
                                if message.get("tool_calls")
                                else "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    }
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
