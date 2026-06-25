# -*- coding: utf-8 -*-
"""
export_report.py
================
- VBA kodunu .swp veya .txt olarak diske yazar (download için).
- Akademik metrikler:
    * Accuracy        : modelin ürettiği op etiketinin beklenenle eşleşmesi
    * Millimetric Consistency : NL içindeki sayısal değerlerin VBA + CadQuery
                               kodunda doğru korunup korunmadığı
    * Code Validity   : CadQuery kodunun hatasız çalışıp çalışmadığı
"""

from __future__ import annotations
import json
import os
import re
import tempfile
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple


# --------------------------------------------------------------------------- #
#  EXPORT                                                                     #
# --------------------------------------------------------------------------- #

def save_vba(code: str, path: Optional[str] = None, ext: str = "swp") -> str:
    """
    VBA kodunu kaydeder. SolidWorks .swp aslında bir VBA proje dosyasıdır,
    biz salt-metin export verdiğimiz için .txt önerilir; .swp uzantısı
    gönderim/teslim adı içindir.
    """
    assert ext in ("swp", "txt", "bas"), "ext: swp/txt/bas"
    if path is None:
        path = tempfile.NamedTemporaryFile(
            suffix=f".{ext}", delete=False, mode="w", encoding="utf-8").name
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    return path


# --------------------------------------------------------------------------- #
#  METRİKLER                                                                  #
# --------------------------------------------------------------------------- #

NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def extract_numbers(text: str) -> List[float]:
    return [float(x.replace(",", ".")) for x in NUM_RE.findall(text)]


def millimetric_consistency(prompt: str, vba: str, cq: str) -> float:
    """
    Prompt içindeki sayıların VBA ve/veya CadQuery'de bulunma oranı.
    VBA metrik birime (m) çevirdiği için sayıları /1000 toleranslı arar.
    """
    nums = extract_numbers(prompt)
    if not nums:
        return 1.0
    found = 0
    for n in nums:
        as_mm_int = str(int(n)) if n.is_integer() else f"{n:g}"
        as_meter = f"{n/1000:.6f}".rstrip("0").rstrip(".")
        if (as_mm_int in cq) or (as_meter in vba) or (as_mm_int in vba):
            found += 1
    return found / len(nums)


def op_accuracy(predicted_op: str, expected_op: str) -> float:
    return 1.0 if predicted_op == expected_op else 0.0


def code_validity(cq_code: str) -> Tuple[bool, str]:
    """CadQuery kodunu yürütüp geçerli `result` üretip üretmediğini test eder."""
    try:
        from visualizer import execute_cadquery
        execute_cadquery(cq_code)
        return True, ""
    except Exception as e:
        return False, str(e)


@dataclass
class MetricsReport:
    n: int
    accuracy: float
    mm_consistency: float
    code_validity: float
    per_op_accuracy: Dict[str, float]

    def as_dict(self):
        return asdict(self)

    def pretty(self) -> str:
        lines = [
            "=== Akademik Başarı Raporu ===",
            f"Örnek sayısı           : {self.n}",
            f"Op-Accuracy            : {self.accuracy*100:.2f}%",
            f"Millimetric Consistency: {self.mm_consistency*100:.2f}%",
            f"Code Validity (CQ run) : {self.code_validity*100:.2f}%",
            "Operasyon başına doğruluk:",
        ]
        for k, v in self.per_op_accuracy.items():
            lines.append(f"  - {k:18s}: {v*100:.1f}%")
        return "\n".join(lines)


def evaluate(model, dataset_path: str, sample_size: int = 200,
             check_validity: bool = True) -> MetricsReport:
    """
    `model` -> `predict(prompt)` -> {vba, cadquery, op}
    """
    import random
    rng = random.Random(0)
    rows = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    rng.shuffle(rows)
    rows = rows[:sample_size]

    acc_sum = mm_sum = val_sum = 0.0
    per_op_total: Dict[str, int] = {}
    per_op_hit: Dict[str, int] = {}

    for r in rows:
        pred = model.predict(r["prompt"])
        a = op_accuracy(pred.get("op", ""), r["op"])
        m = millimetric_consistency(r["prompt"], pred["vba"], pred["cadquery"])
        if check_validity:
            ok, _ = code_validity(pred["cadquery"])
        else:
            ok = True
        acc_sum += a
        mm_sum += m
        val_sum += 1.0 if ok else 0.0
        per_op_total[r["op"]] = per_op_total.get(r["op"], 0) + 1
        per_op_hit[r["op"]] = per_op_hit.get(r["op"], 0) + int(a)

    n = len(rows) or 1
    per_op = {k: per_op_hit.get(k, 0) / v for k, v in per_op_total.items()}
    return MetricsReport(
        n=n,
        accuracy=acc_sum / n,
        mm_consistency=mm_sum / n,
        code_validity=val_sum / n,
        per_op_accuracy=per_op,
    )


if __name__ == "__main__":
    import argparse
    from ai_model_setup import get_model
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset.jsonl")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--no-validity", action="store_true")
    args = ap.parse_args()
    rep = evaluate(get_model(), args.data, args.n,
                   check_validity=not args.no_validity)
    print(rep.pretty())
