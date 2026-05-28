"""
Build output/theme/reference.dotx — Theory Y institutional equity research template.

Palette
-------
  Navy      #0D1F3C  — headings, title, table header bg
  Gold      #B8922A  — H3, accent rule, quote border
  Ink       #1A1A1A  — body text
  Slate     #4A5568  — subtitle, metadata
  Silver    #F4F6F9  — table alternate row, code bg
  White     #FFFFFF  — base page
  Rule      #CBD5E0  — thin separator lines

Typography
----------
  Display / Headings : Garamond (Word built-in serif, authoritative)
  Body               : Calibri 10.5 pt  (clean, readable at dense info density)
  Monospace          : Courier New 9 pt
"""

import shutil, zipfile, os
from lxml import etree

SRC  = "output/theme/reference.dotx"
DEST = "output/theme/reference.dotx"
TMP  = "/tmp/theory_y_dotx"

# ── palette ────────────────────────────────────────────────────────────────
NAVY   = "0D1F3C"
GOLD   = "B8922A"
INK    = "1A1A1A"
SLATE  = "4A5568"
SILVER = "F4F6F9"
WHITE  = "FFFFFF"
RULE   = "CBD5E0"
NAVY_LIGHT = "1E3A5F"

# ── XML namespaces ──────────────────────────────────────────────────────────
W  = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
R  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

def w(tag):   return f"{{{W}}}{tag}"
def el(tag, **attrs):
    e = etree.Element(w(tag))
    for k, v in attrs.items():
        e.set(w(k.replace("_", "")), v)
    return e

def wval(tag, val):
    e = etree.Element(w(tag))
    e.set(w("val"), val)
    return e

def color_el(hex_val):
    e = etree.Element(w("color"))
    e.set(w("val"), hex_val)
    return e

def sz_el(pts_x2):
    """Font size: Word uses half-points."""
    e = etree.Element(w("sz"))
    e.set(w("val"), str(pts_x2))
    cs = etree.Element(w("szCs"))
    cs.set(w("val"), str(pts_x2))
    return e, cs

def shd_el(fill, color="auto", val="clear"):
    e = etree.Element(w("shd"))
    e.set(w("val"), val)
    e.set(w("color"), color)
    e.set(w("fill"), fill)
    return e

def border_el(side, sz="4", val="single", color=RULE, space="0"):
    e = etree.Element(w(side))
    e.set(w("val"), val)
    e.set(w("sz"), sz)
    e.set(w("space"), space)
    e.set(w("color"), color)
    return e

def spacing_el(before=None, after=None, line=None, lineRule=None):
    e = etree.Element(w("spacing"))
    if before    is not None: e.set(w("before"),    str(before))
    if after     is not None: e.set(w("after"),     str(after))
    if line      is not None: e.set(w("line"),      str(line))
    if lineRule  is not None: e.set(w("lineRule"),  lineRule)
    return e

def ind_el(left=None, right=None, firstLine=None, hanging=None):
    e = etree.Element(w("ind"))
    if left      is not None: e.set(w("left"),      str(left))
    if right     is not None: e.set(w("right"),     str(right))
    if firstLine is not None: e.set(w("firstLine"), str(firstLine))
    if hanging   is not None: e.set(w("hanging"),   str(hanging))
    return e

# ── unpack ──────────────────────────────────────────────────────────────────
if os.path.exists(TMP):
    shutil.rmtree(TMP)
os.makedirs(TMP)
shutil.copy(SRC, "/tmp/ref_backup.dotx")      # safety backup

with zipfile.ZipFile(SRC, "r") as z:
    z.extractall(TMP)

# ── parse styles.xml ────────────────────────────────────────────────────────
styles_path = os.path.join(TMP, "word", "styles.xml")
tree = etree.parse(styles_path)
root = tree.getroot()

def find_style(style_id):
    for s in root.findall(w("style")):
        if s.get(w("styleId")) == style_id:
            return s
    return None

def get_or_create(parent, tag):
    e = parent.find(w(tag))
    if e is None:
        e = etree.SubElement(parent, w(tag))
    return e

def clear_children(el, *tags):
    for tag in tags:
        for child in el.findall(w(tag)):
            el.remove(child)

