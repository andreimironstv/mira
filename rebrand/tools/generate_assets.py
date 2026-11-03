#!/usr/bin/env python3
"""Generate rebrand/overlay/ artwork from the Mira logo PDFs.

Run only when the logo changes: python rebrand/tools/generate_assets.py
Requires PyMuPDF and Pillow. Icon dimensions, corner masks and placement are
read from the upstream file being replaced, so every slot keeps its layout.
"""
import io
import re
import struct
import subprocess
import zlib
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "rebrand/brand"
OVERLAY = ROOT / "rebrand/overlay"
BASE_REF = "origin/main"
ICONS = "desktop/src-tauri/icons"


def git_bytes(path):
    return subprocess.run(
        ["git", "show", f"{BASE_REF}:{path}"], cwd=ROOT, capture_output=True, check=True
    ).stdout


def tracked(*prefixes):
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", BASE_REF, *prefixes],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return out.splitlines()


def write(path, data):
    target = OVERLAY / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode()
    target.write_bytes(data)


def load_subpaths():
    """Return subpaths as lists of (op, points) in SVG (y-down) coordinates."""
    pdf = (BRAND / "mira-horizontal-black.pdf").read_bytes()
    stream = zlib.decompress(re.search(rb"stream\r?\n(.*?)endstream", pdf, re.S).group(1))
    tokens = stream.decode().split()
    height = 208.0
    subpaths, current, stack = [], [], []
    start = tokens.index("rg") + 1  # skip the q/cm/rg preamble
    for token in tokens[start:]:
        if re.fullmatch(r"-?\d*\.?\d+", token):
            stack.append(float(token))
            continue
        points = [(stack[i], height - stack[i + 1]) for i in range(0, len(stack) - 1, 2)]
        stack = []
        if token == "m":
            current = [("M", points)]
        elif token in ("l", "c"):
            current.append((token.upper(), points))
        elif token == "h":
            subpaths.append(current)
    return subpaths


def bbox(subpaths):
    xs = [p[0] for sub in subpaths for _, pts in sub for p in pts]
    ys = [p[1] for sub in subpaths for _, pts in sub for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def path_d(subpaths, dx=0.0, dy=0.0):
    def fmt(value):
        return f"{value:.1f}".rstrip("0").rstrip(".")

    parts = []
    for sub in subpaths:
        for op, pts in sub:
            parts.append(op + " ".join(f"{fmt(x - dx)} {fmt(y - dy)}" for x, y in pts))
        parts.append("Z")
    return "".join(parts)


SUBPATHS = load_subpaths()
MARK = [s for s in SUBPATHS if bbox([s])[2] < 400]
x0, y0, x1, y1 = bbox(MARK)
MARK_D = path_d(MARK, x0, y0)
MARK_W, MARK_H = round(x1 - x0, 1), round(y1 - y0, 1)
LOGO_X0, LOGO_Y0, LOGO_X1, LOGO_Y1 = bbox(SUBPATHS)
LOGO_D = path_d(SUBPATHS, LOGO_X0, LOGO_Y0)
LOGO_W, LOGO_H = round(LOGO_X1 - LOGO_X0, 1), round(LOGO_Y1 - LOGO_Y0, 1)


def render_mask(subpaths, width):
    """Rasterize vector paths from the PDF into an L mask `width` pixels wide."""
    a, b, c, d = bbox(subpaths)
    doc = fitz.open(BRAND / "mira-horizontal-black.pdf")
    zoom = width / (c - a)
    pix = doc[0].get_pixmap(
        matrix=fitz.Matrix(zoom, zoom), clip=fitz.Rect(a, b, c, d), alpha=True
    )
    return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples).getchannel("A")


def paint(canvas, mask, color, box):
    """Paste mask, contained and centred in box, onto canvas in color."""
    bx0, by0, bx1, by1 = box
    scale = min((bx1 - bx0) / mask.width, (by1 - by0) / mask.height)
    size = (max(1, round(mask.width * scale)), max(1, round(mask.height * scale)))
    fitted = mask.resize(size, Image.Resampling.LANCZOS)
    pos = (round((bx0 + bx1 - size[0]) / 2), round((by0 + by1 - size[1]) / 2))
    canvas.paste(Image.new("RGBA", size, color), pos, fitted)


HIRES_MARK = render_mask(MARK, 2400)
HIRES_LOGO = render_mask(SUBPATHS, 3200)
WHITE, BLACK = (255, 255, 255, 255), (0, 0, 0, 255)


