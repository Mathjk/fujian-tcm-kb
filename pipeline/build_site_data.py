#!/usr/bin/env python3
"""kb.json + entries.jsonl + img manifest -> site data files.

Outputs into ~/fujian-tcm/site_data/:
  herbs.json diseases.json formulas.json meta.json   (imported by Astro)
  graph.json search.json                             (fetched client-side)
"""
import json, pathlib, re
from collections import Counter, defaultdict

ROOT = pathlib.Path.home() / "fujian-tcm"
SD = ROOT / "site_data"
SD.mkdir(exist_ok=True)

JUNK_NAMES = {
    "轻轻松松学用药", "福建中草药", "中草药速认图集", "常用中草药彩色图谱",
    "中草药方选", "福建中草药处方", "目录", "前言", "凡例", "编写说明",
    "内容提要", "出版说明", "说明", "索引", "附录", "师",
}
FIELD_LABELS = ["别名", "来源", "植物形态", "生境", "分布", "采制", "采收",
                "性状", "性味", "性味功能", "功用", "功能主治", "应用",
                "化学成分", "速认指南", "验方", "注意", "附注"]
# display order for herb detail sections
SECTION_ORDER = ["别名", "来源", "植物形态", "生境", "分布", "性状", "采制", "采收",
                 "化学成分", "性味", "性味功能", "功用", "功能主治", "应用",
                 "速认指南", "验方", "注意", "附注"]

kb = json.loads((ROOT / "kb.json").read_text())
entries = [json.loads(l) for l in open(ROOT / "entries.jsonl")]
manifest = json.loads((SD / "img" / "manifest.json").read_text())


def imgkey(book, name):
    return re.sub(r"[^\w一-鿿-]", "_", book + "__" + name)


# entry lookup: book -> normalized name -> entry
def norm(s):
    return re.sub(r"[·•．.。、,，;；:：\s\-—_()（）\[\]【】]", "", s or "")

by_book = defaultdict(list)
for e in entries:
    by_book[e["book"]].append(e)

entry_map = {}
for e in entries:
    entry_map[(e["book"], norm(e["name"]))] = e

# ---------- herbs ----------
INSTR_PAT = re.compile(
    r"患处|去渣|等量|任选|过滤|均用|少许|杀虫|灭|孑孓|子子|喷洒|投入|捣烂|捣|绞汁|"
    r"送服|水煎|煎成|浸泡|焙干|晒干|研末|细末|外敷|内服|吞服|炖服|调服|冲服|或|日|次")
# OCR/写法 variants of real herbs
VARIANT = {
    "蝉退": "蝉蜕", "板兰根": "板蓝根", "稀签草": "豨莶草", "蕺荣": "蕺菜",
    "铁苋荣": "铁苋菜", "士牛膝根": "土牛膝", "乌鼓莓": "乌蔹莓", "竞州卷柏": "兖州卷柏",
    "篇蓄": "萹蓄", "川栋": "川楝", "狗肝荣": "狗肝菜", "雄黄末": "雄黄",
    "明矾少许": "明矾", "蕃石榴叶": "番石榴叶",
}

herbs_out = []
skipped = []
merge_to = {}   # stub name -> canonical herb name

real_names = {h["name"].strip() for h in kb["herbs"]
              if h.get("fields") and any(k != "_head" for k in h["fields"])
              or h.get("latin") or h.get("family")}

def canon_name(name):
    n = VARIANT.get(name, name)
    if len(n) > 2:
        n = re.sub(r"^(鲜|干)", "", n)
        n = re.sub(r"(末|粉)$", "", n)
    for suf in ("根茎", "全草", "鲜叶", "气根", "根", "叶", "藤", "皮", "仁"):
        if n.endswith(suf) and len(n) > len(suf) + 1 and n[:-len(suf)] in real_names:
            n = n[:-len(suf)]
            break
    return n

