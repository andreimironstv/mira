#!/usr/bin/env node
// Merges upstream Buzz into the current branch and reapplies the Mira brand.
//   node rebrand/sync.mjs [upstream-ref]     default: upstream/main
// Commits locally; pushing stays with you.
import { execFileSync, spawnSync } from "node:child_process";
import { overlayFiles, ROOT, transform } from "./apply.mjs";

const UPSTREAM_URL = "https://github.com/block/buzz.git";
const ref = process.argv[2] ?? "upstream/main";
const BUFFER = 1 << 28;

const git = (...args) =>
  execFileSync("git", args, {
    cwd: ROOT,
    encoding: "utf8",
    maxBuffer: BUFFER,
  }).trim();
const fail = (message) => {
  console.error(message);
  process.exit(1);
};

if (git("status", "--porcelain")) {
  fail("Working tree is not clean. Commit first.");
}
if (!git("remote").split("\n").includes("upstream")) {
  git("remote", "add", "upstream", UPSTREAM_URL);
}
git("fetch", "upstream");

const base = git("merge-base", "HEAD", ref);
if (base === git("rev-parse", ref)) {
  console.log("Already up to date with upstream.");
  process.exit(0);
}

// Conflicts on branding are expected and safe to resolve to upstream, because
// apply.mjs puts the branding back. A conflict on a file with any other Mira
// edit is not: resolving it that way would silently drop that edit.
const preview = spawnSync(
  "git",
  ["merge-tree", "--write-tree", "--name-only", "--no-messages", "HEAD", ref],
  { cwd: ROOT, encoding: "utf8", maxBuffer: BUFFER },
);
const conflicted =
  preview.status === 0
    ? []
    : preview.stdout.trim().split("\n").slice(1).filter(Boolean);
const overlaid = new Set(overlayFiles());
const show = (rev, path) => {
  const out = spawnSync("git", ["show", `${rev}:${path}`], {
    cwd: ROOT,
    encoding: "utf8",
    maxBuffer: BUFFER,
  });
  return out.status === 0 ? out.stdout : null;
};
const customized = conflicted.filter((path) => {
  if (overlaid.has(path)) return false;
  const ours = show("HEAD", path);
  const original = show(base, path);
  return (
    ours === null || original === null || ours !== transform(path, original)
  );
});
if (customized.length) {
  fail(
    `These files conflict and contain Mira changes other than branding:\n  ${customized.join("\n  ")}\n` +
      `Nothing was merged. Resolve with: git merge ${ref}, then node rebrand/apply.mjs`,
  );
}

const merge = spawnSync(
  "git",
  ["merge", "-X", "theirs", "--no-commit", "--no-ff", ref],
  { cwd: ROOT, encoding: "utf8" },
);
if (git("ls-files", "--unmerged")) {
  fail(
    `Merge needs a manual decision (for example, upstream deleted a file):\n${merge.stdout}`,
  );
}
execFileSync(process.execPath, ["rebrand/apply.mjs"], {
  cwd: ROOT,
  stdio: "inherit",
});
git("add", "-A");
const short = git("rev-parse", "--short", ref);
git("commit", "-m", `chore: sync upstream ${short} and reapply Mira branding`);
execFileSync(process.execPath, ["rebrand/apply.mjs", "--check"], {
  cwd: ROOT,
  stdio: "inherit",
});
console.log(
  `Synced to ${short}; ${conflicted.length} branding conflicts resolved. Review and push.`,
);
