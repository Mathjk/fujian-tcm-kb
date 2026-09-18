#!/usr/bin/env python3
"""Parse OCR'd TCM books into structured entries. -> entries.jsonl"""
import json, pathlib, re, sys
from collections import Counter

ROOT = pathlib.Path.home() / "fujian-tcm"
OCR = ROOT / "ocr"
OUT = ROOT / "entries.jsonl"

CN = r"一-鿿"
FIELD_LABELS = ["别名", "別名", "又名", "来源", "植物形态", "形态", "生境", "分布", "采收", "采制",
                "性状", "化学成分", "成分", "药理", "性味功能", "性味", "功能主治", "功用",
                "功效", "主治", "应用", "用法用量", "用量", "验方", "附方", "附注", "速认指南",
                "处方", "制法", "用法", "疗效", "注意", "禁忌"]
LABEL_RE = re.compile(r"^(" + "|".join(FIELD_LABELS) + r")\s*[:：  ]*")
PAGE_NUM_RE = re.compile(r"^[0-9０-９]{1,4}$")
ENTRY_HEAD_RE = re.compile(r"^\d{1,3}[.、．]\s*[" + CN + r"]")
LATIN_RE = re.compile(r"[A-Z][a-z]+(?:\s+[a-z][a-z\-.()]+)+")
FAMILY_RE = re.compile(r"[（(][^（）()]{1,12}科[)）]")
CAT_RE = re.compile(r"^[一二三四五六七八九十]+、")
TOC_NUM_RE = re.compile(r"[(（]\s*\d{1,3}\s*[)）]")


def load_pages(book):
    d = OCR / book
    pages = []
    for f in sorted(d.glob("*.json")):
        try:
            j = json.loads(f.read_text())
        except Exception:
            continue
        res = j.get("res", {})
        texts = res.get("rec_texts", [])
        scores = res.get("rec_scores", [])
        lines = [t.strip() for t, s in zip(texts, scores) if s >= 0.5 and t.strip()]
        pnum = None
        # printed page number is usually the last line; tolerate 1-2 trailing
        # OCR-debris lines (e.g. 'à') after the digits
        for tail in range(len(lines) - 1, max(len(lines) - 4, -1), -1):
            if PAGE_NUM_RE.match(lines[tail]):
                pnum = int(lines.pop(tail))
                break
        pages.append({"file": f.name, "lines": lines, "pnum": pnum})
    return pages


def norm_label(line):
    s = re.sub(r"\s+", "", line)
    m = LABEL_RE.match(s)
    if m:
        return m.group(1), s[m.end():]
    return None, line


def assign_fields(ent, lines):
    cur = None
    for line in lines:
        lab, rest = norm_label(line)
        if lab:
            cur = lab
            ent["fields"].setdefault(lab, "")
            if rest:
                ent["fields"][lab] += rest
        elif cur:
            ent["fields"][cur] += " " + line.strip()
        else:
            ent["fields"].setdefault("_head", "")
            ent["fields"]["_head"] += " " + line.strip()


# ---------- suren-tuji-2010 ----------

SUREN_HEAD_RE = re.compile(r"^[^" + CN + r"]{0,3}[" + CN + r"]{1,8}[药约]([·・，,][" + CN + r"]{1,8}.{0,3})?[^" + CN + r"]{0,2}$")
SUREN_LAB_RE = re.compile(r"^(别名|来源|生境|采收|速认指南|功用|验方)")


def parse_suren(pages):
    entries = []
    cur = None
    for pg in pages:
        lines = pg["lines"]
        if len(lines) < 5:
            continue
        first = re.sub(r"\s+", "", lines[0])
        head_match = SUREN_HEAD_RE.match(first) and len(first) <= 18
        # fallback: header mis-OCR'd — first line is herb name, labels follow soon
        fallback = (not head_match and len(lines) >= 18
                    and re.match(r"^[" + CN + r"]{2,6}$", first)
                    and any(SUREN_LAB_RE.match(re.sub(r"\s+", "", l)) for l in lines[1:6]))
        if head_match or fallback:
            if head_match:
                category = first
                name = re.sub(r"\s+", "", lines[1]) if len(lines) > 1 else "?"
                start = 2
            else:
                category = entries[-1]["category"] if entries else "?"
                name = first
                start = 1
            if not re.match(r"^[" + CN + r"]{1,10}$", name):
                name = "?"
            cur = {"book": "suren-tuji-2010", "entry_type": "herb", "name": name,
                   "category": category, "fields": {}, "pages": [pg["file"]]}
            assign_fields(cur, lines[start:])
            entries.append(cur)
        elif cur is not None:
            cur["pages"].append(pg["file"])
            assign_fields(cur, lines)
    return entries


