#!/usr/bin/env python3
"""Merge parsed entries into a knowledge base: entities + relations.

Output: kb.json {herbs, diseases, formulas}
herb:   {id, name, aliases[], latin, family, category, sources[], fields{label:text per book}}
disease:{id, name, category, sources[]}
formula:{id, book, disease, desc, text, composition[{herb,dose}], usage, efficacy, source_org}
edges stored inline: herb.treats[], disease.formulas[]
"""
import json, pathlib, re, sys
from collections import defaultdict, Counter

ROOT = pathlib.Path.home() / "fujian-tcm"
OCR = ROOT / "ocr"

from opencc import OpenCC
_CC = OpenCC("t2s")
EXTRA = str.maketrans({"痺": "痹", "瘧": "疟", "蟯": "蛲", "棟": "楝", "朁": "骨",
                       "蕁": "荨", "蔴": "麻", "癩": "癞", "卲": "芶", "斉": "荠",
                       "麴": "曲", "蘢": "茏", "兎": "兔", "卽": "即"})
CN = r"一-鿿"

def norm(s):
    return _CC.convert(s or "").translate(EXTRA)


def norm_name(s):
    s = norm(s)
    return re.sub(r"[^" + CN + r"]", "", s)


DOSE_TAIL = re.compile(r"(?:各)?[0-9０-９]+(?:[~-][0-9０-９]+)?\s*(?:克|錢|钱|两|兩|分|片|枚|粒|毫升|ml|斤|升|匙|杯|把|撮|尺|寸|厘米|公分|g|个|只|朵|节|段|條|条|支|块|塊|顆|颗|滴|碗|盅|汤匙|调羹)")
PAREN = re.compile(r"[（(][^（）()]*[)）]")


NON_HERB = re.compile(r"^(日|每日|每次|每|隔日|连服|服用|水炖服|水煎服|水煎|煎服|煎汤|炖服|冲服|冲开水服|开水送服|开水泡服|泡茶|代茶|代茶饮|温服|热服|冷服|空腹|饭前|饭后|睡前|顿服|分服|外敷|敷患处|敷|外擦|外洗|外涂|涂患处|熏洗|薰洗|点眼|滴耳|坐浴|捣烂|捣烂绞汁|绞汁|共研细末|共研末|研末|研细|为末|为散|研粉|调服|調服|调匀|调蜜|调糖|調|浸酒|泡酒|酒炒|盐炒|醋炒|蜜炙|食盐|红糖|白糖|冰糖|蜂蜜|蜜糖|米醋|醋|米汤|米泔水|饭|面粉|酒|黄酒|白酒|高粱酒|水|开水|沸水|茶|油|麻油|花生油|菜油|猪胆|猪瘦肉|猪肠|猪肝|猪肚|猪骨|鸡肉|鸡蛋|鸭蛋|鲫鱼|鲤鱼|泥鳅|黄鳝|虾|蟹|糯米|粳米|大米|小麦|绿豆|赤小豆|黑豆|黄豆|豆腐|豆鼓|生姜汁|姜汁|藕|甘蔗|荸荠|胡萝卜|白萝卜|白菜|芥菜|韭菜|龙眼肉|荔枝|香蕉|苹果|梨|桃|杏|食盐少许|各适量|适量|少许|不拘时|任意|口服|内服|灌服|喂服|餵服|吞服|含服|噙化|口含|送服|送下|药引|引|配伍|配方|备用|待用|另炖|另煎|先煎|后下|包煎|烊化|冲入|兑服|兑|呷|啜|食|吃|服完|见效|痊愈|巩固|加减|酌加|酌减|或加|或配|选配|配合|并用|同用|共用|如|若|症见|适用于|主治|治|疗|治宜|宜|忌|禁|禁忌|注意|孕妇忌服|孕妇慎用).*$")


def split_composition(text):
    """'苦棟皮30克，槟榔、金铃子各15克' -> [(name, dose_str)]"""
    text = norm(text)
    text = re.sub(r"[。；;]", "，", text)
    parts = re.split(r"[、，]", text)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        p = PAREN.sub("", p).strip()
        if not p:
            continue
        if NON_HERB.match(p):
            continue
        if re.match(r"^(水煎|煎服|外用|每日|分|连服|用|随|或|加|另|同|和|与)", p):
            if not DOSE_TAIL.search(p):
                continue
        doses = DOSE_TAIL.findall(p)
        name = DOSE_TAIL.sub("", p)
        name = re.sub(r"^(各|用|加|另|或|和|与|同)+", "", name)
        name = re.sub(r"[^" + CN + r"].*$", "", name)
        name = name.strip("、，。；：:（）() ")
        if len(name) < 1 or len(name) > 12:
            continue
        dose = doses[0] if doses else ""
        out.append({"raw": p, "herb": name, "dose": dose})
    return out


