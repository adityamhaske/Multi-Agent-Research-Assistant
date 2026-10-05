"use client";

import Link from "next/link";
import { useState } from "react";
import toast from "react-hot-toast";

import { RolePromptEditor } from "@/components/account/RolePromptEditor";
import { Section } from "@/components/account/Section";
import { ResetToDefault } from "@/components/settings/ResetToDefault";
import { useMe, useModelCatalog, usePromptDefaults, useUpdateProfile } from "@/hooks/queries";
import { ROLE_COPY, roleModelLabel } from "@/lib/agentRoles";
import { ApiError } from "@/lib/api";
import { customisedRoles } from "@/lib/promptOverrides";
import type { AgentRole } from "@/lib/types";

/**
 * Settings → Agents: how each agent behaves (scope freeze §12).
 *
 * Models answers "what model should this role use"; this page answers "how should this
 * agent behave", and the two stay apart. The model a role runs on is shown here read-only,
 * with a link to where it is changed — a second selector would be a second place to change
 * one setting.
 *
 * **The agents are the five public roles, from the API.** The list is whatever
 * `GET /models/prompt-defaults` returns, which is exactly the overridable surface — so a
 * protected purpose cannot appear here, and nothing on this page can create an agent: the
 * pipeline's roles are fixed, and user-defined agents are deferred beyond V3.
 *
 * One editor is open at a time. Five full-length prompts on one page would bury the
 * question each card answers — shipped or customized — under text nobody asked to read.
 */
export function AgentsSection() {
  const { data: me, isLoading: meLoading } = useMe();
  const defaults = usePromptDefaults();
  const { data: catalog } = useModelCatalog();
  const updateProfile = useUpdateProfile();
  const [editing, setEditing] = useState<AgentRole | null>(null);
  const [resetError, setResetError] = useState<{ role: AgentRole; message: string } | null>(
    null,
  );

  const overrides = me?.preferences.prompt_overrides ?? null;
  const customised = new Set(customisedRoles(overrides));

  // `null` is the reset (§12): the API merges per role, so this touches no other agent.
  const write = async (role: AgentRole, text: string | null) => {
    await updateProfile.mutateAsync({ preferences: { prompt_overrides: { [role]: text } } });
  };

  async function reset(role: AgentRole): Promise<boolean> {
    setResetError(null);
    try {
      await write(role, null);
      toast.success(`${ROLE_COPY[role].label} is back on the shipped prompt.`);
      return true;
    } catch (err) {
      setResetError({
        role,
        message: err instanceof ApiError ? err.message : "Could not reach the server.",
      });
      return false;
    }
  }

  const loading = meLoading || defaults.isLoading;

  return (
    <Section title="Agents" description="Customize how your research agents behave.">
      <div className="space-y-5">
        <p className="text-xs leading-relaxed text-text-muted">
          Each agent follows its shipped instructions unless you give it your own. Saved
          instructions apply to research you start afterwards — a run keeps the instructions
          it started with — and follow-up chat uses them straight away. A run&apos;s
          verification bundle records them in full, so anyone you share it with can read
          them. Bundles from this release use format v2, which a verifier from before this
          release refuses: check them with the current one.
        </p>

        {loading && <div className="h-40 animate-pulse border border-border bg-bg-surface" />}

        {!loading && (defaults.isError || !defaults.data || !me) && (
          <p className="text-sm text-text-secondary">
            The agents&apos; shipped instructions could not be loaded, so nothing here can be
            edited right now. Nothing was changed.
          </p>
        )}

        {!loading && defaults.data && me && (
          <ul className="space-y-3" aria-label="Agents">
            {defaults.data.roles.map((shipped) => {
              const role = shipped.role;
              const isCustom = customised.has(role);
              const open = editing === role;
              const model = roleModelLabel(catalog, role);
              const saved =
                typeof overrides?.[role] === "string" ? (overrides[role] as string) : undefined;
              return (
                <li
                  key={role}
                  aria-label={ROLE_COPY[role].label}
                  className="border border-border/60 bg-bg-base/40 p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-sm font-semibold text-text-primary">
                          {ROLE_COPY[role].label}
                        </h3>
                        <span
                          className={`badge font-mono text-[0.625rem] uppercase tracking-wider ${
                            isCustom
                              ? "border-accent/40 bg-accent/10 text-accent"
                              : "border-border text-text-muted"
                          }`}
                        >
                          {isCustom ? "Customized" : "Shipped"}
                        </span>
                      </div>
                      <p className="text-xs leading-relaxed text-text-muted">
                        {ROLE_COPY[role].blurb}
                      </p>
                      <p className="font-mono text-[0.6875rem] text-text-muted">
                        Model: {model ?? "not available"} ·{" "}
                        <Link href="/settings/models" className="text-accent hover:underline">
                          Change in Models
                        </Link>
                      </p>
                    </div>
                    {!open && (
                      <div className="flex items-center gap-3">
                        {isCustom && (
                          <ResetToDefault
                            isDefault={editing !== null || updateProfile.isPending}
                            onReset={() => reset(role)}
                          />
                        )}
                        <button
                          type="button"
                          className="btn btn-secondary"
                          disabled={editing !== null || updateProfile.isPending}
                          onClick={() => {
                            setResetError(null);
                            setEditing(role);
                          }}
                        >
                          {isCustom ? "Edit instructions" : "Customize"}
                        </button>
                      </div>
                    )}
                  </div>
                  {resetError?.role === role && (
                    <p role="alert" className="mt-2 text-xs text-danger">
                      {resetError.message}
                    </p>
                  )}
                  {open && (
                    <div className="mt-4 border-t border-border/40 pt-4">
                      <RolePromptEditor
                        label={ROLE_COPY[role].label}
                        shipped={shipped}
                        maxChars={defaults.data.max_chars}
                        saved={saved}
                        busy={updateProfile.isPending}
                        onSave={(text) => write(role, text)}
                        onClose={() => setEditing(null)}
                        onReset={async () => {
                          // Closed only once the override is really gone; a refusal shows on
                          // the card and leaves the editor, and its text, where they were.
                          if (await reset(role)) setEditing(null);
                        }}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Section>
  );
}
