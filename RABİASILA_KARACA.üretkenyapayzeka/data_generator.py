# -*- coding: utf-8 -*-
"""
data_generator.py
=================
50.000 adet benzersiz "Doğal Dil -> {VBA_Code, CadQuery_Code}" eşleşmesi üretir.

Desteklenen operasyonlar:
    - Extrude (Boss-Extrude)
    - Revolve
    - Cut-Extrude
    - Fillet
    - Chamfer
    - Circular Pattern
    - Linear Pattern

Çıktı:
    dataset.jsonl  -> her satır: {"prompt": ..., "vba": ..., "cadquery": ..., "op": ...}
"""

from __future__ import annotations
import json
import os
import random
import itertools
from dataclasses import dataclass, asdict
from typing import List, Dict, Callable

# --------------------------------------------------------------------------- #
#  Sabit listeler (Doğal dil çeşitliliği için)                                #
# --------------------------------------------------------------------------- #

TR_VERBS_EXTRUDE = ["oluştur", "üret", "çıkar", "ekstrüde et", "yükselt"]
EN_VERBS_EXTRUDE = ["create", "make", "extrude", "build"]
SHAPES_TR = {"rectangle": "dikdörtgen", "circle": "daire", "polygon": "çokgen"}
PLANES = ["XY", "XZ", "YZ"]
PLANE_VBA = {"XY": "Top", "XZ": "Front", "YZ": "Right"}

# --------------------------------------------------------------------------- #
#  VBA şablonları                                                             #
# --------------------------------------------------------------------------- #

VBA_HEADER = """' SolidWorks VBA Macro - Auto generated
Dim swApp As Object
Dim Part As Object
Dim boolstatus As Boolean
Sub main()
    Set swApp = Application.SldWorks
    Set Part = swApp.ActiveDoc
    If Part Is Nothing Then
        Set Part = swApp.NewPart
    End If
"""

VBA_FOOTER = "End Sub\n"


def vba_sketch_rect(plane: str, w: float, h: float) -> str:
    """Verilen düzlem üzerine merkez-orijinli dikdörtgen sketch oluşturur."""
    return (
        f'    boolstatus = Part.Extension.SelectByID2("{PLANE_VBA[plane]} Plane", '
        f'"PLANE", 0, 0, 0, False, 0, Nothing, 0)\n'
        f'    Part.SketchManager.InsertSketch True\n'
        f'    Part.SketchManager.CreateCenterRectangle 0, 0, 0, '
        f'{w/2000:.6f}, {h/2000:.6f}, 0\n'
        f'    Part.SketchManager.InsertSketch True\n'
    )


def vba_sketch_circle(plane: str, r: float) -> str:
    return (
        f'    boolstatus = Part.Extension.SelectByID2("{PLANE_VBA[plane]} Plane", '
        f'"PLANE", 0, 0, 0, False, 0, Nothing, 0)\n'
        f'    Part.SketchManager.InsertSketch True\n'
        f'    Part.SketchManager.CreateCircleByRadius 0, 0, 0, {r/1000:.6f}\n'
        f'    Part.SketchManager.InsertSketch True\n'
    )


def vba_extrude(depth: float) -> str:
    return (
        f'    Part.FeatureManager.FeatureExtrusion3 True, False, False, 0, 0, '
        f'{depth/1000:.6f}, 0.01, False, False, False, False, 0, 0, '
        f'False, False, False, False, True, True, True, 0, 0, False\n'
    )


def vba_cut_extrude(depth: float) -> str:
    return (
        f'    Part.FeatureManager.FeatureCut4 True, False, False, 0, 0, '
        f'{depth/1000:.6f}, 0.01, False, False, False, False, 0, 0, '
        f'False, False, False, False, False, True, True, True, True, '
        f'False, 0, 0, False, False\n'
    )


def vba_revolve(angle_deg: float) -> str:
    rad = angle_deg * 3.14159265 / 180.0
    return (
        f'    Part.FeatureManager.FeatureRevolve2 True, True, False, False, False, '
        f'False, 0, 0, {rad:.6f}, 0, False, False, 0.01, 0.01, 0, 0, 0, '
        f'True, True, True\n'
    )


def vba_fillet(radius: float) -> str:
    return (
        f'    Part.FeatureManager.FeatureFillet3 195, {radius/1000:.6f}, '
        f'0, 0, 0, 0, 0, Empty, Empty, Empty, Empty, Empty, Empty, Empty, Empty\n'
    )


