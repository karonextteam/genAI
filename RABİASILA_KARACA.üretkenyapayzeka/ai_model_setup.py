# -*- coding: utf-8 -*-
"""
ai_model_setup.py
=================
Hibrit zeka katmanı:
    - 50k JSONL veri setini Hugging Face Dataset formatına çevirir.
    - DeepSeek-Coder / CodeT5 / küçük alternatif modelleri seq2seq fine-tune eder.
    - State Management: ConversationState sınıfı, daha önce üretilen CadQuery
      kodunu hatırlar ve yeni komut geldiğinde onun ÜZERİNE inşa eden prompt
      hazırlar (incremental modeling).

Colab GPU'da çalışacak şekilde yapılandırılmıştır. Eğitim opsiyoneldir; eğitim
yapılmadığı durumlarda DeterministicFallbackModel devreye girer ve veri
üreteci kuralları üzerinden çalışır (demo modu).
"""

from __future__ import annotations
import json
import os
import re
import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

# --------------------------------------------------------------------------- #
#  1) Veri yükleme ve tokenizasyon                                            #
# --------------------------------------------------------------------------- #

def load_jsonl(path: str) -> List[Dict]:
    """JSONL dosyasını listeye yükler."""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def to_hf_dataset(rows: List[Dict]):
    """HuggingFace Datasets formatına çevirir.
    Her örnek için input = NL prompt, target = JSON içinde VBA + CadQuery kodları."""
    try:
        from datasets import Dataset
    except ImportError as e:
        raise ImportError("`datasets` kütüphanesini kurun: pip install datasets") from e

    inputs, targets = [], []
    for r in rows:
        inputs.append(f"Generate CAD code for: {r['prompt']}")
        targets.append(json.dumps(
            {"vba": r["vba"], "cadquery": r["cadquery"]},
            ensure_ascii=False
        ))
    return Dataset.from_dict({"input": inputs, "target": targets})


# --------------------------------------------------------------------------- #
#  2) Fine-tuning pipeline (Seq2Seq)                                          #
# --------------------------------------------------------------------------- #

def fine_tune(
    dataset_path: str = "dataset.jsonl",
    model_name: str = "Salesforce/codet5-small",
    output_dir: str = "./cad_model",
    epochs: int = 1,
    batch_size: int = 4,
    max_input_len: int = 256,
    max_target_len: int = 512,
    subset: Optional[int] = None,
):
    """
    Seq2Seq fine-tune pipeline.
    - Default: codet5-small (Colab T4 üzerinde rahatlıkla çalışır)
    - DeepSeek-Coder isteyen kullanıcı: model_name="deepseek-ai/deepseek-coder-1.3b-base"
      (causal LM olduğundan o durumda CausalLM dalına geçer.)
    """
    import torch
    from transformers import (
        AutoTokenizer, AutoModelForSeq2SeqLM, AutoModelForCausalLM,
        Seq2SeqTrainingArguments, Seq2SeqTrainer, DataCollatorForSeq2Seq,
        TrainingArguments, Trainer, DataCollatorForLanguageModeling,
    )

    rows = load_jsonl(dataset_path)
    if subset:
        rows = rows[:subset]
    ds = to_hf_dataset(rows).train_test_split(test_size=0.05, seed=42)

    is_seq2seq = "t5" in model_name.lower() or "bart" in model_name.lower()
    # use_fast=False -> Colab'de tokenizers/sentencepiece çakışmalarını önler
    tokenizer = AutoTokenizer.from_pretrained(
        model_name, trust_remote_code=True, use_fast=False
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if is_seq2seq:
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

        def tok(batch):
            mi = tokenizer(batch["input"], max_length=max_input_len,
                           truncation=True, padding="max_length")
            mt = tokenizer(batch["target"], max_length=max_target_len,
                           truncation=True, padding="max_length")
            mi["labels"] = mt["input_ids"]
            return mi

        tokenized = ds.map(tok, batched=True, remove_columns=["input", "target"])
        args = Seq2SeqTrainingArguments(
            output_dir=output_dir,
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            logging_steps=50,
            save_strategy="epoch",
            evaluation_strategy="epoch",
            predict_with_generate=True,
            fp16=torch.cuda.is_available(),
            report_to="none",
        )
        trainer = Seq2SeqTrainer(
            model=model,
            args=args,
            train_dataset=tokenized["train"],
            eval_dataset=tokenized["test"],
            tokenizer=tokenizer,
            data_collator=DataCollatorForSeq2Seq(tokenizer, model=model),
        )
    else:
        # Causal LM (DeepSeek vb.)
        model = AutoModelForCausalLM.from_pretrained(
            model_name, trust_remote_code=True,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        )

        def tok(batch):
            text = [f"### Instruction:\n{i}\n### Response:\n{t}{tokenizer.eos_token}"
                    for i, t in zip(batch["input"], batch["target"])]
            return tokenizer(text, max_length=max_input_len + max_target_len,
                             truncation=True, padding="max_length")

        tokenized = ds.map(tok, batched=True, remove_columns=["input", "target"])
        args = TrainingArguments(
            output_dir=output_dir,
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            logging_steps=50,
            save_strategy="epoch",
            fp16=torch.cuda.is_available(),
            report_to="none",
        )
        trainer = Trainer(
            model=model,
            args=args,
            train_dataset=tokenized["train"],
            eval_dataset=tokenized["test"],
            tokenizer=tokenizer,
            data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
        )

    trainer.train()
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"[OK] Model kaydedildi -> {output_dir}")
    return output_dir


