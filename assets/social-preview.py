"""Generate the WarrantOS social preview image (1280x640) deterministically.

PIL-only, no network access. Run with: python assets/social-preview.py
Produces assets/social-preview.png alongside this script.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1280, 640
MARGIN = 80

# Fire House / terminal-inspired palette.
BG = (11, 14, 20)  # #0B0E14 very dark navy-black
ACCENT = (212, 160, 63)  # warm amber/gold accent rule
TEXT_PRIMARY = (240, 242, 246)  # near-white headline
TEXT_SECONDARY = (198, 204, 214)  # subline
TEXT_TAGLINE = (150, 158, 172)  # muted tagline
TEXT_FOOTER = (110, 118, 132)  # dim footer
PANEL_BG = (16, 20, 28)  # verdict strip background, slightly lighter than BG
PANEL_BORDER = (34, 40, 52)

VERDICT_PASS = (63, 185, 80)  # #3FB950
VERDICT_HOLD = (210, 153, 34)  # #D29922
VERDICT_BLOCK = (248, 81, 73)  # #F85149
VERDICT_GREY = (125, 133, 144)

FONT_CANDIDATES_REGULAR = ["segoeui.ttf", "arial.ttf"]
FONT_CANDIDATES_BOLD = ["segoeuib.ttf", "arialbd.ttf"]
FONT_CANDIDATES_MONO = [
    "consola.ttf",
    "cascadiamono.ttf",
    "cour.ttf",
]

WINDOWS_FONT_DIR = r"C:\Windows\Fonts"

# Populated by _load_font(); recorded so the caller can confirm what was used.
FONT_LOG: list[str] = []


def _resolve_font_path(candidates: list[str]) -> str | None:
    for name in candidates:
        path = os.path.join(WINDOWS_FONT_DIR, name)
        if os.path.isfile(path):
            return path
    return None


def _load_font(candidates: list[str], size: int, label: str) -> ImageFont.FreeTypeFont:
    path = _resolve_font_path(candidates)
    if path is not None:
        FONT_LOG.append(f"{label} @ {size}px -> {os.path.basename(path)}")
        return ImageFont.truetype(path, size)
    FONT_LOG.append(f"{label} @ {size}px -> PIL default (no candidate found)")
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def build_image() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Fonts.
    font_headline = _load_font(FONT_CANDIDATES_BOLD, 96, "headline")
    font_subline = _load_font(FONT_CANDIDATES_REGULAR, 44, "subline")
    font_tagline = _load_font(FONT_CANDIDATES_REGULAR, 26, "tagline")
    font_mono_label = _load_font(FONT_CANDIDATES_MONO, 22, "verdict-label")
    font_mono_footer = _load_font(FONT_CANDIDATES_MONO, 18, "footer")
    if font_mono_label is None:  # pragma: no cover - defensive, _load_font never returns None
        font_mono_label = font_tagline

    # Thin amber accent rule near the top, inset from the margins.
    accent_y = MARGIN
    draw.line(
        [(MARGIN, accent_y), (WIDTH - MARGIN, accent_y)],
        fill=ACCENT,
        width=3,
    )

    # Headline: "WarrantOS".
    headline_text = "WarrantOS"
    headline_y = accent_y + 40
    draw.text((MARGIN, headline_y), headline_text, font=font_headline, fill=TEXT_PRIMARY)

    # Subline: "CI for claims": larger than the tagline, sits under the headline.
    subline_text = "CI for claims"
    headline_bbox = draw.textbbox((MARGIN, headline_y), headline_text, font=font_headline)
    subline_y = headline_bbox[3] + 18
    draw.text((MARGIN, subline_y), subline_text, font=font_subline, fill=TEXT_SECONDARY)

    # Tagline, wrapped to fit within the margins if needed.
    tagline_text = (
        "Every claim ships with a source, a [CITE NEEDED], or a logged BLOCK."
    )
    subline_bbox = draw.textbbox((MARGIN, subline_y), subline_text, font=font_subline)
    tagline_y = subline_bbox[3] + 34
    draw.text((MARGIN, tagline_y), tagline_text, font=font_tagline, fill=TEXT_TAGLINE)

    # Verdict strip: terminal-style panel near the bottom.
    strip_height = 74
    strip_y1 = HEIGHT - MARGIN - strip_height
    strip_y0 = strip_y1
    strip_bottom = strip_y1 + strip_height
    draw.rectangle(
        [(MARGIN, strip_y0), (WIDTH - MARGIN, strip_bottom)],
        fill=PANEL_BG,
        outline=PANEL_BORDER,
        width=1,
    )

    verdicts = [
        ("PASS", VERDICT_PASS),
        ("HOLD", VERDICT_HOLD),
        ("BLOCK", VERDICT_BLOCK),
        ("NOT_ASSESSABLE", VERDICT_GREY),
    ]
    gap = 44
    cursor_x = MARGIN + 32
    text_y = strip_y0 + (strip_height - font_mono_label.size) // 2 - 4
    for label, colour in verdicts:
        draw.text((cursor_x, text_y), label, font=font_mono_label, fill=colour)
        cursor_x += _text_width(draw, label, font_mono_label) + gap

    # Footer, small and dim, below the verdict strip is out of bounds so place
    # it just above the strip on the right, keeping the generous bottom margin.
    footer_text = "MIT, stdlib-only Python"
    footer_w = _text_width(draw, footer_text, font_mono_footer)
    footer_y = strip_y0 - 34
    draw.text(
        (WIDTH - MARGIN - footer_w, footer_y),
        footer_text,
        font=font_mono_footer,
        fill=TEXT_FOOTER,
    )

    return img


def main() -> None:
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social-preview.png")
    img = build_image()
    img.save(out_path, format="PNG")

    # Verify the output.
    with Image.open(out_path) as check:
        check.load()
        assert check.size == (WIDTH, HEIGHT), f"unexpected size: {check.size}"
        assert check.mode == "RGB", f"unexpected mode: {check.mode}"

    print(f"Wrote {out_path}")
    print(f"Verified size={img.size} mode={img.mode}")
    print("Fonts used:")
    for entry in FONT_LOG:
        print(f"  {entry}")


if __name__ == "__main__":
    main()