def vba_chamfer(distance: float) -> str:
    return (
        f'    Part.FeatureManager.InsertFeatureChamfer 4, 1, '
        f'{distance/1000:.6f}, 0.78539, 0, 0, 0\n'
    )


def vba_linear_pattern(n: int, spacing: float) -> str:
    return (
        f'    Part.FeatureManager.FeatureLinearPattern5 {n}, '
        f'{spacing/1000:.6f}, 1, 0.01, False, False, '
        f'"NULL", "NULL", False, False, False, False, False, False, '
        f'True, True, False, False, 0, 0\n'
    )


def vba_circular_pattern(n: int, angle_deg: float = 360.0) -> str:
    rad = angle_deg * 3.14159265 / 180.0
    return (
        f'    Part.FeatureManager.FeatureCircularPattern5 {n}, '
        f'{rad:.6f}, False, "NULL", False, True, False\n'
    )


# --------------------------------------------------------------------------- #
#  CadQuery şablonları                                                        #
# --------------------------------------------------------------------------- #

CQ_HEADER = "import cadquery as cq\n\n"


def cq_extrude_rect(plane: str, w: float, h: float, depth: float) -> str:
    return (
        f'result = (cq.Workplane("{plane}")\n'
        f'    .rect({w}, {h})\n'
        f'    .extrude({depth}))\n'
    )


def cq_extrude_circle(plane: str, r: float, depth: float) -> str:
    return (
        f'result = (cq.Workplane("{plane}")\n'
        f'    .circle({r})\n'
        f'    .extrude({depth}))\n'
    )


def cq_revolve_profile(plane: str, w: float, h: float, angle: float) -> str:
    return (
        f'result = (cq.Workplane("{plane}")\n'
        f'    .rect({w}, {h})\n'
        f'    .revolve({angle}, (0, 0, 0), (0, 1, 0)))\n'
    )


def cq_cut_extrude(plane: str, r: float, depth: float) -> str:
    return (
        f'result = (result.faces(">Z").workplane()\n'
        f'    .circle({r})\n'
        f'    .cutBlind(-{depth}))\n'
    )


def cq_fillet(radius: float) -> str:
    return f'result = result.edges("|Z").fillet({radius})\n'


def cq_chamfer(distance: float) -> str:
    return f'result = result.edges("|Z").chamfer({distance})\n'


def cq_linear_pattern(n: int, spacing: float, r: float, depth: float) -> str:
    """CadQuery'de pattern -> noktaları manuel pushPoints ile."""
    pts = ", ".join(f"({i*spacing:.3f}, 0)" for i in range(n))
    return (
        f'result = (result.faces(">Z").workplane()\n'
        f'    .pushPoints([{pts}])\n'
        f'    .circle({r}).cutBlind(-{depth}))\n'
    )


def cq_circular_pattern(n: int, radius: float, hole_r: float, depth: float) -> str:
    return (
        f'result = (result.faces(">Z").workplane()\n'
        f'    .polarArray({radius}, 0, 360, {n})\n'
        f'    .circle({hole_r}).cutBlind(-{depth}))\n'
    )


# --------------------------------------------------------------------------- #
#  Doğal dil cümle üreticileri                                                #
# --------------------------------------------------------------------------- #

def nl_extrude(shape: str, dims: Dict, depth: float, plane: str, lang: str) -> str:
    if lang == "tr":
        if shape == "rectangle":
            return (f"{plane} düzleminde {dims['w']}x{dims['h']} mm "
                    f"dikdörtgen çiz ve {depth} mm ekstrüde et")
        if shape == "circle":
            return (f"{plane} düzleminde yarıçapı {dims['r']} mm olan daire "
                    f"oluştur ve {depth} mm yüksekliğe çıkar")
    else:
        if shape == "rectangle":
            return (f"On {plane} plane sketch a {dims['w']}x{dims['h']} mm "
                    f"rectangle and extrude it {depth} mm")
        if shape == "circle":
            return (f"Create a circle of radius {dims['r']} mm on {plane} plane "
                    f"and extrude {depth} mm")
    return ""


# --------------------------------------------------------------------------- #
#  Örnek üreticiler (her biri tek bir kayıt döner)                            #
# --------------------------------------------------------------------------- #

@dataclass
class Sample:
    prompt: str
    vba: str
    cadquery: str
    op: str