def tile(size):
    """Full-bleed app tile: white mark centred on black."""
    canvas = Image.new("RGBA", (size, size), BLACK)
    pad = size * 0.2
    paint(canvas, HIRES_MARK, WHITE, (pad, pad, size - pad, size - pad))
    return canvas


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def replace_png(path):
    old = Image.open(io.BytesIO(git_bytes(path)))
    original_mode = old.mode
    old = old.convert("RGBA")
    w, h = old.size
    if re.search(r"foreground|launch|LaunchImage|buzz-icon", path, re.I):
        # Transparent slots: fit the mark to the area the old artwork occupied.
        canvas = Image.new("RGBA", old.size, (0, 0, 0, 0))
        paint(canvas, HIRES_MARK, WHITE, old.getchannel("A").getbbox() or (0, 0, w, h))
    else:
        # Tile slots: reuse the old alpha so rounded/circular masks are kept.
        canvas = tile(max(w, h)).resize((w, h), Image.Resampling.LANCZOS)
        canvas.putalpha(old.getchannel("A"))
    if original_mode == "RGB":
        canvas = canvas.convert("RGB")
    write(path, png_bytes(canvas))


def write_icns():
    """Same geometry as scripts/generate-macos-icon.py, without macOS iconutil."""
    scale = 4
    base = Image.new("RGBA", (1024 * scale, 1024 * scale))
    tile_img = tile(1024).convert("RGBA").resize(
        (824 * scale, 824 * scale), Image.Resampling.LANCZOS
    )
    mask = Image.new("L", tile_img.size)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, tile_img.width - 1, tile_img.height - 1), radius=185 * scale, fill=255
    )
    base.paste(tile_img, (100 * scale, 100 * scale), mask)
    types = [("icp4", 16), ("ic11", 32), ("icp5", 32), ("ic12", 64), ("ic07", 128),
             ("ic13", 256), ("ic08", 256), ("ic14", 512), ("ic09", 512), ("ic10", 1024)]
    body = b""
    for code, size in types:
        data = png_bytes(base.resize((size, size), Image.Resampling.LANCZOS))
        body += code.encode() + struct.pack(">I", len(data) + 8) + data
    write(f"{ICONS}/icon.icns", b"icns" + struct.pack(">I", len(body) + 8) + body)


def write_ico():
    sizes = sorted(Image.open(io.BytesIO(git_bytes(f"{ICONS}/icon.ico"))).info["sizes"])
    buffer = io.BytesIO()
    tile(sizes[-1][0]).save(buffer, "ICO", sizes=sizes)
    write(f"{ICONS}/icon.ico", buffer.getvalue())


def wordmark(path):
    """Horizontal logo in the wordmark's canvas; consumers tint it via alpha."""
    size = Image.open(io.BytesIO(git_bytes(path))).size
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    paint(canvas, HIRES_LOGO, (35, 30, 30, 255), (0, 0, *size))
    write(path, png_bytes(canvas))


def dmg_background():
    path = f"{ICONS}/dmg-background.png"
    w, h = Image.open(io.BytesIO(git_bytes(path))).size
    canvas = Image.new("RGBA", (w, h), (244, 244, 244, 255))
    paint(canvas, HIRES_LOGO, BLACK, (w * 0.3, h * 0.1, w * 0.7, h * 0.3))
    ImageDraw.Draw(canvas).rounded_rectangle(
        (w * 0.083, h * 0.405, w * 0.917, h * 0.935), radius=w * 0.03, fill=WHITE
    )
    write(path, png_bytes(canvas))


def svg_assets():
    source = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {MARK_W} {MARK_H}" '
        'role="img" aria-label="Mira">'
    )
    adaptive = (
        source + "<style>path{fill:#000}@media (prefers-color-scheme:dark)"
        "{path{fill:#fff}}</style>" + f'<path d="{MARK_D}"/></svg>\n'
    )
    write("admin-web/public/favicon.svg", adaptive)
    write("web/src/assets/invite/mark.svg", adaptive)
    pad = 0.2 * 512
    scale = (512 - 2 * pad) / MARK_W
    top = (512 - MARK_H * scale) / 2
    write(
        "desktop/public/buzz.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" '
        'aria-label="Mira"><rect width="512" height="512" rx="96" fill="#000"/>'
        f'<path transform="translate({pad:.1f} {top:.1f}) scale({scale:.4f})" '
        f'fill="#fff" d="{MARK_D}"/></svg>\n',
    )
    write(
        "mobile/assets/images/welcome-bee.svg",
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {MARK_W} {MARK_H}">'
        f'<path d="{MARK_D}"/></svg>\n',
    )
    for name, color in (("black", "#000"), ("white", "#fff")):
        (BRAND / f"mira-horizontal-{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {LOGO_W} {LOGO_H}" '
            f'role="img" aria-label="Mira"><path fill="{color}" d="{LOGO_D}"/></svg>\n'
        )
    (BRAND / "mira-mark.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {MARK_W} {MARK_H}" '
        f'role="img" aria-label="Mira"><path d="{MARK_D}"/></svg>\n'
    )


