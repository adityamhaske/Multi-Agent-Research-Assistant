import { DocsSidebar } from "@/components/docs/DocsSidebar";
import { docCategories } from "@/lib/docs";

/**
 * Documentation shell — sidebar and content only.
 *
 * The header, footer and theme toggle this used to render itself now come from
 * `app/(site)/layout.tsx`, which wraps every public page. Keeping its own copy would have
 * stacked two identical headers the moment docs moved into the site group, and would have
 * left the docs section as the one place where the site nav did not appear.
 */
export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const categories = docCategories();

  return (
    <div className="mx-auto flex w-full max-w-7xl gap-8 px-4 py-8 sm:px-6">
      <aside className="hidden w-56 shrink-0 lg:block">
        {/* Sticky under the 3.5rem site header so navigation stays reachable in a long doc. */}
        <div className="sticky top-[4.5rem] max-h-[calc(100vh-6rem)]">
          <DocsSidebar categories={categories} />
        </div>
      </aside>

      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
