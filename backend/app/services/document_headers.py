"""
Response policy for serving one stored corpus document.

**Why this is its own module, and not part of the corpus route.** Both hosts serve the
same document-download contract — `app/api/v1/corpus.py` on the server and
`desktop/sidecar.py` on the desktop — and a second copy of a security header policy is
the worst kind of duplication this repo has. It used to live in the route module and the
sidecar imported it from there, which was one home but the wrong one: importing the route
drags in `app.adapters` → `app.config`, and the desktop host has no `DATABASE_URL` or
`JWT_SECRET_KEY` to build `Settings` with. The packaged sidecar therefore died at import
before serving a single request (#50).

So this module is deliberately **stdlib-only**. Nothing here may import `app.config`,
`app.db`, or anything that reaches them, or the desktop build breaks again in exactly the
way `tests/test_sidecar_startup.py` now exists to prevent.

Same shape as `app/services/sse.py`: a shared header policy with the reasoning attached.
"""

from __future__ import annotations

#: Content-Type per stored kind. Derived from `kind` rather than echoed from the upload —
#: a client-supplied type is attacker-controlled, and reflecting it invites content
#: sniffing on a file another user uploaded.
_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "md": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    # Honest about what the bytes are, so a downloaded file opens correctly. Safe only
    # because it is never served inline — see `download_headers`.
    "html": "text/html; charset=utf-8",
}


def media_type_for(kind: str) -> str:
    return _MEDIA_TYPES.get(kind, "application/octet-stream")


def download_headers(kind: str, filename: str) -> dict[str, str]:
    """Response headers for one stored document (docs/07 §2, Phase 6).

    This route used to be unconditionally `attachment`, on the stated principle that an
    uploaded document must never render inline in this origin. That principle is
    unchanged for every type except one.

    **PDF is inline; nothing else is.** In-place preview needs the browser to render the
    file, and PDF is the only format where "render" does not mean "execute a document in
    our origin": `application/pdf` with `nosniff` is handed to the browser's own viewer,
    which has its own sandbox. Markdown, text and HTML are previewed without this route
    at all — the client `fetch`es the bytes and renders them itself, and `fetch` ignores
    `Content-Disposition` entirely, so keeping `attachment` on them costs the preview
    nothing and keeps an uploaded `.html` from ever being navigated to and executed here.

    The CSP differs with it. PDF must be framable by our own preview (`frame-ancestors
    'self'`, and an explicit `X-Frame-Options` because the security middleware's
    `setdefault` would otherwise apply `DENY`). Everything else keeps `'none'` and adds
    `sandbox`, which gives even a directly-navigated response an opaque origin with no
    scripts — braces to `attachment`'s belt.
    """
    # The filename came from an upload: a raw newline or quote here would let a crafted
    # name inject extra response headers.
    safe_name = filename.replace("\\", "_").replace('"', "_").replace("\n", "_").replace("\r", "_")
    if kind == "pdf":
        return {
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; frame-ancestors 'self'; base-uri 'none'"
            ),
            "X-Frame-Options": "SAMEORIGIN",
        }
    return {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; sandbox"
        ),
    }