# ── helper: fully replace rPr / pPr on a style ─────────────────────────────
def set_style_rPr(style, props: dict):
    """props keys: font_ascii, font_hAnsi, font_cs, sz, bold, italic, color, spacing"""
    rPr = get_or_create(style, "rPr")
    clear_children(rPr, "rFonts", "sz", "szCs", "b", "i", "color",
                   "spacing", "kern", "smallCaps", "caps")

    if "font_ascii" in props or "font_hAnsi" in props:
        rf = etree.SubElement(rPr, w("rFonts"))
        if "font_ascii" in props:
            rf.set(w("ascii"),  props["font_ascii"])
            rf.set(w("hAnsi"), props.get("font_hAnsi", props["font_ascii"]))
        if "font_cs" in props:
            rf.set(w("cs"), props["font_cs"])

    if "sz" in props:
        s, cs = sz_el(props["sz"])
        rPr.append(s); rPr.append(cs)

    if props.get("bold"):
        rPr.append(etree.Element(w("b")))
        rPr.append(etree.Element(w("bCs")))

    if props.get("italic"):
        rPr.append(etree.Element(w("i")))
        rPr.append(etree.Element(w("iCs")))

    if "color" in props:
        rPr.append(color_el(props["color"]))

    if "kern" in props:
        k = etree.SubElement(rPr, w("kern"))
        k.set(w("val"), str(props["kern"]))

    if props.get("allcaps"):
        rPr.append(etree.Element(w("caps")))

def set_style_pPr(style, props: dict):
    """props: before, after, line, lineRule, indent_l, indent_r, jc,
              pBdr_bottom_color, pBdr_bottom_sz, keep_next, spacing_after_auto"""
    pPr = get_or_create(style, "pPr")
    clear_children(pPr, "spacing", "ind", "jc", "pBdr", "keepNext",
                   "outlineLvl", "contextualSpacing", "shd")

    sp_kwargs = {}
    if "before"    in props: sp_kwargs["before"]    = props["before"]
    if "after"     in props: sp_kwargs["after"]     = props["after"]
    if "line"      in props: sp_kwargs["line"]      = props["line"]
    if "lineRule"  in props: sp_kwargs["lineRule"]  = props["lineRule"]
    if sp_kwargs:
        pPr.append(spacing_el(**sp_kwargs))

    if "indent_l" in props or "indent_r" in props:
        pPr.append(ind_el(
            left=props.get("indent_l"),
            right=props.get("indent_r"),
            hanging=props.get("indent_hang"),
        ))

    if "jc" in props:
        pPr.append(wval("jc", props["jc"]))

    if "pBdr_bottom_color" in props:
        pBdr = etree.SubElement(pPr, w("pBdr"))
        pBdr.append(border_el("bottom",
            sz=str(props.get("pBdr_bottom_sz", 4)),
            color=props["pBdr_bottom_color"],
            space="4",
        ))

    if props.get("keep_next"):
        pPr.append(etree.Element(w("keepNext")))

    if "outline_lvl" in props:
        ol = etree.SubElement(pPr, w("outlineLvl"))
        ol.set(w("val"), str(props["outline_lvl"]))

    if props.get("contextual_spacing"):
        pPr.append(etree.Element(w("contextualSpacing")))

    if "shd_fill" in props:
        pPr.append(shd_el(props["shd_fill"]))

# ══════════════════════════════════════════════════════════════════════════════
# NORMAL  — body text
# ══════════════════════════════════════════════════════════════════════════════
s = find_style("Normal")
set_style_rPr(s, dict(font_ascii="Calibri", font_cs="Calibri",
                       sz=21, color=INK))          # 10.5 pt
set_style_pPr(s, dict(before=0, after=120, line=276, lineRule="auto",
                       jc="both"))

# ══════════════════════════════════════════════════════════════════════════════
# TITLE
# ══════════════════════════════════════════════════════════════════════════════
s = find_style("Title")
set_style_rPr(s, dict(font_ascii="Garamond", font_cs="Garamond",
                       sz=56, bold=True, color=NAVY, kern=28))    # 28 pt
set_style_pPr(s, dict(before=0, after=240,
                       pBdr_bottom_color=GOLD, pBdr_bottom_sz=12,
                       keep_next=True))