PART_SUFFIX = ["全草", "全株", "根皮", "根", "茎", "叶", "花", "果实", "果", "种子", "子",
               "皮", "藤", "枝", "苗", "仁", "实", "壳", "心", "核", "头", "尾", "身", "段", "块"]
PRE_STRIP = ["鲜", "干", "生", "熟", "炙", "煅", "炒", "炭", "制", "净", "选", "去", "陈", "嫩", "老"]


def fold_herb_name(name):
    """candidates from most-specific to least-specific for lookup"""
    yield name
    for suf in PART_SUFFIX:
        if name.endswith(suf) and len(name) > len(suf) + 1:
            yield name[:-len(suf)]
            break
    n = name
    while n and n[0] in PRE_STRIP and len(n) > 2:
        n = n[1:]
        yield n
        for suf in PART_SUFFIX:
            if n.endswith(suf) and len(n) > len(suf) + 1:
                yield n[:-len(suf)]
                break


def extract_indications(ent):
    """indication strings from herb entry fields."""
    f = ent.get("fields", {})
    out = []
    # caise 功能主治 / suren 功用: functions.用于 ind1、ind2
    for k in ("功能主治", "功用", "主治"):
        t = norm(f.get(k, ""))
        m = re.search(r"用于(.+)", t)
        seg = m.group(1) if m else t
        # strip dosage tail like 5~10克
        seg = re.sub(r"[0-9０-９~～\-]+(克|钱|两|錢|分|g|毫升).*$", "", seg)
        for x in re.split(r"[、，,。；;：:]", seg):
            x = x.strip()
            if 2 <= len(x) <= 20:
                out.append(x)
    # fj1 应用: '病症：用法' pairs inside one text blob
    t = norm(f.get("应用", ""))
    for m in re.finditer(r"([" + CN + r"、]{2,20})[:：]", t):
        out.append(m.group(1))
    # suren 验方 ①适应症：方
    t = norm(f.get("验方", "") + " " + f.get("附方", ""))
    for m in re.finditer(r"[①②③④⑤⑥⑦⑧⑨⑩\d]*\s*([" + CN + r"、]{2,20})[:：]", t):
        out.append(m.group(1))
    return sorted(set(out))