def gen_extrude(rng: random.Random) -> Sample:
    shape = rng.choice(["rectangle", "circle"])
    plane = rng.choice(PLANES)
    depth = rng.randint(2, 200)
    lang = rng.choice(["tr", "en"])

    if shape == "rectangle":
        w, h = rng.randint(5, 300), rng.randint(5, 300)
        prompt = nl_extrude(shape, {"w": w, "h": h}, depth, plane, lang)
        vba = VBA_HEADER + vba_sketch_rect(plane, w, h) + vba_extrude(depth) + VBA_FOOTER
        cq = CQ_HEADER + cq_extrude_rect(plane, w, h, depth)
    else:
        r = rng.randint(3, 150)
        prompt = nl_extrude(shape, {"r": r}, depth, plane, lang)
        vba = VBA_HEADER + vba_sketch_circle(plane, r) + vba_extrude(depth) + VBA_FOOTER
        cq = CQ_HEADER + cq_extrude_circle(plane, r, depth)
    return Sample(prompt, vba, cq, "extrude")


def gen_revolve(rng: random.Random) -> Sample:
    plane = rng.choice(PLANES)
    w, h = rng.randint(5, 100), rng.randint(5, 200)
    angle = rng.choice([90, 180, 270, 360])
    lang = rng.choice(["tr", "en"])
    if lang == "tr":
        prompt = (f"{plane} düzleminde {w}x{h} mm profili Y ekseni etrafında "
                  f"{angle} derece döndür (revolve)")
    else:
        prompt = (f"Revolve a {w}x{h} mm profile on {plane} plane around Y axis "
                  f"by {angle} degrees")
    vba = VBA_HEADER + vba_sketch_rect(plane, w, h) + vba_revolve(angle) + VBA_FOOTER
    cq = CQ_HEADER + cq_revolve_profile(plane, w, h, angle)
    return Sample(prompt, vba, cq, "revolve")