# ---------- caise-tupu-1992 ----------

def is_plate_caise(lines):
    body = [l for l in lines if not PAGE_NUM_RE.match(l)]
    return 1 <= len(body) <= 3 and any(ENTRY_HEAD_RE.match(re.sub(r"\s+", "", l)) for l in body)


def parse_caise(pages):
    entries = []
    cur = None
    for pg in pages:
        lines = pg["lines"]
        if is_plate_caise(lines):
            if cur:
                cur["pages"].append(pg["file"])
                cur["plate_caption"] = " ".join(lines)
                entries.append(cur)
                cur = None
            continue
        first = re.sub(r"\s+", "", lines[0]) if lines else ""
        if ENTRY_HEAD_RE.match(first):
            if cur:
                entries.append(cur)
            name = re.sub(r"^\d{1,3}[.、．]\s*", "", first)
            name = re.split(r"[A-Z(（]", name)[0].strip()
            cur = {"book": "caise-tupu-1992", "entry_type": "herb", "name": name,
                   "head_raw": first, "fields": {}, "pages": [pg["file"]]}
            lines = lines[1:]
        if cur is None:
            continue
        if pg["file"] not in cur["pages"]:
            cur["pages"].append(pg["file"])
        assign_fields(cur, lines)
    if cur:
        entries.append(cur)
    return entries


# ---------- fujian-zhongcaoyao-vol1 ----------

def is_plate_fj1(lines):
    tail = " ".join(lines[-4:])
    return bool(FAMILY_RE.search(tail) and LATIN_RE.search(tail))


FJ1_MARK_RE = re.compile(r"^(别名|采收|性味功能|性味|应用|生境|分布|功用|主治)")

def _fj1_name_line(s):
    """first line of a text page that looks like a herb name"""
    return bool(re.match(r"^[" + CN + r"]{1,8}$", s))