# --------------------------------------------------------------------------- #
#  3) Inference + Deterministic Fallback                                      #
# --------------------------------------------------------------------------- #

class DeterministicFallbackModel:
    """
    Eğitim yapılmadıysa veya GPU yoksa kuralla doğal dilden VBA + CadQuery
    çıktısı üreten yedek modeldir. data_generator içindeki regex-yardımcılarını
    kullanarak çoğu komutu doğru şekilde işler.
    """

    NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")

    def _nums(self, txt: str) -> List[float]:
        return [float(x.replace(",", ".")) for x in self.NUM_RE.findall(txt)]

    def predict(self, prompt: str) -> Dict[str, str]:
        from data_generator import (
            VBA_HEADER, VBA_FOOTER,
            vba_sketch_rect, vba_sketch_circle, vba_extrude, vba_cut_extrude,
            vba_revolve, vba_fillet, vba_chamfer, vba_linear_pattern,
            vba_circular_pattern,
            CQ_HEADER, cq_extrude_rect, cq_extrude_circle, cq_revolve_profile,
            cq_cut_extrude, cq_fillet, cq_chamfer, cq_linear_pattern,
            cq_circular_pattern,
        )

        p = prompt.lower()
        nums = self._nums(p)
        plane = "XY"
        for pl in ("xy", "xz", "yz"):
            if pl in p:
                plane = pl.upper()
                break

        # Operasyon tespiti
        if any(k in p for k in ("revolve", "döndür", "dondur")):
            w, h = (nums + [40, 80])[:2]
            angle = next((n for n in nums if n in (90, 180, 270, 360)), 360)
            vba = VBA_HEADER + vba_sketch_rect(plane, w, h) + vba_revolve(angle) + VBA_FOOTER
            cq = CQ_HEADER + cq_revolve_profile(plane, w, h, angle)
            return {"vba": vba, "cadquery": cq, "op": "revolve"}

        if any(k in p for k in ("circular pattern", "dairesel dizil", "polar")):
            radius = nums[0] if nums else 60
            base_d = nums[1] if len(nums) > 1 else 10
            n = int(nums[2]) if len(nums) > 2 else 6
            hole_r = nums[3] if len(nums) > 3 else 4
            pcd = nums[4] if len(nums) > 4 else max(radius - 10, 20)
            vba = (VBA_HEADER + vba_sketch_circle(plane, radius) + vba_extrude(base_d)
                   + vba_sketch_circle(plane, hole_r) + vba_cut_extrude(base_d)
                   + vba_circular_pattern(n) + VBA_FOOTER)
            cq = (CQ_HEADER + cq_extrude_circle(plane, radius, base_d)
                  + cq_circular_pattern(n, pcd, hole_r, base_d))
            return {"vba": vba, "cadquery": cq, "op": "circular_pattern"}

        if any(k in p for k in ("linear pattern", "doğrusal dizil", "dogrusal dizil")):
            w, h, d = (nums + [120, 60, 10])[:3]
            n = int(nums[3]) if len(nums) > 3 else 4
            spacing = nums[4] if len(nums) > 4 else 20
            hole_r = nums[5] if len(nums) > 5 else 4
            vba = (VBA_HEADER + vba_sketch_rect(plane, w, h) + vba_extrude(d)
                   + vba_sketch_circle(plane, hole_r) + vba_cut_extrude(d)
                   + vba_linear_pattern(n, spacing) + VBA_FOOTER)
            cq = (CQ_HEADER + cq_extrude_rect(plane, w, h, d)
                  + cq_linear_pattern(n, spacing, hole_r, d))
            return {"vba": vba, "cadquery": cq, "op": "linear_pattern"}

        if "fillet" in p or "yuvarlat" in p:
            w, h, d, r = (nums + [60, 60, 10, 5])[:4]
            vba = (VBA_HEADER + vba_sketch_rect(plane, w, h) + vba_extrude(d)
                   + vba_fillet(r) + VBA_FOOTER)
            cq = CQ_HEADER + cq_extrude_rect(plane, w, h, d) + cq_fillet(r)
            return {"vba": vba, "cadquery": cq, "op": "fillet"}

        if "chamfer" in p or "pah" in p:
            w, h, d, c = (nums + [60, 60, 10, 3])[:4]
            vba = (VBA_HEADER + vba_sketch_rect(plane, w, h) + vba_extrude(d)
                   + vba_chamfer(c) + VBA_FOOTER)
            cq = CQ_HEADER + cq_extrude_rect(plane, w, h, d) + cq_chamfer(c)
            return {"vba": vba, "cadquery": cq, "op": "chamfer"}

        if any(k in p for k in ("delik", "hole", "cut", "kes")):
            w, h, base_d = (nums + [80, 80, 15])[:3]
            hole_r = nums[3] if len(nums) > 3 else 5
            cut_d = nums[4] if len(nums) > 4 else base_d
            vba = (VBA_HEADER + vba_sketch_rect(plane, w, h) + vba_extrude(base_d)
                   + vba_sketch_circle(plane, hole_r) + vba_cut_extrude(cut_d)
                   + VBA_FOOTER)
            cq = (CQ_HEADER + cq_extrude_rect(plane, w, h, base_d)
                  + cq_cut_extrude(plane, hole_r, cut_d))
            return {"vba": vba, "cadquery": cq, "op": "cut_extrude"}

        # Default: extrude
        if "daire" in p or "circle" in p or "silindir" in p or "cylinder" in p:
            r = nums[0] if nums else 25
            d = nums[1] if len(nums) > 1 else 20
            vba = VBA_HEADER + vba_sketch_circle(plane, r) + vba_extrude(d) + VBA_FOOTER
            cq = CQ_HEADER + cq_extrude_circle(plane, r, d)
            return {"vba": vba, "cadquery": cq, "op": "extrude"}

        w, h, d = (nums + [50, 50, 10])[:3]
        vba = VBA_HEADER + vba_sketch_rect(plane, w, h) + vba_extrude(d) + VBA_FOOTER
        cq = CQ_HEADER + cq_extrude_rect(plane, w, h, d)
        return {"vba": vba, "cadquery": cq, "op": "extrude"}


