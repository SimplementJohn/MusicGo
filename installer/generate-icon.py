"""Genere musicgo.ico + assets wizard depuis icon.png et logotexte.png."""

from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow manquant. Installez-le : pip install pillow")

REPO_ROOT     = Path(__file__).resolve().parent.parent
ICON_SRC      = REPO_ROOT / "icon.png"
LOGO_SRC      = REPO_ROOT / "logotexte.png"

OUTPUT        = Path(__file__).resolve().parent / "musicgo.ico"
LOGO_ICO      = Path(__file__).resolve().parent / "musicgo_logo.ico"
WIZARD_LARGE  = Path(__file__).resolve().parent / "assets" / "wizard-large.bmp"
WIZARD_SMALL  = Path(__file__).resolve().parent / "assets" / "wizard-small.bmp"

BG     = (26, 26, 46)
SIZES  = [16, 32, 48, 64, 128, 256]


def load_icon_src() -> Image.Image:
    if ICON_SRC.exists():
        return Image.open(ICON_SRC).convert("RGBA")
    # Fallback: carre sombre avec play
    img = Image.new("RGBA", (256, 256), BG + (255,))
    d = ImageDraw.Draw(img)
    d.polygon([(80, 60), (80, 196), (196, 128)], fill=(255, 255, 255, 255))
    return img


def main() -> None:
    src = load_icon_src()
    images = [src.resize((s, s), Image.LANCZOS) for s in SIZES]
    base = images[-1]
    base.save(OUTPUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"[OK] Icone generee depuis {ICON_SRC.name} : {OUTPUT}")

    # Copie aussi en PNG pour le stub C# (icone exe)
    src.resize((256, 256), Image.LANCZOS).save(
        Path(__file__).resolve().parent / "musicgo_icon.png"
    )

    # Icone raccourci bureau : logotexte.png (avec texte du logo)
    if LOGO_SRC.exists():
        make_logo_ico()


def make_logo_ico() -> None:
    """Genere musicgo_logo.ico depuis logotexte.png.
    Image rectangulaire (logo + texte) -> carre transparent padded."""
    logo = Image.open(LOGO_SRC).convert("RGBA")
    out_imgs = []
    for sz in SIZES:
        # Fit dans carre sz x sz, padding transparent
        ratio = min(sz / logo.width, sz / logo.height)
        w = max(1, int(logo.width * ratio))
        h = max(1, int(logo.height * ratio))
        resized = logo.resize((w, h), Image.LANCZOS)
        canvas = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        canvas.paste(resized, ((sz - w) // 2, (sz - h) // 2), resized)
        out_imgs.append(canvas)
    out_imgs[-1].save(LOGO_ICO, format="ICO",
                      sizes=[(s, s) for s in SIZES],
                      append_images=out_imgs[:-1])
    print(f"[OK] Logo ICO genere depuis {LOGO_SRC.name} : {LOGO_ICO}")


def make_wizard_large() -> None:
    """164x314 — image laterale Inno Setup.
    Utilise logotexte.png centre sur fond sombre si disponible."""
    w, h = 164, 314
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    # Degrade subtil
    for y in range(h):
        ratio = y / h
        r = int(26 + 20 * ratio)
        g = int(26 + 8  * ratio)
        b = int(46 + 15 * ratio)
        d.line([(0, y), (w, y)], fill=(r, g, b))

    # Logo icone en haut
    icon_src = load_icon_src()
    icon_sz = 72
    icon_img = icon_src.resize((icon_sz, icon_sz), Image.LANCZOS).convert("RGBA")
    icon_x = (w - icon_sz) // 2
    img.paste(icon_img, (icon_x, 28), icon_img)

    # logotexte.png en dessous si disponible
    if LOGO_SRC.exists():
        logo = Image.open(LOGO_SRC).convert("RGBA")
        max_w = w - 16
        ratio = max_w / logo.width
        logo_h = int(logo.height * ratio)
        logo = logo.resize((max_w, logo_h), Image.LANCZOS)
        logo_y = 28 + icon_sz + 14
        img.paste(logo, (8, logo_y), logo)

    WIZARD_LARGE.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(WIZARD_LARGE), format="BMP")
    print(f"[OK] wizard-large.bmp genere")


def make_wizard_small() -> None:
    """55x55 — petite image header Inno Setup."""
    src = load_icon_src()
    img = src.resize((55, 55), Image.LANCZOS).convert("RGB")
    WIZARD_SMALL.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(WIZARD_SMALL), format="BMP")
    print(f"[OK] wizard-small.bmp genere")


if __name__ == "__main__":
    main()
    make_wizard_large()
    make_wizard_small()
