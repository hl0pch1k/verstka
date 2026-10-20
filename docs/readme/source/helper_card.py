"""Helper cards for the README in the «Слои» style (Pillow + poppler).

before/after:  helper_card.py pair  out.webp "просьба" before.pdf PAGE after.pdf PAGE
chat panels:   helper_card.py chat  out.webp "Заголовок" shot1.png "подпись 1" shot2.png "подпись 2" ...
screen:        helper_card.py screen out.webp WIDTH "подпись" shot.png   (interface screen on a plate, 1600 or 800 wide)
phones:        helper_card.py phones out.webp "подпись" phone1.png "экран 1" phone2.png "экран 2" ...

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


def save(img, out, scale=1.0):
    W, H = img.size
    img = img.resize((round(W * scale / S), round(H * scale / S)), Image.LANCZOS)
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


# ---------------------------------------------------------------- interface screens
def stack_box(im, bg=(243, 244, 241)):
    """Bounds of the interface stack (the plates) in a 1920×1080 shot: everything below the header that differs from
    the page background."""
    import numpy as np
    a = np.abs(np.asarray(im).astype(int) - np.array(bg)).sum(2) > 8
    a[:60] = False
    ys, xs = np.where(a)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def screen(out, cw, caption, png, radius=48):
    """One interface screen on a plate: dark caption pill + logo bars on top, the real screen below with its own
    rounded corners and a soft shadow."""
    global CW, PAD
    CW, PAD = cw, (40 if cw >= 1200 else 24)
    im = Image.open(png).convert("RGB")
    im = im.crop(stack_box(im))
    big = cw >= 1200
    head = 116 if big else 104
    sw = cw - 2 * PAD
    sh_ = sw * im.height / im.width
    H = int(20 + head + sh_ + PAD)
    img, d = canvas(H)
    mid = (20 + head / 2 + 2) * S
    pill(d, PAD * S, mid, caption, 21 if big else 26, INK + (255,), (255, 255, 255, 255), padx=24 if big else 26,
         h=50 if big else 60)
    k = (2.5 if big else 2.4) * S
    bx = CW * S - PAD * S - (28 + 3 + 20 + 3 + 12) * k
    for wd, col in ((28, (191, 214, 255)), (20, BLUE), (12, INK)):
        d.rounded_rectangle([bx, mid - 2 * k, bx + wd * k, mid + 2 * k], 2 * k, fill=col + (255,))
        bx += (wd + 3) * k
    shot(img, im, PAD * S, (20 + head) * S, sw * S, sh_ * S, r=radius * sw / im.width)
    save(img, out, 1.0 if big else 1.5)  # small cards are shown half-width: 1.5× pixels stay sharp on HiDPI


# ---------------------------------------------------------------- phone screens (design of the mobile version)
def phones(out, caption, items):
    """Three phone screens (390×844 renders of the «Слои» phone boards) in plain rounded frames — no maker marks —
    with arrows between them and a caption pill under each."""
    global CW, PAD
    CW, PAD = 1600, 40
    head, lab = 116, 70
    sh_, bez, gap = 720, 9, 128
    ims = [Image.open(p).convert("RGB") for p, _ in items]
    sw = sh_ * ims[0].width / ims[0].height
    fw, fh = sw + 2 * bez, sh_ + 2 * bez
    total = len(ims) * fw + (len(ims) - 1) * gap
    x0 = (CW - total) / 2
    H = int(20 + head + fh + lab + PAD - 10)
    img, d = canvas(H)
    mid = (20 + head / 2 + 2) * S
    pill(d, PAD * S, mid, caption, 21, INK + (255,), (255, 255, 255, 255), padx=24, h=50)
    logo_bars(d, mid)
    y = (20 + head) * S
    for i, (im, (_, cap_)) in enumerate(zip(ims, items)):
        X = (x0 + i * (fw + gap)) * S
        # frame: soft shadow, thin dark bezel, the screen inside with matching corners
        shadow = Image.new("RGBA", (int(fw * S) + 60 * S, int(fh * S) + 60 * S), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle([30 * S, 38 * S, fw * S + 30 * S, fh * S + 38 * S], 54 * S,
                                                 fill=INK + (46,))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14 * S)), (int(X - 30 * S), int(y - 30 * S)))
        d.rounded_rectangle([X, y, X + fw * S, y + fh * S], 54 * S, fill=INK + (255,))
        scr = im.resize((int(sw * S), int(sh_ * S)), Image.LANCZOS)
        mask = Image.new("L", scr.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, scr.size[0] - 1, scr.size[1] - 1], 46 * S, fill=255)
        img.paste(scr, (int(X + bez * S), int(y + bez * S)), mask)
        pill(d, 0, y + (fh + lab / 2 + 6) * S, cap_, 18, (255, 255, 255, 255), INK + (255,), padx=18, h=36,
             center_x=X + fw * S / 2)
        if i < len(ims) - 1:
            cx, cy, r = X + (fw + gap / 2) * S, y + fh * S / 2, 30 * S
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BLUE + (255,))
            a = 11 * S
            d.line([cx - a, cy, cx + a, cy], fill=(255, 255, 255, 255), width=int(4 * S))
            d.line([cx + a - 9 * S, cy - 9 * S, cx + a + 1 * S, cy, cx + a - 9 * S, cy + 9 * S],
                   fill=(255, 255, 255, 255), width=int(4 * S), joint="curve")
    save(img, out)


if __name__ == "__main__" and sys.argv[1] != "pitch":
    mode, out = sys.argv[1], sys.argv[2]
    if mode == "phones":
        rest = sys.argv[4:]
        phones(out, sys.argv[3], list(zip(rest[::2], rest[1::2])))
    elif mode == "screen":
        screen(out, int(sys.argv[3]), sys.argv[4], sys.argv[5])
    elif mode == "pair":
        request, bp, bn, ap, an = sys.argv[3:8]
        pair(out, request, bp, int(bn), ap, int(an))
    else:
        title, rest = sys.argv[3], sys.argv[4:]
        chat(out, title, list(zip(rest[::2], rest[1::2])))


def pitch(out, pdf, title, items):
    """The solution pitch: a title pill and a 2 × 2 grid of slides with one-line captions (helper_card.py pitch …)."""
    head, gap, lab = 120, 48, 56
    sw = (CW - 2 * PAD - gap) // 2
    sh_ = round(sw * 9 / 16)
    rows = (len(items) + 1) // 2
    H = 20 + head + rows * (sh_ + lab) + (rows - 1) * 24 + PAD - 16
    img, d = canvas(H)
    mid = (20 + head / 2 + 6) * S
    pill(d, PAD * S, mid, title, 22, INK + (255,), (255, 255, 255, 255), padx=26, h=52)
    logo_bars(d, mid)
    for i, (page, cap_) in enumerate(items):
        r, c = divmod(i, 2)
        X = (PAD + c * (sw + gap)) * S
        Y = (20 + head + r * (sh_ + lab + 24)) * S
        shot(img, pdf_page(pdf, page, sw * S), X, Y, sw * S, sh_ * S)
        pill(d, 0, Y + (sh_ + lab / 2 + 4) * S, cap_, 18, (255, 255, 255, 255), INK + (255,), padx=18, h=36,
             center_x=X + sw * S / 2)
    save(img, out)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "pitch":
    _, _, _out, _pdf, _title, *_rest = sys.argv
    pitch(_out, _pdf, _title, [(int(_rest[i]), _rest[i + 1]) for i in range(0, len(_rest), 2)])
