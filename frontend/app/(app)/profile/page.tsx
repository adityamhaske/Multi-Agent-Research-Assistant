"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import { AccountShell } from "@/components/account/AccountShell";
import { Field, ReadOnlyRow, Section } from "@/components/account/Section";
import { useChangePassword, useMe, useUpdateProfile } from "@/hooks/queries";
import { ApiError } from "@/lib/api";

const MIN_PASSWORD = 12;

export default function ProfilePage() {
  const { data: user, isLoading } = useMe();
  const updateProfile = useUpdateProfile();
  const changePassword = useChangePassword();

  const [name, setName] = useState("");
  const [copied, setCopied] = useState(false);

  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");

  // Seed from the server copy; re-seed if it changes (React's adjust-state-on-prop-change).
  const [seeded, setSeeded] = useState<string | null>(null);
  const seedKey = user ? `${user.id}|${user.display_name}` : null;
  if (user && seedKey !== seeded) {
    setSeeded(seedKey);
    setName(user.display_name ?? "");
  }

  if (isLoading || !user) {
    return (
      <AccountShell title="Profile" description="How you appear across the app.">
        <div className="card h-48 animate-pulse" aria-hidden />
        <div className="card h-56 animate-pulse" aria-hidden />
      </AccountShell>
    );
  }

  const dirty = name !== (user.display_name ?? "");

  const saveProfile = async () => {
    try {
      await updateProfile.mutateAsync({ display_name: name.trim(), avatar_url: user.avatar_url ?? "" });
      toast.success("Profile updated.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save your profile.");
    }
  };

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(user.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't access the clipboard.");
    }
  };

  const pwMismatch = confirmPw.length > 0 && newPw !== confirmPw;
  const pwTooShort = newPw.length > 0 && newPw.length < MIN_PASSWORD;
  const canChangePw =
    currentPw.length > 0 && newPw.length >= MIN_PASSWORD && newPw === confirmPw && !changePassword.isPending;

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canChangePw) return;
    try {
      await changePassword.mutateAsync({ current_password: currentPw, new_password: newPw });
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
      toast.success("Password updated. Other devices have been signed out.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not change your password.");
    }
  };

  return (
    <AccountShell title="Profile" description="How you appear across the app.">
      {/* ── Identity ─────────────────────────────────────────────────────── */}
      <Section
        title="Your details"
        description="Your name appears in the top bar and on your sessions."
        footer={
          <>
            <span className="text-xs text-text-muted">
              {dirty ? "You have unsaved changes." : "All changes saved."}
            </span>
            <button
              type="button"
              onClick={saveProfile}
              disabled={!dirty || updateProfile.isPending}
              className="btn btn-primary"
            >
              {updateProfile.isPending && <span className="spinner" />}
              Save changes
            </button>
          </>
        }
      >
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1 space-y-4">
            <Field
              label="Display name"
              htmlFor="name"
              hint="Shown in the top bar."
            >
              <input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value.slice(0, 80))}
                placeholder="Your name"
                className="input-base"
              />
            </Field>
          </div>
        </div>
      </Section>

      {/* ── Account facts ────────────────────────────────────────────────── */}
      <Section title="Account" description="Identifiers tied to this account.">
        <div className="divide-y divide-border">
          <ReadOnlyRow label="Email" value={user.email} />
          <ReadOnlyRow
            label="User ID"
            value={<code className="font-mono text-xs text-text-muted">{user.id}</code>}
            action={
              <button type="button" onClick={copyId} className="btn btn-secondary shrink-0">
                {copied ? "Copied" : "Copy"}
              </button>
            }
          />
          <ReadOnlyRow
            label="Member since"
            value={new Date(user.created_at).toLocaleDateString(undefined, {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
          />
        </div>
      </Section>

      {/* ── Password ─────────────────────────────────────────────────────── */}
      <form onSubmit={submitPassword}>
        <Section
          title="Password"
          description="Changing your password signs out every other device."
          footer={
            <>
              <span className="text-xs text-text-muted">
                At least {MIN_PASSWORD} characters.
              </span>
              <button type="submit" disabled={!canChangePw} className="btn btn-primary">
                {changePassword.isPending && <span className="spinner" />}
                Update password
              </button>
            </>
          }
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Current password" htmlFor="current-pw" className="sm:col-span-2">
              <input
                id="current-pw"
                type="password"
                autoComplete="current-password"
                value={currentPw}
                onChange={(e) => setCurrentPw(e.target.value)}
                className="input-base"
              />
            </Field>

            <Field
              label="New password"
              htmlFor="new-pw"
              hint={pwTooShort ? <span style={{ color: "var(--warning)" }}>Too short.</span> : undefined}
            >
              <input
                id="new-pw"
                type="password"
                autoComplete="new-password"
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                className="input-base"
              />
            </Field>

            <Field
              label="Confirm new password"
              htmlFor="confirm-pw"
              hint={
                pwMismatch ? (
                  <span style={{ color: "var(--danger)" }}>Passwords don&apos;t match.</span>
                ) : undefined
              }
            >
              <input
                id="confirm-pw"
                type="password"
                autoComplete="new-password"
                value={confirmPw}
                onChange={(e) => setConfirmPw(e.target.value)}
                className="input-base"
              />
            </Field>
          </div>
        </Section>
      </form>
    </AccountShell>
  );
}