for h in kb["herbs"]:
    name = h["name"].strip()
    fields = h.get("fields", {})
    content_labels = [k for k in fields if k != "_head" and any(v.strip() for v in fields[k].values())]
    is_stub = not content_labels and not h.get("latin") and not h.get("family")
    # junk filter: blacklist / overlong / instruction fragments that leaked as stubs
    if (name in JUNK_NAMES or len(name) > 10
            or (is_stub and (INSTR_PAT.search(name) or len(name) < 2))):
        skipped.append(name)
        continue
    if is_stub:
        c = canon_name(name)
        if c != name and c in real_names:
            merge_to[name] = c
            continue
        if c != name:
            name = c  # renamed stub keeps its own entry
            h = dict(h); h["name"] = name

    # find images from each contributing book's entry
    images = []
    nname = norm(name)
    alias_norms = {norm(a) for a in h.get("aliases", [])}
    real_norms = {norm(n) for n in real_names}
    for book in dict.fromkeys(h.get("sources", [])):
        cand = entry_map.get((book, nname))
        if not cand:
            for e in by_book[book]:
                if e["entry_type"] != "herb":
                    continue
                # an entry whose own name is another real herb belongs to that
                # herb — alias collisions (e.g. 石决明 alias 千里光) must not
                # pull its plate/photo across
                if norm(e["name"]) in real_norms and norm(e["name"]) != nname:
                    continue
                if norm(e["name"]) in alias_norms or \
                   any(norm(a) == nname for a in e.get("aliases", [])):
                    cand = e
                    break
        if cand:
            k = imgkey(book, cand["name"])
            if k in manifest:
                images.append({"file": manifest[k]["file"], "book": book})
    # prefer fj1 hand-drawn plate as primary, then photos
    order = {"fujian-zhongcaoyao-vol1": 0, "caise-tupu-1992": 1, "suren-tuji-2010": 2}
    images.sort(key=lambda x: order.get(x["book"], 9))

    # merge same-label fields across books, keep per-book detail for 互证
    sections = []
    for label in SECTION_ORDER:
        if label in fields:
            per_book = {b: v.strip() for b, v in fields[label].items() if v.strip()}
            if per_book:
                sections.append({"label": label, "texts": per_book})
    extra = [{"label": k, "texts": {b: v.strip() for b, v in v.items() if v.strip()}}
             for k, v in fields.items()
             if k not in SECTION_ORDER and k != "_head" and any(x.strip() for x in v.values())]
    sections += extra
    # 题注 (head lines: English/Japanese names, collection notes)
    head = {b: v.strip() for b, v in fields.get("_head", {}).items() if v.strip()}
    if head:
        sections.insert(0, {"label": "题注", "texts": head})

    hid = "h" + re.sub(r"[^\w一-鿿]", "", name)
    herbs_out.append({
        "id": hid,
        "name": name,
        "aliases": sorted(set(a.strip("。.;；,，") for a in h.get("aliases", []) if a.strip() and a.strip("。.;；,，") != name)),
        "latin": h.get("latin", ""),
        "family": h.get("family", ""),
        "category": h.get("category", ""),
        "images": images,
        "sections": sections,
        "books": sorted(set(h.get("sources", []))),
    })

# dedupe by name (stubs normalized to same name, or cross-book name dups)
deduped = {}
order = []
for h in herbs_out:
    if h["name"] in deduped:
        t = deduped[h["name"]]
        t["aliases"] = sorted(set(t["aliases"]) | set(h["aliases"]))
        t["images"] = (t["images"] + [i for i in h["images"] if i not in t["images"]])
        t["books"] = sorted(set(t["books"]) | set(h["books"]))
        seen_labels = {s["label"] for s in t["sections"]}
        for s in h["sections"]:
            if s["label"] in seen_labels:
                tgt = next(x for x in t["sections"] if x["label"] == s["label"])
                tgt["texts"].update(s["texts"])
            else:
                t["sections"].append(s); seen_labels.add(s["label"])
        if not t["latin"] and h["latin"]: t["latin"] = h["latin"]
        if not t["family"] and h["family"]: t["family"] = h["family"]
        if not t["category"] and h["category"]: t["category"] = h["category"]
    else:
        deduped[h["name"]] = h
        order.append(h["name"])
herbs_out = [deduped[n] for n in order]

# apply stub merges -> alias into canonical herb
name2herb = {h["name"]: h for h in herbs_out}
for stub, tgt in merge_to.items():
    t = name2herb.get(tgt)
    if t and stub not in t["aliases"]:
        t["aliases"].append(stub)

# ---------- pinyin & english ----------
import unicodedata
from pypinyin import pinyin as _py, Style

zh_en_path = ROOT / "data" / "zh_en_map.json"
zh_en = json.loads(zh_en_path.read_text()) if zh_en_path.exists() else {}


def _toneless(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c)).replace("ü", "v").lower()


