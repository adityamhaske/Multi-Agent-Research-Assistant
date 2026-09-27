import type { RunVerification } from "@/lib/types";

/**
 * What the artifact panel says about the prompts a run ran under, beside the verifier's
 * verdict — the in-app counterpart of what `research_engine.verify_bundle` prints (scope
 * freeze §10, D-3).
 *
 * **Only what the run recorded.** Everything here comes from the run's own bundle, via the
 * verification endpoint; nothing reads the user's current settings, so a run is never
 * described by instructions saved after it. A v1 bundle recorded no prompts, and says
 * nothing rather than something inferred.
 *
 * **Hashes, never text.** The endpoint does not return prompt text and this does not ask for
 * it: the full prompts are in the bundle, for whoever downloads it.
 */

export interface ReplacedPrompt {
  /** A role label ("Critic"), never an internal purpose name. */
  role: string;
  hash: string;
}

export interface ProvenanceNotice {
  /** Purposes the run's owner replaced. Empty when every recorded prompt was shipped. */
  replaced: ReplacedPrompt[];
  /** Overrides were configured but unusable, so the run fell back to its shipped prompts. */
  unusable: boolean;
}

function roleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

export function provenanceNotice(verification: RunVerification | undefined): ProvenanceNotice {
  if (!verification?.assembled) return { replaced: [], unusable: false };
  const replaced = (verification.prompt_provenance ?? [])
    .filter((entry) => entry.overridden)
    .map((entry) => ({ role: roleLabel(entry.role), hash: entry.effective_prompt_sha256 }));
  return { replaced, unusable: verification.prompt_overrides_status === "UNUSABLE" };
}
