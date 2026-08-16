/**
 * Whether the session monitor should hold an SSE connection for a session in `status`.
 *
 * Yes for every loaded session, including finished ones — which is the whole point.
 * The stream is the only path by which the UI ever sees `agent_logs`: the backend
 * replays them on connect before tailing Redis (see the stream endpoint in
 * `app/api/v1/research.py`), and no other query in the app reads them. Gating this on
 * RUNNING therefore did not merely skip live updates, it discarded the run's history —
 * a session that finished before its page loaded showed "Waiting for the pipeline to
 * start…" permanently, with an empty pipeline rail beside it.
 *
 * That is also why the golden E2E was flaky rather than simply broken: a fake-mode run
 * reaches the gate in ~0.67s, so whether the feed populated depended on the page winning
 * a race against the pipeline.
 *
 * The connection is cheap for a finished run: the backend ends the response after the
 * replay for COMPLETED/FAILED, and the client closes itself on the terminal event.
 */
export function shouldOpenStream(status?: string | null): boolean {
  return Boolean(status);
}