def parse_fj1(pages):
    entries = []
    vet_entries = []
    buf, buf_pages = [], []

    # first pass: locate last plate page — everything after it is tail content
    plate_idx = [i for i, pg in enumerate(pages) if is_plate_fj1(pg["lines"])]
    last_plate = plate_idx[-1] if plate_idx else len(pages)

    def flush_buf():
        nonlocal buf, buf_pages
        if not buf:
            return
        nm = buf[0].strip()
        ent = {"book": "fujian-zhongcaoyao-vol1", "entry_type": "herb",
               "name": nm, "fields": {}, "pages": list(buf_pages)}
        # fix OCR-dropped 别名 label: lines like "名三义虎" -> 别名
        fixed = []
        for ln in buf[1:]:
            m2 = re.match(r"^名([" + CN + r"、，,]{2,20})$", re.sub(r"\s+", "", ln))
            fixed.append("别名" + m2.group(1) if (m2 and "别名" not in ent["fields"]) else ln)
        assign_fields(ent, fixed)
        entries.append(ent)
        buf, buf_pages = [], []

    in_index = False
    tail_cur = None
    tail_cat = None
    CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
    circled_re = re.compile(r"^[" + CIRCLED + "]")
    paren_num_re = re.compile(r"^[（(]\d{1,2}[)）]")
    SECTION_RE = re.compile(r"^[" + CN + r"]{2,14}(中草药|处方选|验方|应用)$")
    ITEM_KEY_RE = re.compile(r"^[" + CN + r"]{1,8}[：:]")
    # pure-CN lines that are really usage instructions, not disease headings
    INSTR_LINE = re.compile(
        r"^(均用|加水|水煎|煎取|煎成|共研|共捣|捣烂|研末|细末|去渣|候温|候冷|灌服|内服|吞服|"
        r"冲服|调服|炖服|送服|外敷|外洗|涂抹|搽|涂患处|洗患处|敷患处|每次|每日|日服|分服|"
        r"鲜品|干品|捣烂外敷|加盐|加醋|加酒|黄酒|开水|温水|冷水|米汤|蜂蜜|红糖|白糖|冰糖|"
        r"用时|药量|用量|酌减|酌加|小儿酌减|孕妇|忌|慎用|禁食|温服|冷服|热服|空腹|饭后|"
        r"睡前|早晚各|连服|连用|疗程|引|为引|作引|药引|猪骨|猪肉|鸡肉|鸡蛋|鸭蛋|糯米|粳米|"
        r"大米|小米|赤小豆|绿豆|黄豆|豆腐|饴糖|麦芽糖|蜂蜜少许|食盐|食油|麻油|菜油|茶油|"
        r"香油|猪油|生姜|葱白|大蒜|胡椒|辣椒|米醋|白酒|米酒|啤酒|酒精|食盐少许|冰糖少许)")

    def flush_tail():
        nonlocal tail_cur
        if tail_cur:
            vet_entries.append(tail_cur)
            tail_cur = None

    for pidx, pg in enumerate(pages):
        lines = pg["lines"]
        if not lines:
            continue
        # index section: dense '名字+页码' patterns
        idxish = sum(1 for l in lines if re.search(r"[" + CN + r"]\d{2,3}$", re.sub(r"\s+", "", l)))
        if idxish >= 8 and len(lines) >= 12:
            in_index = True
            flush_buf(); flush_tail()
            continue
        if in_index:
            continue
        # tail content only after the last plate page
        if pidx > last_plate:
            has_herb_label = any(FJ1_MARK_RE.match(re.sub(r"\s+", "", l)) for l in lines)
        else:
            has_herb_label = True   # before last plate: always herb path
        is_tail_page = pidx > last_plate and not has_herb_label
        if is_tail_page:
            flush_buf()
            for l in lines:
                s = re.sub(r"\s+", "", l)
                if not s or s.isdigit():
                    continue
                if SECTION_RE.match(s) and not circled_re.match(s):
                    flush_tail()
                    tail_cat = s
                    continue
                # split embedded circled markers: "①xx②yy" -> two items
                if any(c in s for c in CIRCLED):
                    segs = re.split("(?=[" + CIRCLED + "])", s)
                    for sg in segs:
                        if not sg:
                            continue
                        if not circled_re.match(sg) and tail_cur is not None and tail_cur["items"]:
                            tail_cur["items"][-1]["text"] += sg
                            continue
                        if tail_cur is None:
                            tail_cur = {"book": "fujian-zhongcaoyao-vol1", "entry_type": "disease",
                                        "name": "_tail", "category": tail_cat, "items": [], "pages": []}
                        tail_cur["items"].append({"text": sg})
                        if pg["file"] not in tail_cur["pages"]:
                            tail_cur["pages"].append(pg["file"])
                    continue
                if paren_num_re.match(s) or (ITEM_KEY_RE.match(s) and "除害" in (tail_cat or "")):
                    if tail_cur is None:
                        tail_cur = {"book": "fujian-zhongcaoyao-vol1", "entry_type": "disease",
                                    "name": "_tail", "category": tail_cat, "items": [], "pages": []}
                    tail_cur["items"].append({"text": s})
                    if pg["file"] not in tail_cur["pages"]:
                        tail_cur["pages"].append(pg["file"])
                elif re.match(r"^[" + CN + r"]{2,14}$", s) and not INSTR_LINE.match(s):
                    flush_tail()
                    tail_cur = {"book": "fujian-zhongcaoyao-vol1", "entry_type": "disease",
                                "name": s, "category": tail_cat, "items": [], "pages": [pg["file"]]}
                elif tail_cur is not None:
                    if tail_cur["items"]:
                        tail_cur["items"][-1]["text"] += s
                    else:
                        tail_cur["items"].append({"text": s})
                    if pg["file"] not in tail_cur["pages"]:
                        tail_cur["pages"].append(pg["file"])
            continue
        if is_plate_fj1(lines):
            tail = " ".join(lines[-4:])
            fam = FAMILY_RE.search(tail)
            name = None
            if fam:
                before = tail[:fam.start()].split()
                if before:
                    name = before[-1]
            if buf:
                flush_buf()
                ent = entries[-1]
                ent["pages"].append(pg["file"])
                if fam:
                    ent["family"] = fam.group(0).strip("（）()")
                latin_txt = tail[fam.end():].strip() if fam else ""
                latin_txt = re.sub(r"\s*\d+$", "", latin_txt).strip()
                if latin_txt:
                    ent["latin"] = latin_txt
                if name:
                    ent["plate_name"] = name
                if not re.match(r"^[" + CN + r"]{1,8}$", ent["name"]) and name:
                    ent["name"] = name
            continue
        first = re.sub(r"\s+", "", lines[0])
        # new herb text page: short name line + field marker within next 3 lines
        body_has_marker = any(FJ1_MARK_RE.match(re.sub(r"\s+", "", l)) for l in lines[1:4])
        if buf and _fj1_name_line(first) and body_has_marker and any(
                k in ("应用", "性味功能", "采收") for k in
                [re.match(r"^(" + "|".join(FIELD_LABELS) + r")", re.sub(r"\s+", "", l)).group(1)
                 for l in buf if re.match(r"^(" + "|".join(FIELD_LABELS) + r")", re.sub(r"\s+", "", l))]):
            flush_buf()
        if not buf:
            buf, buf_pages = list(lines), [pg["file"]]
        else:
            buf += lines
            buf_pages.append(pg["file"])
    flush_buf()
    flush_tail()
    return entries + vet_entries