def _pick_reading(name, ref):
    """Per-char tone syllables whose plain forms concatenate to ref (fixes heteronyms)."""
    cand = _py(name, style=Style.NORMAL, heteronym=True)
    tones = _py(name, style=Style.TONE, heteronym=True)
    seq = []

    def dfs(i, acc):
        if i == len(cand):
            return acc == ref
        for alt in cand[i]:
            a = alt.lower().replace("u:", "v").replace("ü", "v")
            if ref.startswith(acc + a):
                tv = next((t for t in tones[i] if _toneless(t) == a), alt)
                seq.append(tv)
                if dfs(i + 1, acc + a):
                    return True
                seq.pop()
        return False

    return seq if dfs(0, "") else None


def pinyin_of(name):
    rec = zh_en.get(name)
    ref = re.sub(r"[^a-zvü:]", "", (rec or {}).get("py", "").lower().replace("u:", "v"))
    if ref:
        seq = _pick_reading(name, ref)
        if seq:
            return " ".join(seq).capitalize()
    return " ".join(s[0] for s in _py(name, style=Style.TONE)).capitalize()


def pinyin_plain(name):
    return "".join(s[0] for s in _py(name, style=Style.NORMAL)).lower()


def english_of(h):
    for key in [h["name"], *h["aliases"]]:
        rec = zh_en.get(key)
        if rec and rec.get("en"):
            return rec["en"]
    return ""


en_hits = 0
for h in herbs_out:
    h["pinyin"] = pinyin_of(h["name"])
    h["py"] = pinyin_plain(h["name"])
    h["en"] = english_of(h)
    en_hits += bool(h["en"])

hid_of = {}   # normalized name -> herb id
for h in herbs_out:
    hid_of[norm(h["name"])] = h["id"]
    for a in h["aliases"]:
        hid_of.setdefault(norm(a), h["id"])

# slugs first so formulas can carry herb_slug
used = set()
def slugify(name, prefix):
    s = re.sub(r"[\\/\\?%*:|\"<>#&=+．。()（）\[\]【】,，、;；:：\s]+", "-", name).strip("-")
    if not s:
        s = prefix
    base, i = s, 2
    while s in used:
        s = f"{base}-{i}"; i += 1
    used.add(s)
    return s

for h in herbs_out:
    h["slug"] = slugify(h["name"], h["id"])
hslug_of = {h["id"]: h["slug"] for h in herbs_out}

# ---------- diseases ----------
# 兽医分类下零方剂条目 = 书末《形态术语》表被误收；除害灭虫个别 OCR 残名
VET_CAT = "兽医中草药处方选"
AGRI_FIX = {"马尾松灭": "马尾松"}
AGRI_DROP = {"助灭"}

diseases_out = []
for d in kb["diseases"]:
    name = AGRI_FIX.get(d["name"].strip(), d["name"].strip())
    cat = d.get("category", "") or "其他"
    if name in JUNK_NAMES or name in AGRI_DROP:
        continue
    if cat == VET_CAT and not d.get("formulas"):
        continue  # 形态术语表混入
    did = "d" + re.sub(r"[^\w一-鿿]", "", name)
    diseases_out.append({
        "id": did, "name": name,
        "category": cat,
        "formulas": d.get("formulas", []),
        "books": sorted(set(d.get("sources", []))),
        "desc": d.get("descs", []),
        "trailing": d.get("trailing", ""),
    })
did_of = {d["name"]: d["id"] for d in diseases_out}
# 除害灭虫条目归并同名（如马尾松灭→马尾松）后可能重名，去重
_dedup = {}
for d in diseases_out:
    if d["name"] in _dedup:
        _dedup[d["name"]]["formulas"] += d["formulas"]
        _dedup[d["name"]]["books"] = sorted(set(_dedup[d["name"]]["books"]) | set(d["books"]))
        for x in d.get("desc", []):
            if x not in _dedup[d["name"]]["desc"]:
                _dedup[d["name"]]["desc"].append(x)
        _dedup[d["name"]]["trailing"] = (_dedup[d["name"]]["trailing"] + " " + d.get("trailing", "")).strip()
    else:
        _dedup[d["name"]] = d
diseases_out = list(_dedup.values())
did_of = {d["name"]: d["id"] for d in diseases_out}

