import { SiteFooter, SiteHeader } from "@/components/site/SiteChrome";

/**
 * The public site: landing, positioning, docs, download.
 *
 * A route group rather than a path prefix, so these live at `/`, `/why`, `/docs` and
 * `/download` — the URLs you would actually put in a README — while still sharing one
 * shell. Deliberately outside `(app)`: none of this is behind the login wall, because it
 * is the material someone reads to decide whether to run this at all, and gating that
 * behind an account inverts the order those two decisions happen in.
 */
export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-bg-base">
      <SiteHeader />
      <div className="flex-1">{children}</div>
      <SiteFooter />
    </div>
  );
}