# Title char
sc = find_style("TitleChar")
if sc is not None:
    set_style_rPr(sc, dict(font_ascii="Garamond", font_cs="Garamond",
                            sz=56, bold=True, color=NAVY, kern=28))

# ══════════════════════════════════════════════════════════════════════════════
# SUBTITLE
# ══════════════════════════════════════════════════════════════════════════════
s = find_style("Subtitle")
set_style_rPr(s, dict(font_ascii="Calibri", font_cs="Calibri",
                       sz=20, italic=True, color=SLATE))           # 10 pt
set_style_pPr(s, dict(before=0, after=360, keep_next=True))

sc = find_style("SubtitleChar")
if sc is not None:
    set_style_rPr(sc, dict(font_ascii="Calibri", font_cs="Calibri",
                            sz=20, italic=True, color=SLATE))

# ══════════════════════════════════════════════════════════════════════════════
# HEADING 1  — section title (## in markdown)
# ══════════════════════════════════════════════════════════════════════════════
s = find_style("Heading1")
set_style_rPr(s, dict(font_ascii="Garamond", font_cs="Garamond",
                       sz=32, bold=True, color=NAVY))              # 16 pt
set_style_pPr(s, dict(before=480, after=120,
                       pBdr_bottom_color=NAVY, pBdr_bottom_sz=6,
                       keep_next=True, outline_lvl=0))

sc = find_style("Heading1Char")
if sc is not None:
    set_style_rPr(sc, dict(font_ascii="Garamond", font_cs="Garamond",
                            sz=32, bold=True, color=NAVY))

# ══════════════════════════════════════════════════════════════════════════════
# HEADING 2  — subsection (### in markdown)
# ══════════════════════════════════════════════════════════════════════════════
s = find_style("Heading2")
set_style_rPr(s, dict(font_ascii="Calibri", font_cs="Calibri",
                       sz=26, bold=True, color=NAVY_LIGHT))        # 13 pt
set_style_pPr(s, dict(before=360, after=80,
                       keep_next=True, outline_lvl=1))

sc = find_style("Heading2Char")
if sc is not None:
    set_style_rPr(sc, dict(font_ascii="Calibri", font_cs="Calibri",
                            sz=26, bold=True, color=NAVY_LIGHT))

# ══════════════════════════════════════════════════════════════════════════════
# HEADING 3  — labeled detail (#### in markdown)
# ══════════════════════════════════════════════════════════════════════════════
s = find_style("Heading3")
set_style_rPr(s, dict(font_ascii="Calibri", font_cs="Calibri",
                       sz=22, bold=True, italic=True, color=GOLD))  # 11 pt
set_style_pPr(s, dict(before=240, after=60,
                       keep_next=True, outline_lvl=2))

sc = find_style("Heading3Char")
if sc is not None:
    set_style_rPr(sc, dict(font_ascii="Calibri", font_cs="Calibri",
                            sz=22, bold=True, italic=True, color=GOLD))

# Heading 4–6: muted, progressively smaller
for sid, color_val, sz_val in [("Heading4", SLATE, 21),
                                 ("Heading5", SLATE, 21),
                                 ("Heading6", SLATE, 21)]:
    s = find_style(sid)
    if s is not None:
        set_style_rPr(s, dict(font_ascii="Calibri", font_cs="Calibri",
                               sz=sz_val, bold=True, color=color_val))
        set_style_pPr(s, dict(before=180, after=60, keep_next=True))

# ══════════════════════════════════════════════════════════════════════════════
# QUOTE / INTENSE QUOTE  — blockquotes
# ══════════════════════════════════════════════════════════════════════════════
s = find_style("Quote")
if s is not None:
    set_style_rPr(s, dict(font_ascii="Garamond", font_cs="Garamond",
                           sz=21, italic=True, color=SLATE))
    pPr = get_or_create(s, "pPr")
    clear_children(pPr, "ind", "pBdr", "spacing")
    pPr.append(ind_el(left=720, right=360))
    pPr.append(spacing_el(before=120, after=120))
    pBdr = etree.SubElement(pPr, w("pBdr"))
    pBdr.append(border_el("left", sz="24", color=GOLD, space="12",
                           val="single"))