# ---------- formulas ----------
formulas_out = []
for i, f in enumerate(kb["formulas"]):
    comp = []
    for c in f.get("composition", []):
        hn = norm(c.get("herb_norm") or c.get("herb") or "")
        hid = hid_of.get(hn)
        comp.append({
            "raw": c.get("raw", ""),
            "herb": c.get("herb", ""),
            "dose": c.get("dose", ""),
            "herb_id": hid,
            "slug": hslug_of.get(hid),
            "known": bool(c.get("known")),
        })
    fl = f.get("fields", {})
    formulas_out.append({
        "id": f["id"],
        "disease": f.get("disease", ""),
        "disease_id": did_of.get(f.get("disease", "")),
        "book": f.get("book", ""),
        "prescription": fl.get("处方", ""),
        "preparation": fl.get("制法", ""),
        "usage": fl.get("用法", ""),
        "efficacy": fl.get("疗效", ""),
        "source": fl.get("来源", ""),
        "note": fl.get("备注", "") or fl.get("附注", ""),
        "pnum": f.get("pnum"),
        "composition": comp,
        "index": i,
    })

# reverse indexes
herb_formulas = defaultdict(list)   # herb_id -> formula ids
herb_diseases = defaultdict(set)    # herb_id -> disease names (via formulas)
for fo in formulas_out:
    for c in fo["composition"]:
        if c["herb_id"]:
            herb_formulas[c["herb_id"]].append(fo["id"])
            if fo["disease"]:
                herb_diseases[c["herb_id"]].add(fo["disease"])

# herb -> disease via 主治 text matching (disease name appears in herb's indication text)
herb_indic = defaultdict(set)
herb_indic_text = {}
dname_by_len = sorted((d["name"] for d in diseases_out if len(d["name"]) >= 2), key=len, reverse=True)
for h in herbs_out:
    txt = " ".join(t for s in h["sections"] if s["label"] in ("功用", "功能主治", "性味功能", "应用", "主治") for t in s["texts"].values())
    if not txt:
        continue
    herb_indic_text[h["id"]] = txt
    for dn in dname_by_len:
        if dn in txt:
            herb_indic[h["id"]].add(dn)

for h in herbs_out:
    h["formulas"] = herb_formulas.get(h["id"], [])
    h["diseases"] = sorted(herb_indic.get(h["id"], set()) | herb_diseases.get(h["id"], set()))

# ---------- herb pairs (co-occurrence in formulas) & similar herbs ----------
pair_cnt = defaultdict(Counter)
for fo in formulas_out:
    hids = sorted({c["herb_id"] for c in fo["composition"] if c["herb_id"]})
    for i in range(len(hids)):
        for j in range(i + 1, len(hids)):
            pair_cnt[hids[i]][hids[j]] += 1
            pair_cnt[hids[j]][hids[i]] += 1

name_of = {h["id"]: h["name"] for h in herbs_out}
dset_of = {h["id"]: set(h["diseases"]) for h in herbs_out}
for h in herbs_out:
    top = pair_cnt.get(h["id"], Counter()).most_common(8)
    h["pairs"] = [{"n": name_of[pid], "s": hslug_of[pid], "c": cnt}
                  for pid, cnt in top if pid in name_of and cnt >= 2]
    s = dset_of[h["id"]]
    scored = []
    if len(s) >= 2:
        for g in herbs_out:
            if g["id"] == h["id"]:
                continue
            t = dset_of[g["id"]]
            inter = len(s & t)
            if inter >= 2:
                scored.append((inter / len(s | t), inter, g))
        scored.sort(key=lambda x: (-x[0], -x[1]))
    h["similar"] = [{"n": g["name"], "s": g["slug"], "c": inter} for _, inter, g in scored[:6]]

# ---------- 性味 (四气/五味/毒) ----------
QI_ORDER = ["大寒", "大热", "微寒", "微温", "寒", "热", "温", "凉", "平"]
QI_BUCKET = {"大寒": "寒", "寒": "寒", "微寒": "寒", "凉": "凉", "平": "平",
             "微温": "温", "温": "温", "热": "热", "大热": "热"}
WEI_ORDER = ["辛", "甘", "酸", "苦", "咸", "淡", "涩"]
for h in herbs_out:
    # only the flavor clause (before the first 。); 性味功能 continues with 功效 text
    # where words like 肺热/退热 would falsely match 四气
    xw_txt = " ".join((t.split("。")[0] or t) for s in h["sections"]
                      if s["label"] in ("性味", "性味功能") for t in s["texts"].values())
    qi, rest = [], xw_txt
    for q in QI_ORDER:
        if q in rest:
            b = QI_BUCKET[q]
            if b not in qi:
                qi.append(b)
            rest = rest.replace(q, "")
    h["xw"] = {"qi": qi, "wei": [w for w in WEI_ORDER if w in xw_txt],
               "du": ("有毒" in xw_txt or "大毒" in xw_txt or "小毒" in xw_txt)}