# ---------- fangxuan ----------

RX_FIELD = ["处方", "制法", "用法", "疗效", "来源", "附注", "注意", "加减", "方解", "组成"]
RX_LABEL_RE = re.compile(r"^(" + "|".join(RX_FIELD) + r")[一二三四五六七八九十\d]*\s*[:：  ]*")


def parse_fangxuan(book):
    pages = load_pages(book)
    entries = []
    cur_disease = None
    cur_field = None

    def close():
        nonlocal cur_disease
        if cur_disease and cur_disease["formulas"]:
            entries.append({"book": book, "entry_type": "disease",
                            "name": cur_disease["disease"],
                            "formulas": cur_disease["formulas"],
                            "pages": cur_disease.get("pages", [])})
        cur_disease = None

    for pg in pages:
        lines = pg["lines"]
        for i, line in enumerate(lines):
            s = re.sub(r"\s+", "", line)
            m = RX_LABEL_RE.match(s)
            if m:
                lab = m.group(1)
                rest = s[m.end():]
                if lab == "处方":
                    if cur_disease is None:
                        cur_disease = {"disease": "_front", "formulas": [], "pages": []}
                    fm = {"index": len(cur_disease["formulas"]) + 1,
                          "fields": {"处方": rest}, "page": pg["file"]}
                    cur_disease["formulas"].append(fm)
                    cur_field = ("处方", fm)
                elif cur_disease and cur_disease["formulas"]:
                    fm = cur_disease["formulas"][-1]
                    fm["fields"].setdefault(lab, "")
                    if rest:
                        fm["fields"][lab] += rest
                    cur_field = (lab, fm)
                else:
                    cur_field = None
            else:
                is_head = (re.match(r"^[" + CN + r"·、]{2,15}$", s)
                           and not re.match(r"^\d", s))
                if is_head:
                    nxt = " ".join(lines[i+1:i+4])
                    if re.search(r"处方|\d[.、]", nxt):
                        close()
                        cur_disease = {"disease": s, "formulas": [], "pages": [pg["file"]]}
                        cur_field = None
                        continue
                if cur_disease and cur_disease["formulas"]:
                    if pg["file"] not in cur_disease["pages"]:
                        cur_disease["pages"].append(pg["file"])
                    if cur_field:
                        lab, fm = cur_field
                        fm["fields"][lab] += " " + line.strip()
    close()
    return entries


# ---------- fujian-chufang-1971: TOC names as anchors (normalized) ----------

_CC = None
def t2s(s):
    global _CC
    if _CC is None:
        from opencc import OpenCC
        _CC = OpenCC("t2s")
    return _CC.convert(s)

EXTRA_FOLD = str.maketrans({"痺": "痹", "瘧": "疟", "蟯": "蛲", "菰": "菇", "棟": "楝",
                            "朁": "骨", "蕁": "荨", "蔴": "麻", "癩": "癞", "疥": "疥"})

