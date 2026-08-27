"""
Host ports: the interfaces whose implementations differ per host.

Empty on purpose, like `app/handlers/`. Ports arrive in plan Phase 5, one at a time, each
with both implementations and a stated contract — lifecycle, error semantics, transaction
semantics, concurrency, and how it is tested.

**A port is only justified where the infrastructure genuinely differs.**
`research_engine/ports.py` already argues two candidates down to data (`KeyProvider`) and
to host scheduling (`RunLock`), and that reasoning applies here: persistence is one ORM on
both hosts, so a repository layer over it would be indirection, not a boundary. What does
differ is the event stream, the way a `RunConfig` is built, where secrets live, where a
corpus file is, where routing is stored, and whether project memory exists at all.

Protocols only. Nothing here may import an implementation, on either host.
"""