# ---------- supplementary materia medica annotations ----------
supp_path = ROOT / "supp_data" / "json" / "中药注释.json"
supp_hits = 0
if supp_path.exists():
    supp = {norm(r["zheng"]): r for r in json.loads(supp_path.read_text())}
    for h in herbs_out:
        rec = next((supp[norm(k)] for k in [h["name"], *h["aliases"]] if norm(k) in supp), None)
        if rec:
            h["zhushi"] = {"class": rec.get("class", ""), "desc": rec.get("desc", "")}
            supp_hits += 1

# reverse: disease -> herbs claiming to treat it in their 功用/主治 text.
# herbs already present in the disease's formulas are excluded so the page can
# show "验方用药" and "载述主治" as two distinct groups.
disease_indic_herbs = defaultdict(set)
for hid, dnames in herb_indic.items():
    for dn in dnames:
        disease_indic_herbs[dn].add(hid)

_fx_herbs = defaultdict(set)
for fo in formulas_out:
    if fo.get("disease_id"):
        for c in fo["composition"]:
            if c.get("herb_id"):
                _fx_herbs[fo["disease_id"]].add(c["herb_id"])

for d in diseases_out:
    extra = sorted(disease_indic_herbs.get(d["name"], set()) - _fx_herbs.get(d["id"], set()))
    d["indic_herbs"] = [hslug_of[hid] for hid in extra if hslug_of.get(hid)]

used_d = set()
for d in diseases_out:
    s = re.sub(r"[\\/\\?%*:|\"<>#&=+．。()（）\[\]【】,，、;；:：\s]+", "-", d["name"]).strip("-") or d["id"]
    base_s, i = s, 2
    while s in used_d:
        s = f"{base_s}-{i}"; i += 1
    used_d.add(s)
    d["slug"] = s

# ---------- supplementary: 证候 (patterns) & 症状词典 ----------
dname_list = [d["name"] for d in diseases_out]
zheng_out, glossary_out = [], []
_zp = ROOT / "supp_data" / "json" / "疾病注释.json"
_rp = ROOT / "supp_data" / "json" / "辨证入门症状.json"
_gp = ROOT / "supp_data" / "json" / "症状注释.json"
if _zp.exists():
    _ru = {r["zheng"]: r for r in json.loads(_rp.read_text())} if _rp.exists() else {}
    JINGFANG = re.compile(r"(汤|丸|散|膏|饮|丹|方)（?.*）?$")
    LIUJING = ("太阳", "阳明", "少阳", "太阴", "少阴", "厥阴")
    seen_z = set()
    for r in json.loads(_zp.read_text()):
        z = r["zheng"].strip()
        if z in seen_z:
            continue
        seen_z.add(z)
        if z.startswith("辨证"):
            group, name = "辨证纲领", z[2:]
        elif z.startswith("内科"):
            group, name = "内科证候", z[2:]
        elif z[:2] in LIUJING or JINGFANG.search(z):
            group, name = "伤寒六经", z
        else:
            group, name = "专科杂证", z
        rur = _ru.get(z, {})
        syms = [s for s in re.split(r"[-*]", r.get("symptom") or rur.get("symptom") or "") if s]
        text = name + (r.get("desc") or "") + (r.get("process") or "") + (rur.get("linchuang") or "")
        zheng_out.append({
            "name": name, "full": z, "group": group,
            "desc": r.get("desc", ""), "process": r.get("process", ""),
            "linchuang": rur.get("linchuang", ""),
            "symptoms": syms,
            "rel_diseases": sorted(dn for dn in dname_list if dn in text),
        })
    used_z = set()
    for z in zheng_out:
        s = re.sub(r"[\\/\\?%*:|\"<>#&=+．。()（）\[\]【】,，、;；:：\s]+", "-", z["name"]).strip("-") or "z"
        base_s, i = s, 2
        while s in used_z:
            s = f"{base_s}-{i}"; i += 1
        used_z.add(s)
        z["slug"] = s
    # reverse: disease -> related zheng slugs
    for d in diseases_out:
        d["zheng"] = [z["slug"] for z in zheng_out if d["name"] in z["rel_diseases"]][:12]

