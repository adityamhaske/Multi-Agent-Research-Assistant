import Link from "next/link";

/**
 * The full-width warning a demo carries wherever someone reads its report (docs/17 §6.2).
 *
 * A badge marks a demo in a list; beside the report it is not enough. The demo report
 * answers a fixed question whatever was asked, fully cited, so a reader who skims past
 * two words reads an unrelated, confident answer as research on their own question. This
 * says first that the question never reached a model.
 *
 * One component for runs and sessions, so the two cannot drift into saying different
 * things. It does not send people to Settings as the whole fix: when the *server* runs in
 * demo mode every run is a demo, and a key saved in Settings is never used.
 */
export function DemoNotice() {
  return (
    <div
      role="note"
      aria-label="Demo run"
      className="border px-4 py-3"
      style={{
        borderColor: "color-mix(in srgb, var(--warning) 35%, var(--border))",
        backgroundColor: "color-mix(in srgb, var(--warning) 8%, var(--bg-surface))",
      }}
    >
      <p
        className="font-mono text-xs font-semibold uppercase tracking-wider"
        style={{ color: "var(--warning)" }}
      >
        ⚠ Demo run — no LLM research was performed
      </p>
      <p className="mt-1 text-sm leading-relaxed text-text-secondary">
        Your question was not sent to a model. This report is a scripted demonstration — fixed
        content from scripted models and fixture sources, shown so the pipeline can be tried
        without an API key — and it does not answer what you asked. Exports are stamped. To
        research for real, connect a model in{" "}
        <Link href="/settings" className="text-accent hover:underline">
          Settings
        </Link>
        ; if every run comes back as a demo, the server itself is running in demo mode and
        needs a provider configured.
      </p>
    </div>
  );
}
