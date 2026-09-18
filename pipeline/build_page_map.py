#!/usr/bin/env python3
"""Extract printed page numbers from OCR page files -> page_map.json {book:{file:n}}"""
import json, re, os, glob

ROOT = "/home/jk/fujian-tcm"
PNUM = re.compile(r"^\s*[·\-—~=.。·]*\s*(\d{1,4})\s*[·\-—~=.。·]*\s*$")
PNUM2 = re.compile(r"^[（(【\[]\s*(\d{1,4})\s*[）)】\]]$")

def page_num(texts):
    cands = []
    for t in texts[-4:]:
        m = PNUM.match(t.strip()) or PNUM2.match(t.strip())
        if m:
            cands.append(int(m.group(1)))
    if not cands:
        for t in texts[:4]:
            m = PNUM.match(t.strip()) or PNUM2.match(t.strip())
            if m:
                cands.append(int(m.group(1)))
    return cands[0] if cands else None

out = {}
for book in sorted(os.listdir(f"{ROOT}/ocr")):
    m = {}
    files = sorted(glob.glob(f"{ROOT}/ocr/{book}/page-*.json"),
                   key=lambda p: int(re.search(r"page-(\d+)", p).group(1)))
    for fp in files:
        try:
            texts = json.load(open(fp, encoding="utf-8"))["res"]["rec_texts"]
        except Exception:
            continue
        n = page_num(texts)
        if n:
            m[os.path.basename(fp)] = n
    # interpolate gaps: unmapped page between two mapped pages
    idx = {os.path.basename(f): int(re.search(r"page-(\d+)", f).group(1)) for f in files}
    names = [os.path.basename(f) for f in files]
    for i, nm in enumerate(names):
        if nm in m:
            continue
        # find nearest mapped neighbors
        lo = next((names[j] for j in range(i - 1, -1, -1) if names[j] in m), None)
        hi = next((names[j] for j in range(i + 1, len(names)) if names[j] in m), None)
        if lo and hi:
            gap = idx[hi] - idx[lo]
            if m[hi] - m[lo] == gap:        # printed numbers step in sync
                m[nm] = m[lo] + (idx[nm] - idx[lo])
    out[book] = m
    print(book, len(m), "pages mapped")

json.dump(out, open(f"{ROOT}/page_map.json", "w", encoding="utf-8"), ensure_ascii=False)