if _gp.exists():
    for r in json.loads(_gp.read_text()):
        glossary_out.append({
            "name": r["zheng"].strip(), "desc": r.get("desc", ""),
            "dialogue": r.get("dialogue", ""), "category": r.get("category", ""),
            "division": r.get("division", ""),
        })

# ---------- supplementary: 中成药 ----------
patent_out = []
_mp = ROOT / "supp_data" / "json" / "中成药药品.json"
_mz = ROOT / "supp_data" / "json" / "中成药症状.json"
if _mp.exists() or _mz.exists():
    meds = {}

    def mrec(n):
        return meds.setdefault(n, {"name": n, "team": [], "func": "", "effect": "",
                                   "zheng": set(), "desc": set(), "jian": set()})

    if _mp.exists():
        for r in json.loads(_mp.read_text()):
            z = re.sub(r"\d+$", "", r["zheng"]).strip()
            for m in r.get("medicine", "").split("-"):
                m = m.strip()
                if not m:
                    continue
                rec = mrec(m)
                rec["zheng"].add(z)
                if r.get("desc"):
                    rec["desc"].add(r["desc"])
    if _mz.exists():
        for r in json.loads(_mz.read_text()):
            z = re.sub(r"\d+$", "", r["zheng"]).strip()
            for m in re.split(r"[-、]", r.get("jiaJian", "")):
                m = m.strip()
                if not m:
                    continue
                rec = mrec(m)
                rec["zheng"].add(z)
                if r.get("medicine") and not rec["func"]:
                    rec["func"] = r["medicine"]
                if r.get("effect") and not rec["effect"]:
                    rec["effect"] = r["effect"]
                if r.get("jian"):
                    rec["jian"].add(r["jian"])
                for tok in re.split(r"[-*]", r.get("team", "")):
                    tok = re.sub(r"^[A-Z]\d+", "", tok).strip()
                    if tok and tok not in rec["team"]:
                        rec["team"].append(tok)

    # composition token -> herb link (with part-name aliases)
    PATENT_ALIAS = {
        "荆芥穗": "荆芥", "苦杏仁": "杏仁", "紫苏叶": "紫苏", "紫苏梗": "紫苏",
        "金银花": "忍冬", "生姜皮": "生姜", "干地黄": "地黄", "熟地黄": "地黄",
        "生地黄": "地黄", "川牛膝": "牛膝", "怀牛膝": "牛膝", "浙贝母": "贝母",
        "川贝母": "贝母", "广藿香": "藿香", "云苓": "茯苓", "炒白术": "白术",
        "炙甘草": "甘草", "蜜麻黄": "麻黄", "煅牡蛎": "牡蛎", "生石膏": "石膏",
        "干姜": "生姜", "山萸肉": "山茱萸", "酒大黄": "大黄", "焦山楂": "山楂",
    }
    zname2slug = {z["name"]: z["slug"] for z in zheng_out}
    used_m = set()
    unmatched_tok = Counter()
    for n, rec in meds.items():
        herbs_l = []
        for tok in rec["team"]:
            tgt = PATENT_ALIAS.get(tok, tok)
            hid = hid_of.get(norm(tgt))
            herbs_l.append({"n": tok, "s": hslug_of.get(hid)})
            if not hid:
                unmatched_tok[tok] += 1
        s = re.sub(r"[\\/\\?%*:|\"<>#&=+．。()（）\[\]【】,，、;；:：\s]+", "-", n).strip("-") or "m"
        base_s, i = s, 2
        while s in used_m:
            s = f"{base_s}-{i}"; i += 1
        used_m.add(s)
        patent_out.append({
            "name": n, "slug": s,
            "team": herbs_l, "func": rec["func"],
            "effect": [x for x in re.split(r"[-–—]", rec["effect"]) if x.strip()],
            "zheng": [{"n": z, "s": zname2slug.get(z)} for z in sorted(rec["zheng"])],
            "desc": sorted(rec["desc"]), "jian": sorted(rec["jian"]),
        })
    patent_out.sort(key=lambda x: x["name"])
    # reverse: herb -> patents
    slug2herb = {h["slug"]: h for h in herbs_out}
    for p in patent_out:
        for c in p["team"]:
            hh = slug2herb.get(c["s"]) if c["s"] else None
            if hh is not None:
                hh.setdefault("patents", []).append({"n": p["name"], "s": p["slug"]})
    print("unmatched patent tokens:", unmatched_tok.most_common(15))

