import { REPOSITORY_URL } from "@/lib/releases";

/** The author's site, linked from the footer byline and named in `llms.txt`. */
export const AUTHOR_URL = "https://adityamhaske.com";
export const AUTHOR_NAME = "Aditya Mhaske";

/** `https://github.com/<owner>` — derived from the repository URL so it cannot disagree. */
const AUTHOR_GITHUB_URL = REPOSITORY_URL.split("/").slice(0, 4).join("/");

/**
 * Person structured data for the public site. `sameAs` lists only profiles this repository
 * already links to; adding one that cannot be verified from here would be an invented claim.
 */
export function personSchema() {
  return {
    "@context": "https://schema.org",
    "@type": "Person",
    "@id": `${AUTHOR_URL}/#person`,
    name: AUTHOR_NAME,
    jobTitle: "Software Engineer",
    url: AUTHOR_URL,
    sameAs: [AUTHOR_GITHUB_URL],
  };
}