def react_components():
    logo = "desktop/src/shared/ui/buzz-logo"
    write(f"{logo}/BuzzMark.tsx", f"""/** The Mira mark, rendered in `currentColor`. Generated by rebrand/tools. */
export function BuzzMark({{ className }}: {{ className?: string }}) {{
  return (
    <svg
      aria-hidden="true"
      className={{["buzz-mark", className].filter(Boolean).join(" ")}}
      viewBox="0 0 {MARK_W} {MARK_H}"
      fill="currentColor"
    >
      <path d="{MARK_D}" />
    </svg>
  );
}}
""")
    write(f"{logo}/FlappingBee.tsx", """import { BuzzMark } from "./BuzzMark";

/** Mira has no bee: this slot shows the mark. Generated by rebrand/tools. */
export function FlappingBee({ className }: { className?: string }) {
  return (
    <BuzzMark className={["bee-sprite", className].filter(Boolean).join(" ")} />
  );
}
""")
    write(f"{logo}/BuzzLogoAnimation.tsx", f"""import type {{ CSSProperties }} from "react";
import "./buzz-logo-animation.css";

/**
 * Mira loading mark. Keeps the upstream props so callers need no changes; the
 * bee morph is replaced by the CSS pulse. Generated by rebrand/tools.
 */
export type BuzzLogoAnimationProps = {{
  ariaLabel?: string;
  className?: string;
  fullScreen?: boolean;
  loop?: boolean;
  loopRestSeconds?: number;
  reverse?: boolean;
  showBackground?: boolean;
  style?: CSSProperties;
  textured?: boolean;
  variant?: "v1" | "v2" | "v3" | "v4" | "v5" | "v6" | "v7" | "v8";
}};

export default function BuzzLogoAnimation({{
  ariaLabel = "Mira logo animation",
  className = "",
  fullScreen = true,
  showBackground = true,
  style,
}}: BuzzLogoAnimationProps) {{
  const classes = [
    "buzz-logo",
    fullScreen && "buzz-logo--screen",
    !fullScreen && "buzz-logo--compact",
    showBackground && "buzz-logo--background",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={{classes}} style={{style}} role="img" aria-label={{ariaLabel}}>
      <svg
        className="buzz-logo__mark"
        viewBox="0 0 {MARK_W} {MARK_H}"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="{MARK_D}" />
      </svg>
    </div>
  );
}}
""")
    write("desktop/src/features/onboarding/ui/LandingBees.tsx", """/** Mira's landing has no bee swarm. Generated by rebrand/tools. */
export function LandingBees() {
  return null;
}
""")
    write("web/src/features/invite/ui/BeeField.tsx", """/** Mira's invite page has no bee swarm. Generated by rebrand/tools. */
export function BeeField(_props: {
  count?: number;
  repel?: boolean;
  palette?: string[];
  sizeScale?: number;
  bleed?: number;
  zIndex?: number;
  clip?: boolean;
}) {
  return null;
}
""")


def main():
    pngs = [
        p for p in tracked(
            ICONS, "mobile/android/app/src/main/res",
            "mobile/ios/Runner/Assets.xcassets", "desktop/public", "web/src/assets",
            "mobile/assets/images/buzz-icon.png",
        )
        if p.endswith(".png") and re.search(
            rf"^{ICONS}/|mipmap-|AppIcon|LaunchImage|app-icon|buzz-icon", p
        ) and not p.endswith("dmg-background.png")
    ]
    for path in pngs:
        replace_png(path)
    # icon.icns is not written here. scripts/macos-icon.sh --check compares it
    # with what iconutil produces, so after a logo change regenerate it on macOS
    # with scripts/macos-icon.sh and copy it into overlay/.
    write_ico()
    wordmark("desktop/public/landing/buzz-wordmark.png")
    wordmark("mobile/assets/images/buzz-wordmark.png")
    dmg_background()
    svg_assets()
    react_components()
    print(f"{len(pngs)} PNG slots, mark {MARK_W}x{MARK_H}, logo {LOGO_W}x{LOGO_H}")


if __name__ == "__main__":
    main()
