"use client";

import { Section } from "@/components/account/Section";
import { useCapabilities, useUpdateCheck, useVersion } from "@/hooks/queries";


/**
 * What you are running, and whether anything newer exists.
 *
 * The check is a button, never a timer and never on mount: an app that presents itself as
 * local-first and airgap-capable should not reach the network unasked, and the person who
 * wants to know is the one who can press it.
 *
 * **Four states, and three of them are not "up to date".** The backend
 * (`app/services/updates.py`) distinguishes a check that ran from one that could not, and
 * this renders that distinction rather than flattening it — an offline machine is told the
 * check failed, not reassured it is current. Same rule the eval harness follows for a
 * measurement it could not take.
 */
export function AboutSection() {
  const capabilities = useCapabilities();
  const { data: build } = useVersion();
  const check = useUpdateCheck();
  const result = check.data;

  return (
    <>
      <Section title="This build" description="What is installed and running right now.">
        {/* A definition list, not `Field`: these are facts to read, not inputs to edit,
            and `Field` exists to bind a label to a form control. */}
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {[
            {
              term: "Version",
              value: build
                ? build.version + (build.dirty && build.version !== "unknown" ? " (modified)" : "")
                : "…",
            },
            { term: "Commit", value: build ? build.git_sha.slice(0, 9) : "…" },
            { term: "Built", value: build ? build.built_at : "…" },
            { term: "API contract", value: build ? build.contract_version : "…" },
          ].map(({ term, value }) => (
            <div key={term}>
              <dt className="font-mono text-xs font-semibold uppercase tracking-wider text-text-secondary">
                {term}
              </dt>
              <dd className="mt-1 font-mono text-sm text-text-primary">{value}</dd>
            </div>
          ))}
        </dl>
      </Section>

      {capabilities.update_check && (
        <Section
          title="Updates"
          description="Checks GitHub for a newer release. Nothing is sent, and nothing happens automatically."
        >
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => check.mutate()}
              disabled={check.isPending}
            >
              {check.isPending ? "Checking…" : "Check for updates"}
            </button>

            {result?.state === "up_to_date" && (
              <span className="text-sm text-text-secondary">
                You are on the latest release ({result.latest_version}).
              </span>
            )}

            {result?.state === "update_available" && result.release_url && (
              <a
                href={result.release_url}
                className="text-sm font-medium text-accent hover:underline"
              >
                Version {result.latest_version} is available →
              </a>
            )}

            {/* Not folded into the success line: "we could not check" and "you are
                current" are different facts, and only one of them is reassuring. */}
            {result?.state === "check_failed" && (
              <span className="text-sm text-warning">
                Could not check for updates. {result.detail}
              </span>
            )}

            {result?.state === "unknown_local_version" && (
              <span className="text-sm text-text-secondary">
                This build did not record its version, so it cannot be compared. The latest
                release is {result.latest_version}.
              </span>
            )}

            {check.isError && !result && (
              <span className="text-sm text-warning">Could not reach the update check.</span>
            )}
          </div>
        </Section>
      )}
    </>
  );
}

