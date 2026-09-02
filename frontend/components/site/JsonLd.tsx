/**
 * Structured-data `<script>` tag, deliberately not built with React's raw-HTML-injection
 * prop — CI greps this tree for that prop's name outright and cannot tell a safe use from
 * an unsafe one (AGENTS.md, "the guards cannot tell a use from a mention"), so even a
 * correct use here would fail the build the same as a real XSS sink would. React renders a
 * `<script>` child as a plain text node instead, which is all `application/ld+json` needs:
 * the browser never parses it as markup, only `JSON.parse`s it, so there is no injection
 * surface to guard against here the way there is for the report renderer (docs/06 §5).
 *
 * `<` is escaped so a value containing the literal text "close-script-tag" cannot terminate
 * the tag early. The payloads passed to this component are this codebase's own static
 * strings today, not user input, but the escape is one line and removes the question
 * entirely.
 */
export function JsonLd({ data }: { data: object }) {
  const json = JSON.stringify(data).replace(/</g, "\\u003c");
  return <script type="application/ld+json">{json}</script>;
}