def main():
    ents = [json.loads(l) for l in open(ROOT / "entries.jsonl")]

    herbs = {}
    diseases = {}
    formulas = []

    def get_herb(rawname):
        key = norm_name(rawname)
        if not key:
            return None
        if key not in herbs:
            herbs[key] = {"id": "h_" + key, "name": key, "aliases": [],
                          "latin": "", "family": "", "category": "",
                          "sources": [], "fields": {}, "treats": set()}
        return herbs[key]

    def get_disease(rawname, cat=None):
        key = norm_name(rawname)
        if not key:
            return None
        if key not in diseases:
            diseases[key] = {"id": "d_" + key, "name": key, "category": cat or "",
                             "formulas": [], "sources": set()}
        d = diseases[key]
        if cat and not d["category"]:
            d["category"] = cat
        return d

    # ---- herbs ----
    for e in ents:
        if e["entry_type"] != "herb":
            continue
        h = get_herb(e["name"])
        if h is None:
            continue
        h["sources"].append(e["book"])
        for k, v in e.get("fields", {}).items():
            if not v.strip():
                continue
            h["fields"].setdefault(k, {})
            h["fields"][k][e["book"]] = v.strip()
        if e.get("family"):
            h["family"] = e["family"]
        if e.get("latin") and not h["latin"]:
            h["latin"] = e["latin"]
        if e.get("category"):
            h["category"] = e["category"]
        # aliases
        al = norm(e["fields"].get("别名", "") if isinstance(e["fields"].get("别名"), str) else "")
        if not al:
            al = norm(e["fields"].get("別名", "") if isinstance(e["fields"].get("別名"), str) else "")
        for a in re.split(r"[、，,。；;]", al):
            a = re.sub(r"[^" + CN + r"]", "", a)
            if 1 < len(a) <= 12 and a != h["name"]:
                h["aliases"].append(a)
        for ind in extract_indications(e):
            h["treats"].add(norm_name(ind))

    # second pass: alias folding — if a canonical herb name equals another's alias, merge
    alias2canon = {}
    for key, h in herbs.items():
        for a in h["aliases"]:
            alias2canon.setdefault(a, key)
    for key in list(herbs.keys()):
        if key in alias2canon and alias2canon[key] != key and alias2canon[key] in herbs:
            tgt = herbs[alias2canon[key]]
            src = herbs.pop(key)
            tgt["sources"] = sorted(set(tgt["sources"] + src["sources"]))
            for k, vb in src["fields"].items():
                tgt["fields"].setdefault(k, {}).update(vb)
            tgt["treats"] |= src["treats"]
            if not tgt["latin"] and src["latin"]:
                tgt["latin"] = src["latin"]
            if not tgt["family"] and src["family"]:
                tgt["family"] = src["family"]
            tgt["aliases"] = sorted(set(tgt["aliases"] + src["aliases"] + [src["name"]]))

    # ---- diseases & formulas ----
    for e in ents:
        if e["entry_type"] != "disease":
            continue
        d = get_disease(e["name"], e.get("category"))
        if d is None:
            continue
        d["sources"].add(e["book"])
        if "formulas" in e:        # fangxuan books
            for fm in e["formulas"]:
                fid = f'f_{len(formulas)}'
                comp_text = fm["fields"].get("处方", "") or fm["fields"].get("组成", "")
                comp = split_composition(comp_text)
                formulas.append({
                    "id": fid, "book": e["book"], "disease": d["name"],
                    "fields": fm["fields"], "composition": comp,
                    "page": fm.get("page")})
                d["formulas"].append(fid)
        for g in e.get("groups", []):   # chufang
            for it in g.get("items", []):
                fid = f'f_{len(formulas)}'
                comp = split_composition(it["text"])
                formulas.append({
                    "id": fid, "book": e["book"], "disease": d["name"],
                    "desc": g.get("desc", ""), "text": it["text"],
                    "composition": comp})
                d["formulas"].append(fid)
        for it in e.get("items", []):   # fj1 tail (vet/pesticide)
            fid = f'f_{len(formulas)}'
            formulas.append({"id": fid, "book": e["book"], "disease": d["name"],
                             "text": it.get("text", ""),
                             "composition": split_composition(it.get("text", ""))})
            d["formulas"].append(fid)

    # herb <- formula membership edges (disease<-herb implied via formula)
    herb_ref = set(herbs.keys()) | set(alias2canon.keys())
    comp_hit = 0
    for fm in formulas:
        for c in fm["composition"]:
            hit = None
            for cand in fold_herb_name(norm_name(c["herb"])):
                canon = alias2canon.get(cand, cand)
                if canon in herbs:
                    hit = canon
                    break
            c["herb_norm"] = hit or norm_name(c["herb"])
            c["known"] = hit is not None
            if hit:
                comp_hit += 1
                herbs[hit]["treats"].add(norm_name(fm["disease"]))

    # unmatched composition tokens -> stub herbs if frequent & clean
    NOISE_CHAR = re.compile(r"[捣烂喷洒煎服灭食调研浸泡洗敷擦涂炖煮蒸晒烧熏喂饲粪尿屎汁]")
    unk = Counter()
    for fm in formulas:
        for c in fm["composition"]:
            if not c.get("known") and 2 <= len(c["herb_norm"]) <= 10:
                unk[c["herb_norm"]] += 1
    stubbed = 0
    for tok, cnt in unk.items():
        if cnt >= 3 and not NOISE_CHAR.search(tok):
            h = {"id": "h_" + tok, "name": tok, "aliases": [], "latin": "",
                 "family": "", "category": "", "sources": [], "fields": {},
                 "treats": set(), "stub": True, "ref_count": cnt}
            herbs[tok] = h
            stubbed += 1
            # backfill edges: mark formulas' tokens known
            for fm in formulas:
                for c in fm["composition"]:
                    if c["herb_norm"] == tok and not c.get("known"):
                        c["known"] = True
                        comp_hit += 1
                        h["treats"].add(norm_name(fm["disease"]))

    for h in herbs.values():
        h["treats"] = sorted(h["treats"])
    for d in diseases.values():
        d["sources"] = sorted(d["sources"])

    kb = {"herbs": list(herbs.values()), "diseases": list(diseases.values()),
          "formulas": formulas,
          "stats": {"herbs": len(herbs), "diseases": len(diseases),
                    "formulas": len(formulas), "comp_herb_hits": comp_hit}}
    (ROOT / "kb.json").write_text(json.dumps(kb, ensure_ascii=False, indent=1))
    print(json.dumps(kb["stats"], ensure_ascii=False))
    unk = Counter()
    for fm in formulas:
        for c in fm["composition"]:
            if not c.get("known"):
                unk[c["herb_norm"]] += 1
    print("top unknown composition tokens:", unk.most_common(30))


if __name__ == "__main__":
    main()
