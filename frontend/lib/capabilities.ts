/**
 * What the host we are talking to can do.
 *
 * The app used to decide this by reading `isDesktop` — a build-time flag inlined by
 * `NEXT_PUBLIC_DESKTOP`. That works, and it is the wrong question: it asks *which build am
 * I* in order to answer *what can the product do*. Every new capability difference then
 * becomes another branch on the build flag, and a branch is where two hosts drift.
 *
 * `GET /api/v1/capabilities` answers the real question, and both hosts serve it at the
 * same path. `isDesktop` stays for what it is genuinely about — transport: cookies vs a
 * bearer token, a dynamic route vs a static export, `withCredentials` on an EventSource.
 * Those are properties of the build. What a person can do is not.
 */

export interface Capabilities {
  /** User accounts: registration, login, a profile, per-account spend limits. */
  accounts: boolean;
  /** Retrieval over previously approved reports in this project. pgvector-backed. */
  project_memory: boolean;
  /** Chat scoped to a whole project, citing every approved report in it. */
  project_chat: boolean;
  /** Server-rendered PDF export. The desktop prints through the WebView instead. */
  server_pdf: boolean;
  /** Whether this host enforces request rate limits. */
  rate_limits: boolean;
  /** Starting and stopping a local Ollama process. */
  local_llm_control: boolean;
  /** Where a provider key is kept. Both hosts store keys; the difference is where. */
  byok_storage: "encrypted_column" | "os_keychain";
  /** Which host answered. For support conversations — never branch on it. */
  host: "server" | "desktop";
}

/**
 * What to assume before the answer arrives.
 *
 * Everything off. A capability shown and then withdrawn is worse than one that appears a
 * moment late: the first offers a control that fails, the second only delays it. The
 * exception is `byok_storage`, which is not a permission — every host stores keys
 * somewhere, and the settings copy has to say which without waiting.
 */
export const UNKNOWN_CAPABILITIES: Capabilities = {
  accounts: false,
  project_memory: false,
  project_chat: false,
  server_pdf: false,
  rate_limits: false,
  local_llm_control: false,
  byok_storage: "encrypted_column",
  host: "server",
};
