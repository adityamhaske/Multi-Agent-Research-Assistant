import Link from "next/link";

export const metadata = {
  title: "License · Research Assistant",
  description: "MIT License terms, copyright notice, and verification pledge.",
};

export default function LicensePage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
      <header>
        <p className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
          Legal &amp; Open Source
        </p>
        <h1 className="mt-3 font-serif text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
          MIT License
        </h1>
        <p className="mt-4 text-base leading-relaxed text-text-secondary">
          The Multi-Agent Research Assistant is free, open-source software licensed under the MIT
          License. You are free to run, inspect, modify, and self-host this software for personal,
          academic, or commercial use.
        </p>
      </header>

      <section className="mt-8 border border-border bg-bg-surface p-6 font-mono text-xs leading-relaxed text-text-primary">
        <p className="font-semibold text-text-primary">MIT License</p>
        <p className="mt-3 text-text-secondary">Copyright (c) 2026 Aditya Mhaske</p>
        <p className="mt-4 text-text-secondary">
          Permission is hereby granted, free of charge, to any person obtaining a copy of this
          software and associated documentation files (the &ldquo;Software&rdquo;), to deal in the
          Software without restriction, including without limitation the rights to use, copy,
          modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
          permit persons to whom the Software is furnished to do so, subject to the following
          conditions:
        </p>
        <p className="mt-4 text-text-secondary">
          The above copyright notice and this permission notice shall be included in all copies or
          substantial portions of the Software.
        </p>
        <p className="mt-4 uppercase text-text-muted">
          THE SOFTWARE IS PROVIDED &ldquo;AS IS&rdquo;, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
          IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
          PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
          HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
          CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR
          THE USE OR OTHER DEALINGS IN THE SOFTWARE.
        </p>
      </section>

      <section className="mt-12 space-y-6">
        <h2 className="font-serif text-xl font-bold tracking-tight text-text-primary">
          Openness &amp; Verifiability
        </h2>
        <p className="text-sm leading-relaxed text-text-secondary">
          The verification guarantees of this assistant — citation fidelity, reproducible
          evaluations, airgapped local corpus privacy, and strict provenance — depend entirely on the
          code being fully inspectable and auditable.
        </p>
        <div className="flex flex-wrap gap-4 pt-2">
          <Link
            href="/source"
            className="btn btn-primary"
          >
            Inspect architecture &amp; source →
          </Link>
          <Link
            href="/docs"
            className="flex h-9 items-center border border-border bg-bg-surface px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Read documentation →
          </Link>
        </div>
      </section>
    </main>
  );
}
