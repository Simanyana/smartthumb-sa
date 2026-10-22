"""Generate a synthetic test dataset in tests/test_images/ (valid + invalid files).

Synthetic images exercise the pipeline (sizes, formats, orientations, bad files).
For the Rekognition demo and label-usefulness metric, ADD 5-10 real, permission-
cleared product photos (your own handbags/shoes/crafts) to tests/test_images/.
"""
import os
import random
import sys

from PIL import Image, ImageDraw

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "tests", "test_images")
os.makedirs(OUT, exist_ok=True)
random.seed(7)


def textured(w, h, mode="RGB"):
    """Gradient + noise blocks so JPEG/PNG sizes behave like real photos."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            c = ((x * 255) // w, (y * 255) // h, random.randint(0, 255))
            for dy in range(4):
                for dx in range(4):
                    if x + dx < w and y + dy < h:
                        px[x + dx, y + dy] = c
    d = ImageDraw.Draw(img)
    d.rectangle([w // 4, h // 4, 3 * w // 4, 3 * h // 4], outline=(255, 255, 255), width=max(2, w // 100))
    return img.convert(mode) if mode != "RGB" else img


valid = [
    ("handbag_01.jpg", 4000, 3000, "JPEG"),
    ("shoes_02.jpg", 3024, 4032, "JPEG"),       # portrait phone photo
    ("craft_03.jpeg", 1600, 1200, "JPEG"),
    ("gift_04.JPG", 2400, 2400, "JPEG"),        # uppercase extension
    ("panorama_05.jpg", 6000, 1200, "JPEG"),    # very wide
    ("tall_06.jpg", 1000, 5000, "JPEG"),        # very tall
    ("logo_07.png", 1200, 1200, "PNG"),
    ("transparent_08.png", 800, 600, "PNG-A"),  # PNG with alpha
    ("small_09.jpg", 200, 150, "JPEG"),         # already smaller than 300 (no upscale)
    ("exact_10.png", 300, 300, "PNG"),
]
for i in range(11, 25):
    valid.append((f"product_{i}.jpg", random.choice([1280, 1920, 2560, 3200]), random.choice([960, 1440, 1920, 2400]), "JPEG"))

for name, w, h, kind in valid:
    if kind == "JPEG":
        textured(w, h).save(os.path.join(OUT, name), "JPEG", quality=92)
    elif kind == "PNG":
        textured(w, h).save(os.path.join(OUT, name), "PNG")
    else:
        img = textured(w, h).convert("RGBA")
        ImageDraw.Draw(img).ellipse([0, 0, w // 2, h // 2], fill=(0, 0, 0, 0))
        img.save(os.path.join(OUT, name), "PNG")

# EXIF-rotated (orientation tag 6 = rotate 270 to display upright)
img = textured(1600, 1000)
exif = Image.Exif()
exif[0x0112] = 6
img.save(os.path.join(OUT, "rotated_exif_25.jpg"), "JPEG", exif=exif)

# ---- invalid / hostile files (FR7) ----
with open(os.path.join(OUT, "INVALID_not_an_image.jpg"), "w") as f:
    f.write("this is plain text pretending to be a jpg")
open(os.path.join(OUT, "INVALID_empty.png"), "wb").close()
good = os.path.join(OUT, "handbag_01.jpg")
with open(good, "rb") as f:
    data = f.read()
with open(os.path.join(OUT, "INVALID_truncated.jpg"), "wb") as f:
    f.write(data[: len(data) // 3])
textured(200, 200).save(os.path.join(OUT, "INVALID_animated.gif"), "GIF")
with open(os.path.join(OUT, "INVALID_notes.txt"), "w") as f:
    f.write("product price list")
with open(os.path.join(OUT, "INVALID_document.pdf"), "wb") as f:
    f.write(b"%PDF-1.4\n%fake\n")
with open(os.path.join(OUT, "INVALID_png_named_jpg.jpg"), "wb") as f:  # real PNG, wrong extension: should still process
    pass
os.remove(os.path.join(OUT, "INVALID_png_named_jpg.jpg"))
textured(900, 700).save(os.path.join(OUT, "png_named_jpg_26.jpg"), "PNG")  # accepted: content decides format
print(f"Wrote {len(os.listdir(OUT))} files to {os.path.abspath(OUT)}")
