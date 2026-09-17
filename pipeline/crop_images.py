#!/usr/bin/env python3
"""Crop herb illustration/photo regions from page PNGs -> webp per herb.

fj1:   plate page is a full-page illustration -> trim margins
caise: plate page = caption line + photo -> drop caption band
suren: photos embedded in text page -> largest non-text connected region
"""
import json, pathlib, re, sys
import numpy as np
from PIL import Image
import cv2

ROOT = pathlib.Path.home() / "fujian-tcm"
PAGES = ROOT / "pages"
OCR = ROOT / "ocr"
OUT = ROOT / "site_data" / "img"
OUT.mkdir(parents=True, exist_ok=True)

QUALITY = 82
MAXW = 900


def save_webp(img, name):
    if img.width > MAXW:
        h = int(img.height * MAXW / img.width)
        img = img.resize((MAXW, h), Image.LANCZOS)
    img.convert("RGB").save(OUT / f"{name}.webp", "WEBP", quality=QUALITY)
    return f"{name}.webp"


def trim_margins(img, frac=0.055):
    w, h = img.size
    return img.crop((int(w*frac), int(h*frac*0.7), int(w*(1-frac)), int(h*(1-frac*0.9))))


def boxes_of(book, pagefile):
    jf = OCR / book / pagefile
    if not jf.exists():
        return []
    j = json.loads(jf.read_text())
    res = j.get("res", {})
    boxes = res.get("rec_polys") or res.get("rec_boxes") or []
    out = []
    for b in boxes:
        arr = np.array(b, dtype=float).reshape(-1, 2)
        x0, y0 = arr.min(0); x1, y1 = arr.max(0)
        out.append((x0, y0, x1, y1))
    return out


def crop_caise(img, boxes):
    """plate page: find caption band (the few text lines) and cut it off."""
    w, h = img.size
    if not boxes:
        return trim_margins(img)
    # caption = text lines; photo = the rest
    ytext = [b for b in boxes]
    top = min(b[1] for b in ytext); bot = max(b[3] for b in ytext)
    # caption near top -> crop below it; near bottom -> crop above
    if bot < h * 0.25:
        return img.crop((int(w*0.03), int(bot + h*0.02), int(w*0.97), int(h*0.97)))
    if top > h * 0.75:
        return img.crop((int(w*0.03), int(h*0.03), int(w*0.97), int(top - h*0.02)))
    return trim_margins(img)


def crop_suren(img, boxes):
    """largest connected non-text, non-white region = photo."""
    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]
    # non-near-white mask
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    mask = (gray < 235).astype(np.uint8) * 255
    # remove text regions
    for (x0, y0, x1, y1) in boxes:
        cv2.rectangle(mask, (int(x0)-4, int(y0)-4), (int(x1)+4, int(y1)+4), 0, -1)
    # also remove thin colored decorations (thin rows) via morphology: keep big blobs
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw > w*0.2 and bh > h*0.12 and area > w*h*0.03:
            score = area
            if best is None or score > best[0]:
                best = (score, x, y, bw, bh)
    if not best:
        return None
    _, x, y, bw, bh = best
    pad = int(w*0.01)
    return img.crop((max(0, x-pad), max(0, y-pad), min(w, x+bw+pad), min(h, y+bh+pad)))


def main():
    ents = [json.loads(l) for l in open(ROOT / "entries.jsonl")]
    manifest = {}
    for e in ents:
        if e["entry_type"] != "herb":
            continue
        book = e["book"]
        pagefiles = e.get("pages", [])
        img = None
        key = re.sub(r"[^\w一-鿿-]", "_", book + "__" + e["name"])
        if book == "fujian-zhongcaoyao-vol1":
            # plate page = last page of entry
            pf = pagefiles[-1].replace(".json", ".png")
            fp = PAGES / book / pf
            if fp.exists():
                img = trim_margins(Image.open(fp))
        elif book == "caise-tupu-1992":
            pf = pagefiles[-1].replace(".json", ".png")
            fp = PAGES / book / pf
            if fp.exists() and e.get("plate_caption"):
                img = crop_caise(Image.open(fp), boxes_of(book, pagefiles[-1]))
        elif book == "suren-tuji-2010":
            pf = pagefiles[0].replace(".json", ".png")
            fp = PAGES / book / pf
            if fp.exists():
                img = crop_suren(Image.open(fp), boxes_of(book, pagefiles[0]))
        if img is not None:
            fname = save_webp(img, key)
            manifest[key] = {"file": fname, "book": book, "name": e["name"],
                             "w": img.width, "h": img.height}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"cropped {len(manifest)} images")


if __name__ == "__main__":
    main()
