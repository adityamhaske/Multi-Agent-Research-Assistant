# Release audit evidence

One directory per release, holding what [`RELEASE.md`](../RELEASE.md) requires be recorded:

```text
release-audit/
  TEMPLATE.md                    copied to vX.Y.Z/record.md at the start of a release (M0.01)
  historical-references.json     every reviewed version mention in user-facing text (A1.09)
  compose.published-images.yml   runs the published images on their own volumes (Phase 10)
  vX.Y.Z/
    record.md                    scope, manual results, dispositions, sign-off — a working document
    pre-tag.json                 scripts/release_audit.py output, one file per stage —
    published.json                 write-once evidence, like backend/evals/results/
    post-release.json              (CI's eval-artifacts job fails on a modified one)
```

**A JSON file is a measurement, and measurements are never edited.** A re-run of a stage after
a fix is a new file (`published-2.json`), and the record says which one the sign-off rests on.
Large logs are not committed: the JSON carries each check's verdict and the evidence it used
(run URLs, digests, hashes, commit SHAs), which is enough for a reader to re-check the claim.

`record.md` is where a person writes what a machine cannot see — the scope decision, the
manual platform checks, the disposition of every WARN and UNAVAILABLE, and the sign-off.
`A21.01` fails the post-release audit while any manual check in `RELEASE.md` has no row.