class FineTunedModel:
    """Fine-tune edilmiş model için inference sarmalayıcısı."""

    def __init__(self, model_dir: str):
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_dir)
        self.model.eval()

    @staticmethod
    def _detect_op(cq_code: str) -> str:
        """CadQuery kodundan operasyon etiketini çıkarır."""
        c = cq_code.lower()
        if "polararray" in c:
            return "circular_pattern"
        if "pushpoints" in c and "cutblind" in c:
            return "linear_pattern"
        if ".chamfer(" in c:
            return "chamfer"
        if ".fillet(" in c:
            return "fillet"
        if ".revolve(" in c:
            return "revolve"
        if "cutblind" in c:
            return "cut_extrude"
        if ".extrude(" in c:
            return "extrude"
        return "unknown"

    def predict(self, prompt: str) -> Dict[str, str]:
        import torch
        text = f"Generate CAD code for: {prompt}"
        ids = self.tokenizer(text, return_tensors="pt", truncation=True,
                             max_length=256).input_ids
        with torch.no_grad():
            out = self.model.generate(ids, max_length=512, num_beams=4)
        decoded = self.tokenizer.decode(out[0], skip_special_tokens=True)
        try:
            obj = json.loads(decoded)
            # op etiketini koddan otomatik tespit et
            obj["op"] = self._detect_op(obj.get("cadquery", ""))
            return obj
        except Exception:
            # Bozuk JSON gelirse fallback'e devret
            return DeterministicFallbackModel().predict(prompt)


# --------------------------------------------------------------------------- #
#  4) State Management - context-aware incremental modeling                   #
# --------------------------------------------------------------------------- #

