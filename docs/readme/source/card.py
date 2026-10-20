"""Showcase card in the «Слои» style: plate with deck title and chips + 2×2 real slides rendered from deck.pdf by LibreOffice.
needs Pillow and poppler (pdftoppm); usage: card.py deck.pdf "1,4,9,13" "N" "Title" "chip1|chip2|chip3" out.webp"""
import os, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "verstka", "fonts")
U = f"{FD}/Unbounded/Unbounded-Bold.ttf"
M = f"{FD}/Manrope/Manrope-Bold.ttf"
pdf, pages, num, title, chips, out = sys.argv[1:7]
pages = [int(p) for p in pages.split(",")]
S = 2  # supersampling
CW, PAD, GAP, HEAD = 1600, 40, 24, 132
sw = (CW - 2 * PAD - GAP) // 2
sh = round(sw * 9 / 16)
ROWS = (len(pages) + 1) // 2
H = HEAD + 20 + ROWS * sh + (ROWS - 1) * GAP + PAD
tmp = tempfile.mkdtemp()
slides = []
for k, p in enumerate(pages):
    subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-png", "-scale-to-x", str(sw * S), "-scale-to-y", "-1", pdf,
                    f"{tmp}/k{k}x"], check=True)
    f = [x for x in os.listdir(tmp) if x.startswith(f"k{k}x")][0]
    slides.append(Image.open(f"{tmp}/{f}").convert("RGB"))

img = Image.new("RGBA", (CW * S, H * S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# layered plates peeking from behind, then the front plate
d.rounded_rectangle([56 * S, 0, (CW - 56) * S, 70 * S], 30 * S, fill=(191, 214, 255, 255))
d.rounded_rectangle([28 * S, 10 * S, (CW - 28) * S, 80 * S], 30 * S, fill=(233, 241, 255, 255))
d.rounded_rectangle([0, 20 * S, CW * S, H * S], 32 * S, fill=(243, 244, 241, 255))
from fontTools.ttLib import TTFont


def _os2(path):
    t = TTFont(path)
    return t["OS/2"].sCapHeight / t["head"].unitsPerEm, t["OS/2"].sxHeight / t["head"].unitsPerEm


CAP_U, _ = _os2(U)
CAP_M, X_M = _os2(M)
fU = ImageFont.truetype(U, 34 * S)
fN = ImageFont.truetype(U, 80 * S)
fM = ImageFont.truetype(M, 19 * S)


def ink(text, font):
    """Ink box of `text` drawn with its baseline-left at (0, 0) (anchor «ls»)."""
    return d.textbbox((0, 0), text, font=font, anchor="ls")


def optical(text, size):
    """Height used to centre a label like an interface button: caps/digits → cap height, lowercase → x-height."""
    return (CAP_M if any(ch.isupper() or ch.isdigit() for ch in text) else X_M) * size


# header block: title (cap top → baseline), 16 px, a row of chips 34 px tall; the number is centred on the block
NUM_COL = max(ink(f"{i:02d}", fN)[2] - ink(f"{i:02d}", fN)[0] for i in range(1, 10))
cap_t = CAP_U * 34 * S
chip_h, chip_pad, chip_gap = 34 * S, 16 * S, 10 * S
block = cap_t + 16 * S + chip_h
mid = 86 * S
top = mid - block / 2
nx0 = ink(num, fN)[0]
d.text((PAD * S - nx0, mid + CAP_U * 80 * S / 2), num, font=fN, fill=(212, 214, 214, 255), anchor="ls")
tx = PAD * S + NUM_COL + 28 * S
d.text((tx - ink(title, fU)[0], top + cap_t), title, font=fU, fill=(11, 18, 32, 255), anchor="ls")
# chips: text centred on the chip by its drawn outlines
x = tx
y = top + cap_t + 16 * S
for i, c in enumerate(chips.split("|")):
    x0, _, x1, _ = ink(c, fM)
    w = (x1 - x0) + 2 * chip_pad
    fill = (11, 18, 32, 255) if i == 0 else (255, 255, 255, 255)
    col = (255, 255, 255, 255) if i == 0 else (11, 18, 32, 255)
    d.rounded_rectangle([x, y, x + w, y + chip_h], chip_h / 2, fill=fill)
    cx, cy = x + w / 2, y + chip_h / 2
    d.text((cx - (x0 + x1) / 2, cy + optical(c, 19 * S) / 2), c, font=fM, fill=col, anchor="ls")
    x += w + chip_gap
# the interface logo's bar row (28 / 20 / 12 wide, 4 tall, 3 apart at 20 px type), right-aligned, centred on the block
k = 2.5 * S
bx = CW * S - PAD * S - (28 + 3 + 20 + 3 + 12) * k
for wd, col in ((28, (191, 214, 255)), (20, (37, 99, 235)), (12, (11, 18, 32))):
    d.rounded_rectangle([bx, mid - 2 * k, bx + wd * k, mid + 2 * k], 2 * k, fill=col + (255,))
    bx += (wd + 3) * k
# slides
for i, s in enumerate(slides):
    r, c = divmod(i, 2)
    X = (PAD + c * (sw + GAP)) * S
    Y = (HEAD + 20 + r * (sh + GAP)) * S
    s = s.resize((sw * S, sh * S), Image.LANCZOS)
    sh_ = Image.new("RGBA", (sw * S + 40 * S, sh * S + 40 * S), (0, 0, 0, 0))
    ImageDraw.Draw(sh_).rounded_rectangle([20 * S, 24 * S, sw * S + 20 * S, sh * S + 24 * S], 16 * S, fill=(11, 18, 32, 30))
    sh_ = sh_.filter(ImageFilter.GaussianBlur(10 * S))
    img.alpha_composite(sh_, (X - 20 * S, Y - 20 * S))
    mask = Image.new("L", s.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s.size[0] - 1, s.size[1] - 1], 14 * S, fill=255)
    img.paste(s, (X, Y), mask)
img = img.resize((CW, H), Image.LANCZOS)
img.save(out, "WEBP", quality=84, method=6)
print(out, os.path.getsize(out) // 1024, "KB", img.size)