s = find_style("IntenseQuote")
if s is not None:
    set_style_rPr(s, dict(font_ascii="Garamond", font_cs="Garamond",
                           sz=21, italic=True, bold=True, color=NAVY))
    pPr = get_or_create(s, "pPr")
    clear_children(pPr, "ind", "pBdr", "spacing", "shd")
    pPr.append(ind_el(left=720, right=360))
    pPr.append(spacing_el(before=120, after=120))
    pBdr = etree.SubElement(pPr, w("pBdr"))
    pBdr.append(border_el("left", sz="36", color=NAVY, space="12",
                           val="single"))

# ══════════════════════════════════════════════════════════════════════════════
# TABLE NORMAL  — base table style
# ══════════════════════════════════════════════════════════════════════════════
s = find_style("TableNormal")
if s is not None:
    # table-level properties
    tblPr = get_or_create(s, "tblPr")
    clear_children(tblPr, "tblBorders", "tblCellMar", "tblLook")

    borders = etree.SubElement(tblPr, w("tblBorders"))
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = etree.SubElement(borders, w(side))
        if side in ("insideH", "insideV"):
            b.set(w("val"), "single")
            b.set(w("sz"), "4")
            b.set(w("color"), RULE)
        else:
            b.set(w("val"), "single")
            b.set(w("sz"), "6")
            b.set(w("color"), NAVY)

    margins = etree.SubElement(tblPr, w("tblCellMar"))
    for side, val in [("top","60"), ("left","120"), ("bottom","60"), ("right","120")]:
        m = etree.SubElement(margins, w(side))
        m.set(w("w"), val)
        m.set(w("type"), "dxa")

    # cell-level rPr: Calibri 9.5pt
    tcPr = get_or_create(s, "tcPr")
    set_style_rPr(s, dict(font_ascii="Calibri", font_cs="Calibri",
                           sz=19, color=INK))

# ══════════════════════════════════════════════════════════════════════════════
# PAGE / DOCUMENT defaults  (docDefaults)
# ══════════════════════════════════════════════════════════════════════════════
docDefaults = root.find(w("docDefaults"))
if docDefaults is not None:
    rPrDefault = docDefaults.find(f".//{w('rPrDefault')}")
    if rPrDefault is None:
        rPrDefault = etree.SubElement(
            get_or_create(docDefaults, "rPrDefault"), "placeholder")
        rPrDefault = docDefaults.find(f".//{w('rPrDefault')}")

    rPr = get_or_create(rPrDefault, "rPr")
    clear_children(rPr, "rFonts", "sz", "szCs", "color", "kern")

    rf = etree.SubElement(rPr, w("rFonts"))
    rf.set(w("ascii"),  "Calibri")
    rf.set(w("hAnsi"),  "Calibri")
    rf.set(w("cs"),     "Calibri")
    s1, cs1 = sz_el(21)
    rPr.append(s1); rPr.append(cs1)
    rPr.append(color_el(INK))

# ══════════════════════════════════════════════════════════════════════════════
# Write styles.xml back
# ══════════════════════════════════════════════════════════════════════════════
tree.write(styles_path, xml_declaration=True,
           encoding="UTF-8", standalone=True)

# ── update page margins in document.xml for tighter layout ──────────────────
doc_path = os.path.join(TMP, "word", "document.xml")
if os.path.exists(doc_path):
    dtree = etree.parse(doc_path)
    droot = dtree.getroot()
    for pgMar in droot.iter(w("pgMar")):
        pgMar.set(w("top"),    "1080")   # 0.75"
        pgMar.set(w("bottom"), "1080")
        pgMar.set(w("left"),   "1260")   # 0.875"
        pgMar.set(w("right"),  "1260")
        pgMar.set(w("header"), "720")
        pgMar.set(w("footer"), "720")
    dtree.write(doc_path, xml_declaration=True,
                encoding="UTF-8", standalone=True)

# ── repack as .dotx  (content type must stay as template) ───────────────────
out_path = DEST
with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
    for dirpath, _, filenames in os.walk(TMP):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            arcname = os.path.relpath(full, TMP)
            zout.write(full, arcname)

print(f"✓  reference.dotx written → {out_path}")
