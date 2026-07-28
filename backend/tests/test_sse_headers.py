"""
Regression: SSE responses must forbid transforming proxies.

Found in the browser, not in tests: the live monitor sat on "Waiting for the
pipeline to start…" while the pipeline ran normally. Response headers arrived,
the EventSource reported an open connection, and zero events were delivered —
because Next.js's default gzip compression buffers a text/event-stream body
while filling its compression window.

`Cache-Control: no-transform` is what makes compressing intermediaries (the
`compression` middleware Next uses, nginx, CDNs) leave the stream alone. Losing
that header silently breaks live streaming everywhere, so assert it here.
"""

from app.services.sse import SSE_HEADERS


def test_sse_headers_forbid_transformation():
    cache_control = SSE_HEADERS["Cache-Control"]
    assert "no-transform" in cache_control, (
        "SSE must send Cache-Control: no-transform or gzip proxies buffer the "
        "stream and no events ever reach the browser."
    )


def test_sse_headers_disable_caching():
    assert "no-cache" in SSE_HEADERS["Cache-Control"]


def test_sse_headers_disable_nginx_buffering():
    # docs/09 §5: nginx buffers proxied responses unless told otherwise.
    assert SSE_HEADERS["X-Accel-Buffering"] == "no"


def test_stream_endpoints_use_the_shared_headers():
    """Both SSE endpoints must use SSE_HEADERS, not a local dict that can drift."""
    from pathlib import Path

    for module in ("app/api/v1/research.py", "app/api/v1/chat.py"):
        source = Path(module).read_text()
        assert "headers=SSE_HEADERS" in source, f"{module} should stream with SSE_HEADERS"
