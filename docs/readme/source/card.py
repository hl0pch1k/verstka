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
fU = ImageFont.truetype(U, 34 * S)
fN = ImageFont.truetype(U, 80 * S)
fM = ImageFont.truetype(M, 19 * S)
d.text((PAD * S - 4 * S, 34 * S), num, font=fN, fill=(212, 214, 214, 255))
tx = PAD * S - 4 * S + d.textlength(num, font=fN) + 24 * S
d.text((tx, 42 * S), title, font=fU, fill=(11, 18, 32, 255))
# chips
x = tx
y = 92 * S
for i, c in enumerate(chips.split("|")):
    w = d.textlength(c, font=fM) + 32 * S
    fill = (11, 18, 32, 255) if i == 0 else (255, 255, 255, 255)
    col = (255, 255, 255, 255) if i == 0 else (11, 18, 32, 255)
    d.rounded_rectangle([x, y, x + w, y + 34 * S], 17 * S, fill=fill)
    d.text((x + 16 * S, y + 6 * S), c, font=fM, fill=col)
    x += w + 10 * S
# logo bars at the right
bx = (CW - PAD - 56) * S
for i, (wd, col) in enumerate(((56, (191, 214, 255)), (40, (37, 99, 235)), (24, (11, 18, 32)))):
    d.rounded_rectangle([bx, (52 + i * 14) * S, bx + wd * S, (60 + i * 14) * S], 4 * S, fill=col + (255,))
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
