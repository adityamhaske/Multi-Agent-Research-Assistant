"use client";

import Link from "next/link";
import { useState, useSyncExternalStore } from "react";

import { RELEASES, latestRelease } from "@/lib/releases";

/**
 * Download and install (docs/17 §7).
 *
 * A real route rather than a docs page, because the one thing that matters here — showing
 * *your* operating system's unblock steps without making you hunt for them — needs to know
 * what you are running.
 *
 * The builds are unsigned, and this page says so before you download rather than letting
 * the OS say it after. An unexplained "Apple could not verify this app" reads as "this is
 * broken"; the same warning with a reason beside it reads as "this is unsigned", which is
 * the truth.
 */

const REPO = "https://github.com/adityamhaske/Multi-Agent-Research-Assistant";

// Desktop bundles started shipping in v1.0.1. Derived from `lib/releases.ts` so the
// version lives in exactly one place: the releases page and this button cannot disagree
// about what "latest" means.
const DESKTOP_VERSIONS = RELEASES.filter(
  (r) => !r.unreleased && r.version !== "v1.0.0",
).map((r) => r.version.replace(/^v/, ""));

const LATEST_VERSION =
  DESKTOP_VERSIONS[0] ??
  (latestRelease()?.version ?? "v2.0.2").replace(/^v/, "");

/**
 * Direct installer URLs for a tagged release.
 *
 * Verified against the assets actually attached to the release rather than guessed from a
 * naming convention — a download button that 404s is worse than one that sends you to a
 * list, because it looks like the product is broken rather than like a link is stale.
 *
 * The bundler names files after productName ("Research Assistant_1.0.2_…") and GitHub
 * rewrites the space to a dot when serving them; these are the served names. A prior
 * revision of this page had it right and lost it to an over-broad "use internal routes"
 * refactor that swept up this *external* GitHub asset link along with the internal ones —
 * caught by checking the actual button destination, not by reading the diff that broke it.
 */
function assetUrl(os: OS, version: string): string | null {
  if (os === "unknown" || os === "docker") return null;
  const assetName: Record<Exclude<OS, "unknown" | "docker">, string> = {
    macos: `Research.Assistant_${version}_aarch64.dmg`,
    windows: `Research.Assistant_${version}_x64_en-US.msi`,
    linux: `Research.Assistant_${version}_amd64.AppImage`,
  };
  return `${REPO}/releases/download/v${version}/${assetName[os]}`;
}

function linuxDebUrl(version: string): string {
  return `${REPO}/releases/download/v${version}/Research.Assistant_${version}_amd64.deb`;
}

function sourceZipUrl(version: string): string {
  return `${REPO}/archive/refs/tags/v${version}.zip`;
}

type OS = "macos" | "windows" | "linux" | "docker" | "unknown";
type PlatformKey = "macos" | "windows" | "linux" | "docker";

interface Platform {
  key: PlatformKey;
  label: string;
  artifact: string;
  steps: string[];
  severity: "high" | "low" | "none";
  badgeLabel?: string;
  note?: string;
}

const PLATFORMS: Platform[] = [
  {
    key: "macos",
    label: "macOS",
    artifact: ".dmg",
    severity: "high",
    steps: [
      "Open the .dmg and drag the app to Applications.",
      "Double-click it. macOS refuses to open it and says it cannot verify the developer.",
      "Open System Settings → Privacy & Security.",
      'Scroll to Security. A line about the blocked app appears — click "Open Anyway".',
      "Authenticate, then confirm once more. Only needed the first time.",
    ],
    note: "This is the one platform where the friction is real. Apple charges $99/year for the certificate that removes it, and this project does not pay it yet.",
  },
  {
    key: "windows",
    label: "Windows",
    artifact: ".msi",
    severity: "low",
    steps: [
      "Run the .msi installer.",
      'SmartScreen warns that the publisher is unknown. Click "More info".',
      'Click "Run anyway".',
    ],
  },
  {
    key: "linux",
    label: "Linux",
    artifact: ".AppImage / .deb",
    severity: "none",
    steps: [
      "AppImage: make it executable with chmod +x, then run it.",
      "Debian/Ubuntu: install the .deb with your package manager. No warning to clear.",
    ],
  },
  {
    key: "docker",
    label: "Docker / Localhost",
    artifact: "port 3031",
    severity: "none",
    badgeLabel: "Containerized",
    steps: [
      "Clone the repository with git clone https://github.com/adityamhaske/Multi-Agent-Research-Assistant.git or download the source .zip.",
      "Run ./start.sh (or docker compose -f docker-compose.full.yml up --build).",
      "Open http://localhost:3031 — the entire stack runs isolated in containers with zero local dependencies.",
    ],
    note: "Runs the complete stack (FastAPI backend, Celery worker, Next.js frontend, Postgres with pgvector, and Redis) isolated in Docker. Host port 3031.",
  },
];

