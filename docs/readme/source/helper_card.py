"""Helper cards for the README in the «Слои» style (Pillow + poppler).

before/after:  helper_card.py pair  out.webp "просьба" before.pdf PAGE after.pdf PAGE
chat panels:   helper_card.py chat  out.webp "Заголовок" shot1.png "подпись 1" shot2.png "подпись 2" ...

The request pill is drawn like a user message in the Помощник chat (blue bubble, white text) and its text is centred by
the ink box of the glyphs (cap height for the vertical centre), as in the showcase cards (card.py)."""
import os, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from fontTools.ttLib import TTFont

FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "verstka", "fonts")
U = f"{FD}/Unbounded/Unbounded-Bold.ttf"
M = f"{FD}/Manrope/Manrope-Bold.ttf"
S = 2
CW, PAD = 1600, 40
INK, BLUE, PLATE = (11, 18, 32), (37, 99, 235), (243, 244, 241)


def _os2(path):
    t = TTFont(path)
    return t["OS/2"].sCapHeight / t["head"].unitsPerEm, t["OS/2"].sxHeight / t["head"].unitsPerEm


CAP_U, _ = _os2(U)
CAP_M, X_M = _os2(M)


def optical(text, size):
    return (CAP_M if any(ch.isupper() or ch.isdigit() for ch in text) else X_M) * size


def pdf_page(pdf, page, width):
    tmp = tempfile.mkdtemp()
    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-png", "-scale-to-x", str(width), "-scale-to-y", "-1",
                    pdf, f"{tmp}/p"], check=True)
    im = Image.open(os.path.join(tmp, os.listdir(tmp)[0])).convert("RGB")
    # LibreOffice leaves a 1 px dark seam at the edges of a slide with a background picture: trim 3 px all round
    return im.crop((3, 3, im.width - 3, im.height - 3))


def canvas(H):
    img = Image.new("RGBA", (CW * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([56 * S, 0, (CW - 56) * S, 70 * S], 30 * S, fill=(191, 214, 255, 255))
    d.rounded_rectangle([28 * S, 10 * S, (CW - 28) * S, 80 * S], 30 * S, fill=(233, 241, 255, 255))
    d.rounded_rectangle([0, 20 * S, CW * S, H * S], 32 * S, fill=PLATE + (255,))
    return img, d


def logo_bars(d, mid):
    k = 2.5 * S
    bx = CW * S - PAD * S - (28 + 3 + 20 + 3 + 12) * k
    for wd, col in ((28, (191, 214, 255)), (20, BLUE), (12, INK)):
        d.rounded_rectangle([bx, mid - 2 * k, bx + wd * k, mid + 2 * k], 2 * k, fill=col + (255,))
        bx += (wd + 3) * k


def pill(d, x, cy, text, size, fill, color, padx=22, h=None, center_x=None):
    """Pill with text centred by its drawn outlines; returns the right edge. With center_x the pill is centred there."""
    f = ImageFont.truetype(M, size * S)
    x0, _, x1, _ = d.textbbox((0, 0), text, font=f, anchor="ls")
    h = (h or size * 2) * S
    w = (x1 - x0) + 2 * padx * S
    if center_x is not None:
        x = center_x - w / 2
    d.rounded_rectangle([x, cy - h / 2, x + w, cy + h / 2], h / 2, fill=fill)
    d.text((x + w / 2 - (x0 + x1) / 2, cy + optical(text, size * S) / 2), text, font=f, fill=color, anchor="ls")
    return x + w


def shot(img, im, X, Y, w, h, r=14):
    """Paste an image with rounded corners and a soft shadow (all in supersampled pixels)."""
    im = im.resize((int(w), int(h)), Image.LANCZOS)
    sh = Image.new("RGBA", (int(w) + 40 * S, int(h) + 40 * S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([20 * S, 24 * S, w + 20 * S, h + 24 * S], r * S, fill=INK + (30,))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10 * S)), (int(X - 20 * S), int(Y - 20 * S)))
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], r * S, fill=255)
    img.paste(im, (int(X), int(Y)), mask)


def save(img, out):
    W, H = img.size
    img = img.resize((W // S, H // S), Image.LANCZOS)
    img.save(out, "WEBP", quality=84, method=6)
    print(out, os.path.getsize(out) // 1024, "KB", img.size)


def pair(out, request, before_pdf, before_page, after_pdf, after_page):
    head, gap = 120, 96
    sw = (CW - 2 * PAD - gap) // 2
    sh_ = round(sw * 9 / 16)
    lab = 64
    H = 20 + head + sh_ + lab + PAD - 16
    img, d = canvas(H)
    mid = (20 + head / 2 + 6) * S
    pill(d, PAD * S, mid, request, 22, BLUE + (255,), (255, 255, 255, 255), padx=26, h=52)
    logo_bars(d, mid)
    y = (20 + head) * S
    for i, (pdf, page, tag) in enumerate(((before_pdf, before_page, "до"), (after_pdf, after_page, "после"))):
        X = (PAD + i * (sw + gap)) * S
        shot(img, pdf_page(pdf, page, sw * S), X, y, sw * S, sh_ * S)
        pill(d, 0, y + (sh_ + lab / 2 + 4) * S, tag, 18, (255, 255, 255, 255) if i == 0 else INK + (255,),
             INK + (255,) if i == 0 else (255, 255, 255, 255), padx=18, h=36, center_x=X + sw * S / 2)
    # arrow between the slides
    cx, cy, r = (PAD + sw + gap / 2) * S, y + sh_ * S / 2, 30 * S
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BLUE + (255,))
    a = 11 * S
    d.line([cx - a, cy, cx + a, cy], fill=(255, 255, 255, 255), width=int(4 * S))
    d.line([cx + a - 9 * S, cy - 9 * S, cx + a + 1 * S, cy, cx + a - 9 * S, cy + 9 * S], fill=(255, 255, 255, 255),
           width=int(4 * S), joint="curve")
    save(img, out)


def chat(out, title, items):
    head, gap = 120, 32
    n = len(items)
    pw = (CW - 2 * PAD - (n - 1) * gap) / n
    ims = [Image.open(p).convert("RGB") for p, _ in items]
    ph = pw * ims[0].height / ims[0].width
    lab = 64
    H = int(20 + head + ph + lab + PAD - 16)
    img, d = canvas(H)
    mid = (20 + head / 2 + 6) * S
    fU = ImageFont.truetype(U, 34 * S)
    x0, _, _, _ = d.textbbox((0, 0), title, font=fU, anchor="ls")
    d.text((PAD * S - x0, mid + CAP_U * 34 * S / 2), title, font=fU, fill=INK + (255,), anchor="ls")
    logo_bars(d, mid)
    y = (20 + head) * S
    for i, (im, (_, cap_)) in enumerate(zip(ims, items)):
        X = (PAD + i * (pw + gap)) * S
        shot(img, im, X, y, pw * S, ph * S, r=24)
        pill(d, 0, y + (ph + lab / 2 + 4) * S, cap_, 18, (255, 255, 255, 255), INK + (255,), padx=18, h=36,
             center_x=X + pw * S / 2)
    save(img, out)


if __name__ == "__main__":
    mode, out = sys.argv[1], sys.argv[2]
    if mode == "pair":
        request, bp, bn, ap, an = sys.argv[3:8]
        pair(out, request, bp, int(bn), ap, int(an))
    else:
        title, rest = sys.argv[3], sys.argv[4:]
        chat(out, title, list(zip(rest[::2], rest[1::2])))
