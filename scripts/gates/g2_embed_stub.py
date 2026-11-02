"""A stand-in for Ollama's embeddings endpoint, for the G-2 webview pass on CI runners.

G-2 checks how each webview hands folders to the app, not what the vectors mean, and a CI
runner has no Ollama. The launched app is pointed here with `OLLAMA_BASE_URL`; every vector
is derived from the text's hash, 768-dimensional like `nomic-embed-text`. The evidence log
says the embeddings came from this stub.

    python scripts/gates/g2_embed_stub.py --port 11434
"""

from __future__ import annotations

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIMENSIONS = 768


def vector(text: str) -> list[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    return [((seed[i % len(seed)] + i) % 255) / 255.0 - 0.5 for i in range(DIMENSIONS)]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 — the stdlib's name
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        texts = body.get("input") or []
        texts = [texts] if isinstance(texts, str) else texts
        payload = {
            "object": "list",
            "model": body.get("model"),
            "data": [
                {"object": "embedding", "index": i, "embedding": vector(t)}
                for i, t in enumerate(texts)
            ],
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=11434)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
