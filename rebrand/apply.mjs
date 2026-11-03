#!/usr/bin/env node
// Reapplies the Mira brand on top of the upstream Buzz tree. Idempotent.
//   node rebrand/apply.mjs          apply
//   node rebrand/apply.mjs --check  exit 1 if anything is unbranded
// See rebrand/README.md for what is deliberately left alone.
import { execFileSync } from "node:child_process";
import {
  cpSync,
  existsSync,
  readdirSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OVERLAY = join(ROOT, "rebrand", "overlay");

const IN_SCOPE = [
  /^README\.md$/,
  /^scripts\/.*\.sh$/,
  /^admin-web\/(index\.html|src\/)/,
  /^web\/(index\.html|src\/)/,
  /^desktop\/(index\.html|src\/|tests\/|scripts\/)/,
  /^desktop\/src-tauri\/(src\/|crates\/|tauri[^/]*\.json$|[^/]*\.plist$)/,
  /^mobile\/(lib\/|test\/|integration_test\/|pubspec\.yaml$)/,
  /^mobile\/ios\/(Flutter|Runner|NotificationService|BuzzPushKit\/Sources|RunnerTests)\//,
  /^mobile\/android\/app\/(build\.gradle\.kts$|src\/)/,
  // Rust sources plus markdown compiled into binaries (agent prompts, skills).
  /^crates\/[^/]+\/(src|tests)\//,
  /^\.github\/workflows\/(release|signed-macos-canary)\.yml$/,
];
const OUT_OF_SCOPE = [
  /(^|\/)node_modules\//,
  /\/vendor\//,
  /\/CSecp256k1\//,
  /\.(lock|snap|sql)$/,
  /^crates\/.*\/(README|CHANGELOG)\.md$/,
];
const C_COMMENT = /^\s*(\/\/|\/\*|\*|\{\/\*)/;
const COMMENT_BY_EXT = {
  ts: C_COMMENT,
  tsx: C_COMMENT,
  js: C_COMMENT,
  jsx: C_COMMENT,
  mjs: C_COMMENT,
  cjs: C_COMMENT,
  rs: C_COMMENT,
  dart: C_COMMENT,
  swift: C_COMMENT,
  kt: C_COMMENT,
  kts: C_COMMENT,
  css: C_COMMENT,
  xcconfig: C_COMMENT,
  h: C_COMMENT,
  c: C_COMMENT,
  sh: /^\s*#/,
  yml: /^\s*#/,
  yaml: /^\s*#/,
  py: /^\s*#/,
  html: /^\s*<!--/,
  xml: /^\s*<!--/,
  plist: /^\s*<!--/,
};
// Where the word is an identifier or test input rather than the product name.
const PROTECTED_LINE = [
  /^\s*(@testable\s+)?import\s+Buzz\b/,
  /name_matches\("Buzz/,
  /Based on <a href="https:\/\/github\.com\/block\/buzz">Buzz<\/a>/,
  // Case-insensitive matching fixtures: the query and the name must stay paired.
  /:Buzz:/,
  /"Buzz Platform"/,
];

// `\b` misses the name right after an escaped newline or tab, as in "\nBuzz".
// A host such as "Buzz.Example" is test input, not the name, and "X-Buzz-Live-ID"
// or "Buzz-Chat" is a protocol header or fixture.
const PRODUCT_NAME =
  /(?:(?<=[\x5c][ntr])|(?<!\bX-)\b)Buzz\b(?!-[A-Z]|\.(?!(?:app|exe|dmg|iconset)\b)[A-Za-z])/g;

const markSvg = () =>
  readFileSync(join(ROOT, "rebrand/brand/mira-mark.svg"), "utf8")
    .trim()
    .replace("<svg ", '<svg class="bee" fill="currentColor" ');

// Doc comments here are the --help text clap prints.
const CLI_HELP =
  /^crates\/(buzz-cli\/src\/|buzz-acp\/src\/config\.rs$|buzz-admin\/src\/main\.rs$)/;

// Targeted edits for what the word rule cannot express.
const FILE_RULES = [
  {
    // Lower-cased comparisons against section titles produced by the word rule.
    file: /\.(ts|tsx|mjs|dart)$/,
    from: /(["'])buzz event/g,
    to: (_, quote) => `${quote}mira event`,
  },
  {
    file: /^desktop\/src\/features\/agents\/ui\/agentSessionTranscript\.test\.mjs$/,
    from: /toLowerCase\(\)\.includes\("buzz"\)/g,
    to: () => 'toLowerCase().includes("mira")',
  },
  {
    // A case-insensitive lookup of the renamed fixture "Mira Team".
    file: /^crates\/buzz-cli\/src\/commands\/channel_templates\.rs$/,
    from: /"buzz team"/g,
    to: () => '"mira team"',
  },
  {
    // App identity, the same length as upstream's so no line ever reflows
    // under rustfmt. Also matches the regex-escaped form in shell assertions.
    file: /^(?!mobile\/android\/)/,
    from: /xyz([\x5c]*\.)block\1buzz\1(app|dev\1mobile|mobile)\b/g,
    to: (_, dot, id) => `ro${dot}miraai${dot}mira${dot}${id}`,
  },
  {
    // Android: only the application ID and callback scheme. The `namespace`
    // and Kotlin packages stay, so upstream's source tree needs no moving.
    file: /^mobile\/android\//,
    from: /(?<!namespace = )"xyz\.block\.buzz\.mobile(?=["':])/g,
    to: () => '"ro.miraai.mira.mobile',
  },
  {
    // The theme's label derives from its `buzz` key.
    file: /^mobile\/lib\/shared\/theme\/theme_pairs\.dart$/,
    from: /(String pairedThemeLabel\(String \w+\) \{\n)(?! {2}if \(isBuzzTheme)/,
    to: (_, head) => `${head}  if (isBuzzTheme(lightName)) return 'Mira';\n`,
  },
  {
    // The boot splash shows the static mark, which has no wings to animate.
    file: /^desktop\/tests\/e2e\/boot-splash\.spec\.ts$/,
    from: /  \/\/ The bee is actually animating[\s\S]*?expect\(wingState\)[^\n]*\n\n/,
    to: () => "",
  },
  { file: /^desktop\/scripts\//, from: /\bBuzz(?=_)/g, to: () => "Mira" },
  {
    // Lower-cased comparison against relay/CLI error text renamed by the word rule.
    file: /^desktop\/src\/features\/agents\/ui\/personaModelDiscoveryStatus/,
    from: /\b(no (?:live )?)buzz( shared compute)/g,
    to: (_, a, b) => `${a}mira${b}`,
  },
  {
    file: /^desktop\/src-tauri\/src\/builderlab\.rs$/,
    from: /<svg class="bee"[\s\S]*?<\/svg>/,
    to: markSvg,
  },
  {
    file: /^desktop\/src\/shared\/ui\/buzz-logo\/buzz-logo-animation\.css$/,
    from: /#d7d72e/gi,
    to: () => "#ffffff",
  },
  {
    file: /^desktop\/src\/features\/(sidebar\/ui\/(CommunityRail|SidebarProfileCard)|communities\/ui\/CommunitySwitcher)\.tsx$/,
    from: /🐝/g,
    to: () => "M",
  },
  {
    file: /^desktop\/src\/features\/(onboarding|settings)\/ui\/BackupTestFlow\.tsx$/,
    from: /"🐝", "🍯"/g,
    to: () => '"⭐", "🌟"',
  },
  {
    file: /^README\.md$/,
    from: /<h1 align="center">Mira 🐝<\/h1>/,
    to: () => `<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="rebrand/brand/mira-horizontal-white.svg">
    <img src="rebrand/brand/mira-horizontal-black.svg" alt="Mira" width="320">
  </picture>
</p>

<p align="center"><sub>Based on <a href="https://github.com/block/buzz">Buzz</a> by Block, Inc. See <a href="NOTICE">NOTICE</a>.</sub></p>`,
  },
];

function inScope(path) {
  return (
    IN_SCOPE.some((re) => re.test(path)) &&
    !OUT_OF_SCOPE.some((re) => re.test(path))
  );
}

/** The branded form of a file's text. Pure, so sync can compare it to history. */
export function transform(path, text) {
  if (!inScope(path)) return text;
  const comment = CLI_HELP.test(path)
    ? /^\s*(\/\/(?!\/)|\/\*|\*)/
    : COMMENT_BY_EXT[path.split(".").pop()];
  let out = text;
  if (out.includes("Buzz")) {
    out = out
      .split("\n")
      .map((line) =>
        !line.includes("Buzz") ||
        comment?.test(line) ||
        PROTECTED_LINE.some((re) => re.test(line))
          ? line
          : line.replace(PRODUCT_NAME, "Mira"),
      )
      .join("\n");
  }
  for (const rule of FILE_RULES) {
    if (rule.file.test(path)) out = out.replace(rule.from, rule.to);
  }
  return out;
}

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

export function overlayFiles() {
  if (!existsSync(OVERLAY)) return [];
  return walk(OVERLAY).map((file) =>
    relative(OVERLAY, file).split(sep).join("/"),
  );
}

function run({ check }) {
  const stale = [];
  const overlay = overlayFiles();
  for (const path of overlay) {
    const from = join(OVERLAY, path);
    const to = join(ROOT, path);
    if (existsSync(to) && readFileSync(from).equals(readFileSync(to))) continue;
    stale.push(path);
    if (!check) cpSync(from, to);
  }
  const overlaid = new Set(overlay);
  const tracked = execFileSync("git", ["ls-files", "-z"], {
    cwd: ROOT,
    maxBuffer: 1 << 28,
    encoding: "utf8",
  }).split("\0");
  for (const path of tracked) {
    if (!path || overlaid.has(path) || !inScope(path)) continue;
    const full = join(ROOT, path);
    if (!existsSync(full)) continue;
    const bytes = readFileSync(full);
    if (bytes.includes(0)) continue;
    const text = bytes.toString("utf8");
    if (!Buffer.from(text, "utf8").equals(bytes)) continue;
    const branded = transform(path, text);
    if (branded === text) continue;
    stale.push(path);
    if (!check) writeFileSync(full, branded);
  }
  if (check) {
    for (const path of stale) console.error(`unbranded: ${path}`);
    console.log(
      stale.length
        ? `${stale.length} files need branding`
        : "Branding is up to date",
    );
    process.exit(stale.length ? 1 : 0);
  }
  console.log(`Branded ${stale.length} files`);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  run({ check: process.argv.includes("--check") });
}