def norm_cn(s):
    s = t2s(s).translate(EXTRA_FOLD)
    return re.sub(r"[^" + CN + r"]", "", s)


def parse_chufang():
    book = "fujian-chufang-1971"
    pages = load_pages(book)

    toc_idx = []
    for idx, pg in enumerate(pages[:40]):
        lines = pg["lines"]
        if not lines:
            continue
        tocish = sum(1 for l in lines if TOC_NUM_RE.search(l))
        if len(lines) > 8 and tocish / len(lines) >= 0.25:
            toc_idx.append(idx)
    body_start = (max(toc_idx) + 1) if toc_idx else 18

    toc = []
    cur_cat = None
    pend = None
    for idx in toc_idx:
        for l in pages[idx]["lines"]:
            s = re.sub(r"\s+", "", l)
            if CAT_RE.match(s):
                cur_cat = re.sub(r"[.·…•(（\d)）]+$", "", s)
                pend = None
                continue
            mnum = re.match(r"^[.·…•\s]*[(（]\s*(\d{1,3})\s*[)）]\s*$", s)
            if mnum and pend:
                toc.append((pend, int(mnum.group(1)), cur_cat))
                pend = None
                continue
            inline = re.match(r"^([" + CN + r"·、（）()]{2,20})[.·…•]*[(（]\s*(\d{1,3})\s*[)）]$", s)
            if inline:
                toc.append((inline.group(1), int(inline.group(2)), cur_cat))
                pend = None
                continue
            if re.match(r"^[" + CN + r"·、（）()]{1,25}[·….。、]*$", s) and re.search(r"[" + CN + r"]", s):
                clean = re.sub(r"[·….。、]+$", "", s)
                pend = (pend + clean) if pend else clean
            else:
                pend = None

    # ---- TOC post-fix: drop fragments, split glued names ----
    nameset = {norm_cn(n) for n, _, _ in toc}
    body_all_norm = []
    body_all_raw = []
    for pg in pages[body_start:]:
        for l in pg["lines"]:
            s0 = re.sub(r"\s+", "", l)
            body_all_norm.append(norm_cn(s0))
            body_all_raw.append(s0)
    body_set = set(body_all_norm)

    fixed_toc = []
    for n, p, c in toc:
        nn = norm_cn(n)
        if len(nn) < 2:
            continue                      # OCR fragment like '师'
        if len(nn) > 12:                  # likely two names glued
            done = False
            for k in range(len(n) - 1, 1, -1):
                pre, suf = n[:k], n[k:]
                if norm_cn(pre) in nameset and norm_cn(pre) != nn:
                    fixed_toc.append((suf, p, c))
                    done = True
                    break
                if norm_cn(pre) in body_set and norm_cn(suf) in body_set:
                    fixed_toc.append((pre, p, c))
                    fixed_toc.append((suf, p, c))
                    done = True
                    break
            if done:
                continue
        fixed_toc.append((n, p, c))
    toc = fixed_toc

    names = [n for n, _, _ in toc]
    cat_of = {n: c for n, _, c in toc}
    pnum_of = {n: p for n, p, _ in toc}
    # normalized name -> raw
    norm2raw = {}
    for n in names:
        norm2raw.setdefault(norm_cn(n), n)
    norm_names = sorted(norm2raw.keys(), key=len, reverse=True)

    # printed -> pdf idx
    pmap = {}
    for idx, pg in enumerate(pages):
        if idx >= body_start and pg["pnum"] is not None:
            pmap[pg["pnum"]] = idx

    entries = []
    cur = None
    desc_buf = []
    cur_fx = None
    last_idx_seen = 0
    pending_fallback = []   # unmatched toc names to apply at page start
    pending_set = set()

    def open_disease(hit_raw, rest, pgfile):
        nonlocal cur, desc_buf, cur_fx, last_idx_seen
        finish()
        cur = {"book": book, "entry_type": "disease", "name": hit_raw,
               "category": cat_of.get(hit_raw), "printed_page": pnum_of.get(hit_raw),
               "groups": [], "trailing": "", "pages": [pgfile]}
        desc_buf = [rest] if rest else []
        cur_fx = None
        last_idx_seen = 0

    def finish():
        nonlocal cur, desc_buf, cur_fx, last_idx_seen
        if cur is not None:
            cur["trailing"] = "".join(desc_buf)
            entries.append(cur)
        cur, desc_buf, cur_fx, last_idx_seen = None, [], None, 0

    # expected pdf page for each toc name
    exp_idx = {n: pmap.get(pnum_of[n]) for n in names}
    # printed->pdf offset for pages whose pnum failed to parse
    import statistics
    _offs = [i - p for p, i in pmap.items()]
    OFF = round(statistics.median(_offs)) if _offs else 17

    def exp_page(n):
        if exp_idx.get(n) is not None:
            return exp_idx[n]
        p = pnum_of.get(n)
        return (p + OFF) if p else None

    # shared heading test — used by the rescue simulation AND the main loop.
    # A real heading is a bare name: reject sentences ("…贫血。"), allow glued
    # forms "name：desc" and "namename".
    def heading_hit(s):
        sn = norm_cn(s)
        pureish = bool(re.fullmatch("[" + CN + "·、（）()]{2,25}", s))
        colon_head = bool(re.match("^[" + CN + "]{2,12}[：:]", s))
        if pureish and sn in norm2raw:
            return norm2raw[sn]
        if ("。" not in s and "；" not in s) or colon_head:
            for nn in norm_names:
                if len(nn) >= 2 and sn.startswith(nn):
                    rest_n = sn[len(nn):]
                    if rest_n.startswith(nn) or rest_n[:1] in "：:，,":
                        return norm2raw[nn]
        return None

    # ---- fuzzy heading rescue ----
    # names whose big-font headings were split or dropped by OCR:
    # simulate main matcher; for unfindable names, locate a fragment within
    # the expected page ±1 and splice the proper name in before parsing.
    def main_would_hit(nn):
        for l in body_all_raw:
            if heading_hit(l) and norm_cn(heading_hit(l)) == nn:
                return True
        return False

    pure_cn = lambda t: bool(re.fullmatch("[" + CN + r"]{1,4}", t))
    rescued = []
    for n in names:
        nn = norm_cn(n)
        if main_would_hit(nn):
            continue
        pi = exp_page(n)
        if pi is None:
            continue
        done = False
        # pass A: joined consecutive short pure-CN lines == name
        for pj in (pi, pi - 1, pi + 1):
            if pj < body_start or pj >= len(pages):
                continue
            lines = pages[pj]["lines"]
            acc = []
            for i, l in enumerate(lines):
                s = norm_cn(re.sub(r"\s+", "", l))
                acc.append((i, s) if pure_cn(s) else None)
                joined = ""
                for j in range(len(acc) - 1, -1, -1):
                    if acc[j] is None:
                        break
                    joined = acc[j][1] + joined
                    if joined == nn:
                        st = acc[j][0]
                        pages[pj]["lines"][st] = n
                        for q in range(st + 1, i + 1):
                            pages[pj]["lines"][q] = ""
                        done = True
                        break
                    if len(joined) >= len(nn):
                        break
                if done:
                    break
            if done:
                break
        # pass B: single short line that is a suffix of the name
        if not done:
            for pj in (pi, pi - 1, pi + 1):
                if pj < body_start or pj >= len(pages):
                    continue
                for i, l in enumerate(pages[pj]["lines"]):
                    s = norm_cn(re.sub(r"\s+", "", l))
                    if 1 <= len(s) <= 2 and pure_cn(s) and nn.endswith(s):
                        pages[pj]["lines"][i] = n
                        done = True
                        break
                if done:
                    break
        # pass C: heading lost entirely. If the page starts with unclassifiable
        # OCR garbage, the heading died at the top -> inject at line 0.
        # Otherwise the page continues a previous disease -> inject before the
        # first description opener (俗称/系由/治疗…) or the next real heading.
        if not done:
            lines = pages[pi]["lines"]
            NUML = re.compile(r"^(\d{1,2})[.、．]")
            DESCOP = re.compile(r"^\s*(俗称|系由|本病|凡是|是为|治疗|预防|临床)")
            DOSE = re.compile(r"[錢两克分斤枚粒条片]|水煎|煎服|捣|敷|炖|冲服|外用|灌服|服")

            def classified(t):
                t2 = re.sub(r"\s+", "", t)
                return bool(NUML.match(t2) or DESCOP.match(t2)
                            or DOSE.search(t2) or heading_hit(t2))

            gi = 0
            while gi < len(lines) and not classified(lines[gi]):
                gi += 1
            ins = 0
            if gi == 0:  # page top is already content -> heading lost mid-page
                for i, l in enumerate(lines):
                    if DESCOP.match(l):
                        ins = i
                        break
                else:
                    for i, l in enumerate(lines):
                        if heading_hit(re.sub(r"\s+", "", l)):
                            ins = i
                            break
            pages[pi]["lines"].insert(ins, n)
        rescued.append(n)
    if rescued:
        print(f"[chufang] rescued headings: {rescued}", file=sys.stderr)

    for idx, pg in enumerate(pages):
        if idx < body_start:
            continue

        for li, line in enumerate(pg["lines"]):
            s = re.sub(r"\s+", "", line)
            hit = heading_hit(s)
            if hit:
                rest = s[len(hit):]  # t2s/fold are 1:1 so raw offset == norm offset
                open_disease(hit, rest, pg["file"])
                continue
            if cur is None:
                continue
            num = re.match(r"^(\d{1,2})[.、．]\s*(.+)", s)
            doseish = re.search(r"[錢两克分斤枚粒条片]|水煎|煎服|捣|敷|炖|冲服|外用|服", s)
            # an open formula whose text doesn't end with terminal punctuation
            # is mid-sentence — the next line continues it (page-break tails)
            cont = (cur_fx is not None
                    and not cur_fx["text"].rstrip().endswith(("。", "！", "？", "；", "：", ":")))
            if num:
                n = int(num.group(1))
                if n <= last_idx_seen or cur_fx is None:
                    cur["groups"].append({"desc": "".join(desc_buf), "items": []})
                    desc_buf = []
                cur_fx = {"index": n, "text": num.group(2)}
                if cur["groups"]:
                    cur["groups"][-1]["items"].append(cur_fx)
                else:
                    cur["groups"].append({"desc": "".join(desc_buf), "items": [cur_fx]})
                    desc_buf = []
                last_idx_seen = n
            elif cur_fx is not None and (doseish or cont):
                cur_fx["text"] += line.strip()
            elif s in ("治疗", "治療", "预防", "預防"):
                continue  # section marker, not content
            else:
                cur_fx = None
                last_idx_seen = 0
                desc_buf.append(s)
    finish()

    # merge duplicate-name entries (same disease hit twice)
    merged = []
    seen = {}
    for e in entries:
        if e["name"] in seen and not e.get("unmatched_heading"):
            prev = seen[e["name"]]
            prev["groups"] += e["groups"]
            prev["trailing"] = (prev["trailing"] + e["trailing"]).strip()
            prev["pages"] = sorted(set(prev["pages"] + e["pages"]))
        else:
            seen[e["name"]] = e
            merged.append(e)
    entries = merged

    got = {e["name"] for e in entries}
    missing = [n for n in names if n not in got]
    # fallback pass: create stub entries at expected pages for unmatched names
    for n in missing:
        pi = exp_page(n)
        if pi is not None:
            entries.append({"book": book, "entry_type": "disease", "name": n,
                            "category": cat_of.get(n), "printed_page": pnum_of.get(n),
                            "groups": [], "trailing": "", "pages": [pages[pi]["file"]],
                            "unmatched_heading": True})
    entries.sort(key=lambda e: e.get("printed_page") or 9999)
    if missing:
        print(f"[chufang] fallback stubs for {len(missing)}: {missing[:15]}", file=sys.stderr)
    return entries


def main():
    all_entries = []
    all_entries += parse_fangxuan("fangxuan-vol3-1986")
    all_entries += parse_fangxuan("fangxuan-2")
    all_entries += parse_chufang()
    all_entries += parse_caise(load_pages("caise-tupu-1992"))
    all_entries += parse_suren(load_pages("suren-tuji-2010"))
    all_entries += parse_fj1(load_pages("fujian-zhongcaoyao-vol1"))

    with open(OUT, "w") as f:
        for e in all_entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    c = Counter((e["book"], e["entry_type"]) for e in all_entries)
    for (b, t), n in sorted(c.items()):
        print(f"{b:32s} {t:8s} {n}")
    print(f"TOTAL {len(all_entries)}")


if __name__ == "__main__":
    main()
