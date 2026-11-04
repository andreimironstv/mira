# Mira branding layer

Mira is a fork of [block/buzz](https://github.com/block/buzz). Upstream ships
about 13 commits a day and mentions "buzz" 40,000 times in 3,000 files, so a full
rename would make every update conflict. Branding is instead a thin layer that
is reapplied after each merge.

## Getting upstream updates

```sh
node rebrand/sync.mjs      # merge upstream/main, reapply branding, commit locally
git push
```

Do not run a plain `git merge upstream/main`: branding conflicts would need
manual resolution, which is exactly what this script removes.

Sync resolves conflicts in favor of upstream, then reapplies the brand. New
upstream strings get branded automatically. If a conflicting file holds a Mira
change other than branding, sync stops before merging and lists the file.

To keep sync painless, put Mira features in new files where possible.

## What is here

| Path | Purpose |
|------|---------|
| `apply.mjs` | Applies the brand. `--check` fails if something is unbranded (runs in CI) |
| `sync.mjs` | Merges upstream and reapplies the brand |
| `overlay/` | Files that replace the upstream file at the same path |
| `brand/` | Source logos: the original PDFs and the SVGs derived from them |
| `tools/generate_assets.py` | Regenerates `overlay/` and `brand/*.svg` from the PDFs |

## Adding a rule

- Rename a string: `IN_SCOPE` in `apply.mjs` controls where the word `Buzz`
  becomes `Mira`. Comments are skipped to keep the diff against upstream small.
- Keep a string: add it to `PROTECTED_LINE`.
- Any other edit: add it to `FILE_RULES`.
- Replace a whole file: add it to `overlay/`, or to the generator if it derives
  from the logo.

Rules must be idempotent: the output of `apply.mjs` must pass `--check`.

## Deliberately still "buzz"

Renaming these adds conflicts without changing what users see, or breaks
compatibility:

- Crate, package and directory names (`buzz-relay`, `package:buzz`)
- Identifiers and asset file names (`BuzzClient`, `buzz-wordmark.png`)
- `BUZZ_*` environment variables, CSS classes, protocol tags and event names
- The `buzz` CLI binary, the `buzz://` deep link scheme and the `.buzz` directory
- Migrations, schema, Helm charts, benchmarks and developer docs

## Not rebranded yet: needs Mira's own values

- **Block-hosted services:** `communities.buzz.xyz`, `push.buzz.xyz` and the
  Builderlab hosted-community flow (`app.builderlab.xyz`) still point at the
  original operators. Move them once `mira-ai.ro` services are deployed.

App IDs are `ro.miraai.mira.app` (desktop) and `ro.miraai.mira.mobile` (mobile). The
Android `namespace` and Kotlin packages keep `xyz.block.buzz.mobile`, which users
never see. The UI keeps the original color palette by decision.