# ---------- graph ----------
# per-disease top herbs (for tooltip) — count occurrences across its formulas
disease_herb_freq = defaultdict(Counter)
for fo in formulas_out:
    if not fo["disease_id"]:
        continue
    for c in fo["composition"]:
        if c["herb_id"]:
            disease_herb_freq[fo["disease_id"]][c["herb"]] += 1

def _xw_excerpt(h):
    for s in h["sections"]:
        if s["label"] in ("性味", "性味功能"):
            return next(iter(s["texts"].values()))[:60]
    return ""

def _fn_excerpt(h):
    for s in h["sections"]:
        if s["label"] in ("功能主治", "功用", "主治", "应用"):
            return next(iter(s["texts"].values()))[:90]
    return ""

nodes, links = [], []
h_by_id = {h["id"]: h for h in herbs_out}
for h in herbs_out:
    nodes.append({"id": h["id"], "name": h["name"], "type": "herb",
                  "slug": h["slug"], "cat": h["category"].split("·")[0] if h["category"] else "",
                  "img": h["images"][0]["file"] if h.get("images") else "",
                  "xw": _xw_excerpt(h), "fn": _fn_excerpt(h)})
for d in diseases_out:
    top = disease_herb_freq.get(d["id"], Counter()).most_common(6)
    nodes.append({"id": d["id"], "name": d["name"], "type": "disease",
                  "slug": d["slug"], "cat": d["category"],
                  "fc": len(d["formulas"]),
                  "top": [t[0] for t in top]})
seen_edge = set()
adj = defaultdict(set)
for fo in formulas_out:
    for c in fo["composition"]:
        if c["herb_id"] and fo["disease_id"]:
            k = (c["herb_id"], fo["disease_id"])
            if k not in seen_edge:
                seen_edge.add(k)
                links.append({"source": c["herb_id"], "target": fo["disease_id"], "rel": "组方治疗"})
                adj[c["herb_id"]].add(fo["disease_id"])
                adj[fo["disease_id"]].add(c["herb_id"])
for hid, dnames in herb_indic.items():
    for dn in dnames:
        did = did_of.get(dn)
        if did and (hid, did) not in seen_edge:
            seen_edge.add((hid, did))
            links.append({"source": hid, "target": did, "rel": "主治"})
            adj[hid].add(did)
            adj[did].add(hid)

for n in nodes:
    n["deg"] = len(adj.get(n["id"], ()))

# ---------- precomputed layouts (no client-side simulation) ----------
import math
try:
    import networkx as nx
except ImportError:
    nx = None

herb_ids = [n["id"] for n in nodes if n["type"] == "herb"]
dis_ids = [n["id"] for n in nodes if n["type"] == "disease"]

def norm_scale(pos, w=1000):
    xs = [p[0] for p in pos.values()]; ys = [p[1] for p in pos.values()]
    x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys)
    xr = (x1 - x0) or 1; yr = (y1 - y0) or 1
    s = w / max(xr, yr)
    return {k: ((v[0] - (x0 + x1) / 2) * s, (v[1] - (y0 + y1) / 2) * s) for k, v in pos.items()}

pos_spring = {}
pos_bi = {}
if nx is not None:
    G = nx.Graph()
    G.add_nodes_from(n["id"] for n in nodes)
    G.add_edges_from((l["source"], l["target"]) for l in links)
    # only layout the connected part; isolates go on a ring
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    main = comps[0] if comps else set()
    try:
        pos_spring = norm_scale(nx.kamada_kawai_layout(G.subgraph(main)), 2400)
    except Exception:
        pos_spring = norm_scale(nx.spring_layout(G.subgraph(main), seed=42, k=0.8, iterations=150), 2400)
    # ring for isolated nodes
    iso = [n["id"] for n in nodes if n["id"] not in main]
    for i, nid in enumerate(iso):
        a = 2 * math.pi * i / max(1, len(iso))
        pos_spring[nid] = (1350 * math.cos(a), 1350 * math.sin(a))
