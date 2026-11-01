"""Gera assets/icon.ico (raio neon) com Pillow."""
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))


def make(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, size - 8, size - 8), fill=(8, 14, 27, 255), outline=(0, 212, 255, 255), width=10)
    s = size / 256
    bolt = [(150, 30), (70, 140), (122, 140), (100, 226), (186, 110), (134, 110), (160, 30)]
    pts = [(x * s, y * s) for x, y in bolt]
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(pts, fill=(0, 212, 255, 200))
    glow = glow.filter(ImageFilter.GaussianBlur(10 * s))
    img = Image.alpha_composite(img, glow)
    ImageDraw.Draw(img).polygon(pts, fill=(0, 212, 255, 255))
    return img


if __name__ == "__main__":
    im = make()
    im.save(os.path.join(HERE, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
                                                     (256, 256)])
    im.save(os.path.join(HERE, "icon.png"))
    print("icon.ico gerado")
