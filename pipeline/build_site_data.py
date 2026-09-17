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
    for book in dict.fromkeys(h.get("sources", [])):
        cand = entry_map.get((book, nname))
        if not cand:
            for e in by_book[book]:
                if e["entry_type"] != "herb":
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
    })
did_of = {d["name"]: d["id"] for d in diseases_out}
# 除害灭虫条目归并同名（如马尾松灭→马尾松）后可能重名，去重
_dedup = {}
for d in diseases_out:
    if d["name"] in _dedup:
        _dedup[d["name"]]["formulas"] += d["formulas"]
        _dedup[d["name"]]["books"] = sorted(set(_dedup[d["name"]]["books"]) | set(d["books"]))
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
dname_by_len = sorted((d["name"] for d in diseases_out if len(d["name"]) >= 2), key=len, reverse=True)
for h in herbs_out:
    txt = " ".join(t for s in h["sections"] if s["label"] in ("功用", "功能主治", "性味功能", "应用", "主治") for t in s["texts"].values())
    if not txt:
        continue
    for dn in dname_by_len:
        if dn in txt:
            herb_indic[h["id"]].add(dn)

for h in herbs_out:
    h["formulas"] = herb_formulas.get(h["id"], [])
    h["diseases"] = sorted(herb_indic.get(h["id"], set()) | herb_diseases.get(h["id"], set()))

used_d = set()
for d in diseases_out:
    s = re.sub(r"[\\/\\?%*:|\"<>#&=+．。()（）\[\]【】,，、;；:：\s]+", "-", d["name"]).strip("-") or d["id"]
    base_s, i = s, 2
    while s in used_d:
        s = f"{base_s}-{i}"; i += 1
    used_d.add(s)
    d["slug"] = s

# ---------- graph ----------
nodes, links = [], []
for h in herbs_out:
    nodes.append({"id": h["id"], "name": h["name"], "type": "herb",
                  "slug": h["slug"], "cat": h["category"].split("·")[0] if h["category"] else ""})
for d in diseases_out:
    nodes.append({"id": d["id"], "name": d["name"], "type": "disease",
                  "slug": d["slug"], "cat": d["category"]})
seen_edge = set()
for fo in formulas_out:
    for c in fo["composition"]:
        if c["herb_id"] and fo["disease_id"]:
            k = (c["herb_id"], fo["disease_id"])
            if k not in seen_edge:
                seen_edge.add(k)
                links.append({"source": c["herb_id"], "target": fo["disease_id"], "rel": "组方治疗"})
for hid, dnames in herb_indic.items():
    for dn in dnames:
        did = did_of.get(dn)
        if did and (hid, did) not in seen_edge:
            seen_edge.add((hid, did))
            links.append({"source": hid, "target": did, "rel": "主治"})

graph = {"nodes": nodes, "links": links}

# ---------- search ----------
search = []
for h in herbs_out:
    kw = " ".join(h["aliases"] + [h["latin"], h["family"], h["category"]])
    search.append({"t": "h", "n": h["name"], "s": h["slug"], "k": kw})
for d in diseases_out:
    search.append({"t": "d", "n": d["name"], "s": d["slug"], "k": d["category"]})

meta = {
    "title": "闽本草",
    "herbs": len(herbs_out), "diseases": len(diseases_out),
    "formulas": len(formulas_out), "edges": len(links),
    "images": sum(len(h["images"]) for h in herbs_out),
    "skipped_junk": skipped,
}

(SD / "herbs.json").write_text(json.dumps(herbs_out, ensure_ascii=False))
(SD / "diseases.json").write_text(json.dumps(diseases_out, ensure_ascii=False))
(SD / "formulas.json").write_text(json.dumps(formulas_out, ensure_ascii=False))
(SD / "graph.json").write_text(json.dumps(graph, ensure_ascii=False))
(SD / "search.json").write_text(json.dumps(search, ensure_ascii=False))
(SD / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in meta.items() if k != "skipped_junk"}, ensure_ascii=False))
print("skipped:", skipped[:30])
