#!/usr/bin/env python3
import json, pathlib, sys, time
from paddleocr import PaddleOCR

ROOT = pathlib.Path.home() / "fujian-tcm"
PAGES = ROOT / "pages"
OUT = ROOT / "ocr"
BATCH = 8

ocr = PaddleOCR(lang="ch", use_doc_orientation_classify=False,
                use_doc_unwarping=False, use_textline_orientation=True)

imgs = [p for p in sorted(PAGES.glob("*/*.png"))
        if not (OUT / p.parent.name / (p.stem + ".json")).exists()]
print(f"to OCR: {len(imgs)} pages", flush=True)

def dump(img, res):
    out = OUT / img.parent.name / (img.stem + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = res.json if hasattr(res, "json") else {"res": {}}
    if isinstance(payload, dict):
        payload["book"] = img.parent.name
        payload["page"] = img.stem
    out.write_text(json.dumps(payload, ensure_ascii=False))

t0 = time.time()
for i in range(0, len(imgs), BATCH):
    chunk = imgs[i:i+BATCH]
    try:
        results = list(ocr.predict([str(p) for p in chunk]))
        for img, res in zip(chunk, results):
            dump(img, res)
    except Exception as e:
        print(f"batch {i} failed: {e}; falling back to per-page", flush=True)
        for img in chunk:
            try:
                dump(img, list(ocr.predict(str(img)))[0])
            except Exception as e2:
                print(f"  page {img} failed: {e2}", flush=True)
    if (i // BATCH) % 10 == 0:
        done = i + len(chunk)
        rate = done / max(time.time() - t0, 1)
        eta = (len(imgs) - done) / max(rate, 0.01)
        print(f"{done}/{len(imgs)}  {rate:.2f}p/s  eta {eta/60:.1f}min", flush=True)
print("ALL DONE", flush=True)
