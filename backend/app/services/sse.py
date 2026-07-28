"""
Shared response headers for Server-Sent Events endpoints.

`no-transform` is load-bearing, not decoration. Any compressing intermediary —
Next.js's built-in gzip (`compress: true`, the default), nginx's gzip module, a
CDN — will buffer a `text/event-stream` body while it fills a compression
window. The response headers arrive immediately, so the client sees a healthy
open connection and simply never receives events: the live monitor sits on
"Waiting for the pipeline to start…" forever while the pipeline runs normally.

`Cache-Control: no-transform` is the HTTP-standard instruction not to alter the
payload, and both the `compression` middleware Next uses and nginx honor it, so
one header fixes every layer rather than disabling compression app-wide.

`X-Accel-Buffering: no` covers nginx's proxy buffering specifically (docs/09 §5).
"""

SSE_HEADERS: dict[str, str] = {
    # no-transform stops proxies gzipping (and therefore buffering) the stream.
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
