"""
The canonical application runtime: one implementation of each product operation.

Empty on purpose. The layer is declared before anything moves into it, because a boundary
drawn after the fact is a boundary drawn around whatever the code already does.

What belongs here: plain `async` functions, one per product-visible operation, taking their
collaborators as arguments — a database session, the caller's identity, a port. What does
not: FastAPI (`Depends`, `HTTPException`, `UploadFile`, `StreamingResponse`), the server's
configuration or engine, Celery, Redis, the keychain, or anything under `desktop/`.

Each host wraps these in a thin router. `tests/workflow/test_layer_boundaries.py` enforces
the direction; `app/api/v1/runs.py` is the worked example of the shape, from before the
rule existed.
"""