else:
    # fallback: concentric by degree
    hh = sorted(herb_ids, key=lambda x: -len(adj[x]))
    dd = sorted(dis_ids, key=lambda x: -len(adj[x]))
    for i, nid in enumerate(dd):
        a = 2 * math.pi * i / len(dd)
        pos_spring[nid] = (300 * math.cos(a), 300 * math.sin(a))
    for i, nid in enumerate(hh):
        a = 2 * math.pi * i / len(hh)
        r = 500 + 60 * (i // 40)
        pos_spring[nid] = (r * math.cos(a), r * math.sin(a))

# bipartite: two horizontal rows, barycenter ordering to reduce crossings
def barycentric(rows_a, rows_b):
    pa = {x: i for i, x in enumerate(rows_a)}
    pb = {x: i for i, x in enumerate(rows_b)}
    inf = float("inf")
    for _ in range(6):
        rows_b = sorted(rows_b, key=lambda d: (sum(pa[h] for h in adj[d] if h in pa) / max(1, len([h for h in adj[d] if h in pa])) if any(h in pa for h in adj[d]) else inf))
        pb = {x: i for i, x in enumerate(rows_b)}
        rows_a = sorted(rows_a, key=lambda h: (sum(pb[d] for d in adj[h] if d in pb) / max(1, len([d for d in adj[h] if d in pb])) if any(d in pb for d in adj[h]) else inf))
        pa = {x: i for i, x in enumerate(rows_a)}
    return pa, pb

ha = [h for h in sorted(herb_ids, key=lambda x: -len(adj[x]))]
db = [d for d in sorted(dis_ids, key=lambda x: -len(adj[x]))]
pa, pb = barycentric(ha, db)
W = max(len(ha), len(db)) * 9.5   # ~9.5px per node so rows stay readable
for h, i in pa.items():
    pos_bi[h] = ((i - len(pa) / 2) * (W / len(pa)), -320.0)
for d, i in pb.items():
    pos_bi[d] = ((i - len(pb) / 2) * (W / len(pb)), 320.0)

for n in nodes:
    x, y = pos_spring.get(n["id"], (0, 0))
    n["x"], n["y"] = round(x, 1), round(y, 1)
    x2, y2 = pos_bi.get(n["id"], (0, 0))
    n["bx"], n["by"] = round(x2, 1), round(y2, 1)

graph = {"nodes": nodes, "links": links}

# ---------- search ----------
search = []
for h in herbs_out:
    kw = " ".join(h["aliases"] + [h["latin"], h["family"], h["category"],
                                h.get("py", ""), h.get("pinyin", ""), h.get("en", ""),
                                herb_indic_text.get(h["id"], "")[:800]])
    search.append({"t": "h", "n": h["name"], "s": h["slug"], "k": kw})
for d in diseases_out:
    dpy = pinyin_plain(d["name"])
    fx_names = " ".join(name_of[x] for x in _fx_herbs.get(d["id"], set()) if x in name_of)
    ddesc = " ".join(d.get("desc", []))[:400]
    search.append({"t": "d", "n": d["name"], "s": d["slug"],
                   "k": " ".join([d["category"], dpy, fx_names, ddesc])})
for z in zheng_out:
    search.append({"t": "z", "n": z["name"], "s": z["slug"],
                   "k": " ".join([z["group"], z.get("desc", "")[:300]])})
for g in glossary_out:
    search.append({"t": "g", "n": g["name"], "s": g["name"],
                   "k": " ".join([g.get("category", ""), g.get("desc", "")[:200]])})
for p in patent_out:
    search.append({"t": "c", "n": p["name"], "s": p["slug"],
                   "k": " ".join([z["n"] for z in p["zheng"]] + [p.get("func", "")[:200]])})

meta = {
    "title": "闽本草",
    "herbs": len(herbs_out), "diseases": len(diseases_out),
    "formulas": len(formulas_out), "edges": len(links),
    "images": sum(len(h["images"]) for h in herbs_out),
    "english": en_hits, "zhushi": supp_hits,
    "zheng": len(zheng_out), "glossary": len(glossary_out),
    "patents": len(patent_out),
    "skipped_junk": skipped,
}

(SD / "herbs.json").write_text(json.dumps(herbs_out, ensure_ascii=False))
(SD / "diseases.json").write_text(json.dumps(diseases_out, ensure_ascii=False))
(SD / "formulas.json").write_text(json.dumps(formulas_out, ensure_ascii=False))
(SD / "zhengxing.json").write_text(json.dumps(zheng_out, ensure_ascii=False))
(SD / "glossary.json").write_text(json.dumps(glossary_out, ensure_ascii=False))
(SD / "patent.json").write_text(json.dumps(patent_out, ensure_ascii=False))
(SD / "graph.json").write_text(json.dumps(graph, ensure_ascii=False))
(SD / "search.json").write_text(json.dumps(search, ensure_ascii=False))
(SD / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in meta.items() if k != "skipped_junk"}, ensure_ascii=False))
print("skipped:", skipped[:30])