function detectOS(): OS {
  if (typeof navigator === "undefined") return "unknown";
  const ua = navigator.userAgent;
  // Windows first: several user agents carry more than one of these tokens.
  if (/Windows/i.test(ua)) return "windows";
  if (/Mac OS X|Macintosh/i.test(ua)) return "macos";
  if (/Linux|X11/i.test(ua)) return "linux";
  return "unknown";
}

function SeverityChip({
  severity,
  labelOverride,
}: {
  severity: Platform["severity"];
  labelOverride?: string;
}) {
  const map = {
    high: { label: "Extra steps needed", token: "warning" },
    low: { label: "Two extra clicks", token: "text-muted" },
    none: { label: "No warning", token: "success" },
  } as const;
  const { label, token } = map[severity];
  const activeToken = labelOverride ? "text-muted" : token;
  const c = `var(--${activeToken})`;
  return (
    <span
      className="badge font-mono text-[0.625rem] font-semibold uppercase tracking-wider"
      style={{
        color: c,
        backgroundColor: `color-mix(in srgb, ${c} 10%, var(--bg-surface))`,
        borderColor: `color-mix(in srgb, ${c} 30%, var(--border))`,
      }}
    >
      {labelOverride ?? label}
    </span>
  );
}

function PlatformCard({
  platform,
  primary,
  version,
}: {
  platform: Platform;
  primary: boolean;
  version: string;
}) {
  return (
    <section
      className="flex flex-col justify-between border p-5"
      style={{
        borderColor: primary
          ? "color-mix(in srgb, var(--accent) 35%, var(--border))"
          : "var(--border)",
        backgroundColor: primary
          ? "color-mix(in srgb, var(--accent) 5%, var(--bg-surface))"
          : "var(--bg-surface)",
      }}
      aria-labelledby={`plat-${platform.key}`}
    >
      <div>
        <div className="flex flex-wrap items-center gap-2.5">
          <h2
            id={`plat-${platform.key}`}
            className="font-serif text-lg font-bold text-text-primary"
          >
            {platform.label}
          </h2>
          <code className="font-mono text-xs text-text-muted">
            {platform.artifact}
          </code>
          <SeverityChip
            severity={platform.severity}
            labelOverride={platform.badgeLabel}
          />
        </div>

        <ol className="mt-3 flex list-decimal flex-col gap-1.5 pl-5 text-sm leading-relaxed text-text-secondary">
          {platform.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>

        {platform.note && (
          <p className="mt-3 border-l-2 border-border pl-3 text-xs leading-relaxed text-text-muted">
            {platform.note}
          </p>
        )}
      </div>

      {/* Subtle action buttons at the bottom of the card — no loud or extra colors */}
      <div className="mt-5 flex flex-wrap items-center gap-2.5 border-t border-border pt-4">
        {platform.key === "macos" && (
          <a
            href={assetUrl("macos", version)!}
            className="btn btn-secondary font-mono text-xs"
            download
          >
            Download .dmg · v{version}
          </a>
        )}
        {platform.key === "windows" && (
          <a
            href={assetUrl("windows", version)!}
            className="btn btn-secondary font-mono text-xs"
            download
          >
            Download .msi · v{version}
          </a>
        )}
        {platform.key === "linux" && (
          <>
            <a
              href={assetUrl("linux", version)!}
              className="btn btn-secondary font-mono text-xs"
              download
            >
              Download .AppImage · v{version}
            </a>
            <a
              href={linuxDebUrl(version)}
              className="btn btn-secondary font-mono text-xs"
              download
            >
              Download .deb · v{version}
            </a>
          </>
        )}
        {platform.key === "docker" && (
          <>
            <a
              href={sourceZipUrl(version)}
              className="btn btn-secondary font-mono text-xs"
              download
            >
              Download Source (.zip)
            </a>
            <Link
              href="/docs/deployment/docker"
              className="btn btn-secondary font-mono text-xs"
            >
              Docker Deployment Guide →
            </Link>
          </>
        )}
      </div>
    </section>
  );
}

/** The visitor's OS as an external store.
 *
 *  `useSyncExternalStore`, not `useState` + `useEffect`: deriving state in an effect is
 *  the pattern this codebase avoids everywhere (see `ActiveProject`, and the lint rule
 *  that rejects it). The server snapshot is "unknown" because the server has no user
 *  agent, so the first paint shows every platform rather than flashing the wrong one.
 *  Nothing can change mid-session, so `subscribe` never fires. */
const OS_STORE = {
  subscribe: () => () => {},
  getSnapshot: detectOS,
  getServerSnapshot: (): OS => "unknown",
};

export default function DownloadPage() {
  const os = useSyncExternalStore(
    OS_STORE.subscribe,
    OS_STORE.getSnapshot,
    OS_STORE.getServerSnapshot,
  );

  const [version, setVersion] = useState<string>(LATEST_VERSION);

  const mine = PLATFORMS.find((p) => p.key === os);
  const others = PLATFORMS.filter((p) => p.key !== os);

  return (
    // Header, footer and theme toggle come from `app/(site)/layout.tsx`. This page used to
    // render its own, which would now stack two headers.
    <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
      <h1 className="font-serif text-3xl font-bold tracking-tight text-text-primary">
        Download
      </h1>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
        The desktop app runs the whole pipeline on your machine — no server, no
        login, no Docker. It opens on a demo you can read straight away;
        connecting a model comes after.
      </p>

      {/* Version selector */}
      <div className="mt-5 flex flex-wrap items-center gap-3 border border-border bg-bg-surface p-3">
        <label
          htmlFor="version-select"
          className="font-mono text-xs font-semibold uppercase tracking-wider text-text-secondary"
        >
          Version:
        </label>
        <select
          id="version-select"
          value={version}
          onChange={(e) => setVersion(e.target.value)}
          className="border border-border bg-bg-elevated px-2.5 py-1 font-mono text-xs text-text-primary focus:border-text-primary focus:outline-none"
        >
          {DESKTOP_VERSIONS.map((v) => (
            <option key={v} value={v}>
              v{v} {v === LATEST_VERSION ? "(latest)" : ""}
            </option>
          ))}
        </select>
        <span className="font-mono text-xs text-text-muted">
          Select release version to download across any platform below
        </span>
      </div>

      {/* Said before the download, not left for the OS to say after. */}
      <div
        role="note"
        className="mt-6 border px-4 py-3"
        style={{
          borderColor: "color-mix(in srgb, var(--warning) 35%, var(--border))",
          backgroundColor:
            "color-mix(in srgb, var(--warning) 8%, var(--bg-surface))",
        }}
      >
        <p
          className="font-mono text-xs font-semibold uppercase tracking-wider"
          style={{ color: "var(--warning)" }}
        >
          These builds are not code-signed
        </p>
        <p className="mt-1 text-sm leading-relaxed text-text-secondary">
          Your operating system will warn you the first time you open it. That
          is what unsigned software looks like — not a sign anything is wrong
          with the download. The steps below clear it, and you can verify the
          file against <code className="font-mono text-xs">SHA256SUMS</code>{" "}
          before running anything.
        </p>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        {assetUrl(os, version) ? (
          // Straight at the installer for the OS you are on — an <a>, not <Link>, because
          // this is an external github.com URL, not a route this app owns.
          <a href={assetUrl(os, version)!} className="btn btn-primary" download>
            Download for {PLATFORMS.find((p) => p.key === os)?.label} · v
            {version}
          </a>
        ) : (
          <Link
            href="/releases"
            className="btn btn-primary"
          >
            Get the latest release →
          </Link>
        )}
        <Link
          href="/releases"
          className="font-mono text-xs text-text-muted transition-colors hover:text-text-primary"
        >
          All downloads &amp; checksums →
        </Link>
        {/* Measured on the arm64 build: an 81 MB .dmg that installs to 182 MB. Only
              macOS has actually been built and launched, so only macOS gets a number. */}
        <span className="font-mono text-xs text-text-muted">
          ~80 MB download, ~180 MB installed (macOS) · runs on any laptop from
          the last decade
        </span>
      </div>

      <h2 className="mt-10 font-mono text-xs font-semibold uppercase tracking-wider text-text-secondary">
        {mine ? "Your platform" : "Choose your platform"}
      </h2>
      <div className="mt-3 flex flex-col gap-4">
        {mine && <PlatformCard platform={mine} primary version={version} />}
        {others.map((p) => (
          <PlatformCard key={p.key} platform={p} primary={false} version={version} />
        ))}
      </div>

      <h2 className="mt-10 font-mono text-xs font-semibold uppercase tracking-wider text-text-secondary">
        Verify your download
      </h2>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
        Every release ships a{" "}
        <code className="font-mono text-xs">SHA256SUMS</code> file. Unsigned
        software that also cannot be checked is worse than unsigned software
        that can — this is how you confirm the file is the one CI built.
      </p>
      <pre className="mt-3 overflow-x-auto border border-border bg-bg-elevated p-3 font-mono text-xs text-text-primary">
        sha256sum -c SHA256SUMS --ignore-missing
      </pre>

      <h2 className="mt-10 font-mono text-xs font-semibold uppercase tracking-wider text-text-secondary">
        Would rather not install anything?
      </h2>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
        The whole stack runs in Docker with one command — see{" "}
        <Link
          href="/docs/deployment/docker"
          className="text-accent hover:underline"
        >
          Deployment
        </Link>
        . Or read{" "}
        <Link
          href="/docs/getting-started/overview"
          className="text-accent hover:underline"
        >
          what this is for
        </Link>{" "}
        first.
      </p>
    </main>
  );
}