@dataclass
class ConversationState:
    """
    Kullanıcının önceki adımlarını saklar. Yeni komut geldiğinde model çıktısı
    içindeki CadQuery kodunu, mevcut `result` üzerine OPERATION OLARAK ekler
    (yeni `result = ...` satırını silip uygun chain'i ekler).
    """
    history_prompts: List[str] = field(default_factory=list)
    cadquery_code: str = ""        # Birikmiş CadQuery kodu
    vba_code: str = ""             # Birikmiş VBA kodu (header + body + footer)
    last_op: str = ""

    def reset(self):
        self.history_prompts.clear()
        self.cadquery_code = ""
        self.vba_code = ""
        self.last_op = ""

    @staticmethod
    def _strip_cq_header(code: str) -> str:
        return code.replace("import cadquery as cq\n\n", "").strip()

    @staticmethod
    def _strip_vba_wrapper(code: str) -> Tuple[str, str, str]:
        """VBA kodunu (header, body, footer) olarak parçalar."""
        from data_generator import VBA_HEADER, VBA_FOOTER
        body = code.replace(VBA_HEADER, "").replace(VBA_FOOTER, "")
        return VBA_HEADER, body, VBA_FOOTER

    @staticmethod
    def _extract_followup_ops(new_body: str) -> List[str]:
        """
        Yeni CadQuery kodundan sadece "ek operasyon" satırlarını çıkarır.
        Baz şekil tanımı (`result = (cq.Workplane(...).rect(...).extrude(...))`)
        çok satırlı parantezli olabilir; tüm parantez bloğunu atlar ve
        ondan sonra gelen `result = result.edges...` / `result = result.faces...`
        gibi zincir satırlarını döner.
        """
        followups: List[str] = []
        lines = new_body.splitlines()
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            s = line.strip()
            if not s or s.startswith("import"):
                i += 1
                continue
            if s.startswith("result = (cq.Workplane") or s.startswith("result = cq.Workplane"):
                # Parantez balansı tamam olana kadar tüm devam satırlarını yut
                bal = line.count("(") - line.count(")")
                i += 1
                while i < n and bal > 0:
                    bal += lines[i].count("(") - lines[i].count(")")
                    i += 1
                continue
            # Yeni bir result = result.<op>(...) satırı veya devamı
            followups.append(line)
            # Çok satırlı zincir varsa parantez balansını korumak için yut
            bal = line.count("(") - line.count(")")
            i += 1
            while i < n and bal > 0:
                followups.append(lines[i])
                bal += lines[i].count("(") - lines[i].count(")")
                i += 1
        return followups

    def add_step(self, prompt: str, prediction: Dict[str, str]) -> Dict[str, str]:
        """
        Modelin ürettiği yeni adımı state'e ekler ve kümülatif kodu döner.
        İlk adımda direkt prediction'ı baz alır; sonraki adımlarda yeni
        operasyonun gövdesini mevcut koda iliştirir.
        """
        self.history_prompts.append(prompt)
        new_cq = prediction["cadquery"]
        new_vba = prediction["vba"]

        if not self.cadquery_code:
            # İlk adım
            self.cadquery_code = new_cq
            self.vba_code = new_vba
        else:
            # CadQuery: yeni koddan sadece ek operasyon zincirlerini al
            new_body = self._strip_cq_header(new_cq)
            extra_lines = self._extract_followup_ops(new_body)
            if extra_lines:
                if not self.cadquery_code.endswith("\n"):
                    self.cadquery_code += "\n"
                self.cadquery_code += "\n".join(extra_lines) + "\n"

            # VBA: yeni kodun gövdesini eski VBA'nın footer'ından önce ekle
            from data_generator import VBA_FOOTER
            _, new_body_vba, _ = self._strip_vba_wrapper(new_vba)
            self.vba_code = self.vba_code.replace(VBA_FOOTER, new_body_vba + VBA_FOOTER)

        self.last_op = prediction.get("op", "unknown")
        return {"vba": self.vba_code, "cadquery": self.cadquery_code, "op": self.last_op}


def get_model(model_dir: Optional[str] = None):
    """Eğitilmiş model varsa onu, yoksa fallback'i döner."""
    if model_dir and os.path.isdir(model_dir):
        try:
            return FineTunedModel(model_dir)
        except Exception as e:
            print(f"[WARN] Eğitilmiş model yüklenemedi ({e}); fallback aktif.")
    return DeterministicFallbackModel()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--data", default="dataset.jsonl")
    ap.add_argument("--model", default="Salesforce/codet5-small")
    ap.add_argument("--out", default="./cad_model")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--subset", type=int, default=None)
    args = ap.parse_args()
    if args.train:
        fine_tune(args.data, args.model, args.out, args.epochs, subset=args.subset)
    else:
        m = get_model()
        print(json.dumps(m.predict("100x60x10 mm plaka oluştur"),
                         indent=2, ensure_ascii=False))
