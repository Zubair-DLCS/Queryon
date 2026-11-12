"""Draws the Queryon icon (assets/queryon.png and assets/queryon.ico)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "assets"
S = 1024


def font(size):
    for name in ("segoeuib.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# rounded square with a teal gradient
grad = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(grad)
for y in range(S):
    t = y / S
    gd.line([(0, y), (S, y)], fill=(int(17 + 0 * t), int(94 + 22 * t), int(89 + 55 * t), 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
img.paste(grad, (0, 0), mask)

# document sheet
d.rounded_rectangle([250, 210, 690, 760], radius=40, fill=(255, 255, 255, 255))
d.polygon([(590, 210), (690, 310), (590, 310)], fill=(204, 251, 241, 255))
for i, w in enumerate((330, 300, 330, 220)):
    y = 360 + i * 80
    d.rounded_rectangle([310, y, 310 + w, y + 30], radius=15, fill=(153, 246, 228, 255))

# speech bubble with a question mark
d.ellipse([500, 520, 860, 850], fill=(251, 191, 36, 255))
d.polygon([(560, 790), (520, 900), (650, 830)], fill=(251, 191, 36, 255))
d.text((680, 690), "?", font=font(250), fill=(17, 94, 89, 255), anchor="mm")

OUT.mkdir(exist_ok=True)
img.resize((256, 256), Image.LANCZOS).save(OUT / "queryon.png")
img.save(OUT / "queryon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon written to", OUT)