def gen_cut_extrude(rng: random.Random) -> Sample:
    """Önce blok oluştur, sonra üst yüzeyden delik aç."""
    w = rng.randint(20, 200)
    h = rng.randint(20, 200)
    base_d = rng.randint(5, 50)
    hole_r = rng.randint(2, min(w, h) // 4)
    cut_d = rng.randint(2, base_d)
    lang = rng.choice(["tr", "en"])
    if lang == "tr":
        prompt = (f"{w}x{h}x{base_d} mm blok oluştur, üst yüzeyine "
                  f"yarıçapı {hole_r} mm olan {cut_d} mm derinliğinde delik aç")
    else:
        prompt = (f"Create a {w}x{h}x{base_d} mm block and cut a {hole_r} mm "
                  f"radius hole {cut_d} mm deep on the top face")
    vba = (VBA_HEADER
           + vba_sketch_rect("XY", w, h) + vba_extrude(base_d)
           + vba_sketch_circle("XY", hole_r) + vba_cut_extrude(cut_d)
           + VBA_FOOTER)
    cq = (CQ_HEADER
          + cq_extrude_rect("XY", w, h, base_d)
          + cq_cut_extrude("XY", hole_r, cut_d))
    return Sample(prompt, vba, cq, "cut_extrude")


def gen_fillet(rng: random.Random) -> Sample:
    w = rng.randint(20, 200)
    h = rng.randint(20, 200)
    d = rng.randint(5, 50)
    r = rng.randint(1, min(w, h) // 6)
    lang = rng.choice(["tr", "en"])
    if lang == "tr":
        prompt = (f"{w}x{h}x{d} mm bir blok oluştur ve dikey kenarlarına "
                  f"{r} mm yarıçaplı fillet uygula")
    else:
        prompt = (f"Create a {w}x{h}x{d} mm block and apply a {r} mm fillet "
                  f"to the vertical edges")
    vba = (VBA_HEADER + vba_sketch_rect("XY", w, h) + vba_extrude(d)
           + vba_fillet(r) + VBA_FOOTER)
    cq = CQ_HEADER + cq_extrude_rect("XY", w, h, d) + cq_fillet(r)
    return Sample(prompt, vba, cq, "fillet")


def gen_chamfer(rng: random.Random) -> Sample:
    w = rng.randint(20, 200)
    h = rng.randint(20, 200)
    d = rng.randint(5, 50)
    c = rng.randint(1, min(w, h) // 8)
    lang = rng.choice(["tr", "en"])
    if lang == "tr":
        prompt = (f"{w}x{h}x{d} mm blok oluştur ve dikey kenarlara "
                  f"{c} mm chamfer uygula")
    else:
        prompt = (f"Build a {w}x{h}x{d} mm block and apply a {c} mm chamfer "
                  f"to vertical edges")
    vba = (VBA_HEADER + vba_sketch_rect("XY", w, h) + vba_extrude(d)
           + vba_chamfer(c) + VBA_FOOTER)
    cq = CQ_HEADER + cq_extrude_rect("XY", w, h, d) + cq_chamfer(c)
    return Sample(prompt, vba, cq, "chamfer")


def gen_linear_pattern(rng: random.Random) -> Sample:
    w = rng.randint(80, 300)
    h = rng.randint(40, 150)
    d = rng.randint(5, 30)
    n = rng.randint(2, 8)
    spacing = rng.randint(10, w // max(n, 2))
    hole_r = rng.randint(2, 8)
    lang = rng.choice(["tr", "en"])
    if lang == "tr":
        prompt = (f"{w}x{h}x{d} mm plaka oluştur ve {hole_r} mm yarıçaplı "
                  f"{n} adet deliği {spacing} mm aralıkla doğrusal dizilimle aç")
    else:
        prompt = (f"Create a {w}x{h}x{d} mm plate and place {n} holes of "
                  f"{hole_r} mm radius in a linear pattern with {spacing} mm spacing")
    vba = (VBA_HEADER + vba_sketch_rect("XY", w, h) + vba_extrude(d)
           + vba_sketch_circle("XY", hole_r) + vba_cut_extrude(d)
           + vba_linear_pattern(n, spacing) + VBA_FOOTER)
    cq = (CQ_HEADER + cq_extrude_rect("XY", w, h, d)
          + cq_linear_pattern(n, spacing, hole_r, d))
    return Sample(prompt, vba, cq, "linear_pattern")


def gen_circular_pattern(rng: random.Random) -> Sample:
    radius = rng.randint(40, 150)
    base_d = rng.randint(5, 25)
    n = rng.randint(3, 12)
    hole_r = rng.randint(2, 8)
    pcd = rng.randint(20, radius - 5)
    lang = rng.choice(["tr", "en"])
    if lang == "tr":
        prompt = (f"Yarıçapı {radius} mm, kalınlığı {base_d} mm disk oluştur ve "
                  f"PCD {pcd} mm üzerinde {n} adet {hole_r} mm yarıçaplı deliği "
                  f"dairesel dizilim ile aç")
    else:
        prompt = (f"Create a {radius} mm radius disk of thickness {base_d} mm "
                  f"and pattern {n} holes of {hole_r} mm radius circularly on a "
                  f"{pcd} mm PCD")
    vba = (VBA_HEADER + vba_sketch_circle("XY", radius) + vba_extrude(base_d)
           + vba_sketch_circle("XY", hole_r) + vba_cut_extrude(base_d)
           + vba_circular_pattern(n) + VBA_FOOTER)
    cq = (CQ_HEADER + cq_extrude_circle("XY", radius, base_d)
          + cq_circular_pattern(n, pcd, hole_r, base_d))
    return Sample(prompt, vba, cq, "circular_pattern")


# --------------------------------------------------------------------------- #
#  Master generator                                                           #
# --------------------------------------------------------------------------- #

GENERATORS: Dict[str, Callable] = {
    "extrude": gen_extrude,
    "revolve": gen_revolve,
    "cut_extrude": gen_cut_extrude,
    "fillet": gen_fillet,
    "chamfer": gen_chamfer,
    "linear_pattern": gen_linear_pattern,
    "circular_pattern": gen_circular_pattern,
}


def build_dataset(n: int = 50_000,
                  out_path: str = "dataset.jsonl",
                  seed: int = 42) -> str:
    """N örnekli veri setini üretir. Operasyonlar dengeli dağıtılır."""
    rng = random.Random(seed)
    ops = list(GENERATORS.keys())
    seen_prompts = set()
    written = 0

    with open(out_path, "w", encoding="utf-8") as f:
        # round-robin + rastgele seçim ile dengeli dağılım
        for i in itertools.count():
            if written >= n:
                break
            op = ops[i % len(ops)] if rng.random() < 0.5 else rng.choice(ops)
            sample = GENERATORS[op](rng)

            # Tekilleştirme
            if sample.prompt in seen_prompts:
                continue
            seen_prompts.add(sample.prompt)
            f.write(json.dumps(asdict(sample), ensure_ascii=False) + "\n")
            written += 1

            if written % 5000 == 0:
                print(f"  -> {written}/{n} kayıt üretildi")

    print(f"[OK] {written} kayıt yazıldı -> {out_path}")
    return out_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--num", type=int, default=50_000)
    ap.add_argument("-o", "--out", type=str, default="dataset.jsonl")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    build_dataset(args.num, args.out, args.seed)
