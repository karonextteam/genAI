# -*- coding: utf-8 -*-
"""
app.py
======
Gradio tabanlı profesyonel arayüz:
    - Sol panel : doğal dil komut girişi + state geçmişi
    - Sağ panel : canlı 3D önizleme (CadQuery -> Three.js iframe)
    - Altta    : üretilen VBA kodu + indirme butonu
    - Sekme    : metrik raporu

Çalıştırma (Colab):
    !python app.py
veya:
    from app import build; build().launch(share=True)
"""

from __future__ import annotations
import os
import json
import tempfile
from typing import Tuple

import gradio as gr

from ai_model_setup import get_model, ConversationState
from visualizer import render
from export_report import save_vba, evaluate

MODEL_DIR = os.environ.get("CAD_MODEL_DIR", "./cad_model")
DATA_PATH = os.environ.get("CAD_DATA_PATH", "dataset.jsonl")

_model = get_model(MODEL_DIR)
_state = ConversationState()


# --------------------------------------------------------------------------- #
#  Callbacks                                                                  #
# --------------------------------------------------------------------------- #

def on_generate(prompt: str, incremental: bool):
    """Kullanıcı 'Üret' butonuna bastığında çalışır."""
    if not prompt.strip():
        return ("", "", "<p style='color:#fa6'>Lütfen bir komut girin.</p>",
                gr.update(visible=False), _state_history())
    pred = _model.predict(prompt)
    if incremental:
        merged = _state.add_step(prompt, pred)
        vba_code = merged["vba"]
        cq_code = merged["cadquery"]
    else:
        _state.reset()
        _state.add_step(prompt, pred)
        vba_code = pred["vba"]
        cq_code = pred["cadquery"]

    html, stl_bytes, err = render(cq_code)
    iframe = (f'<iframe srcdoc="{_html_escape(html)}" '
              f'style="width:100%;height:520px;border:0;border-radius:12px"></iframe>')
    if err:
        iframe = f"<pre style='color:#f88;white-space:pre-wrap'>{err}</pre>" + iframe

    # VBA dosyasını .swp olarak temp'e kaydet
    swp_path = save_vba(vba_code, ext="swp")
    return (vba_code, cq_code, iframe, gr.update(value=swp_path, visible=True),
            _state_history())


def on_reset():
    _state.reset()
    return ("", "", "<p style='color:#888'>Yeni oturum başlatıldı.</p>",
            gr.update(visible=False), _state_history())


def on_eval(n: int, run_validity: bool):
    if not os.path.exists(DATA_PATH):
        return ("Veri seti bulunamadı: çalıştır `python data_generator.py -n 50000`",
                None)
    rep = evaluate(_model, DATA_PATH, sample_size=int(n),
                   check_validity=run_validity)
    return rep.pretty(), json.dumps(rep.as_dict(), indent=2, ensure_ascii=False)


def _state_history() -> str:
    if not _state.history_prompts:
        return "_(boş)_"
    return "\n".join(f"{i+1}. {p}" for i, p in enumerate(_state.history_prompts))


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace('"', "&quot;")
             .replace("<", "&lt;").replace(">", "&gt;"))


# --------------------------------------------------------------------------- #
#  UI                                                                         #
# --------------------------------------------------------------------------- #

CSS = """
.gradio-container { font-family: 'Inter', -apple-system, sans-serif; }
#title { text-align:center; margin-bottom: 4px; }
#subtitle { text-align:center; color:#888; margin-top:0 }
.panel { border-radius: 14px !important; }
"""

EXAMPLES = [
    ["100x60x10 mm bir plaka oluştur", False],
    ["XY düzleminde yarıçapı 30 mm olan daire oluştur ve 20 mm yüksekliğe çıkar", False],
    ["80x80x15 mm blok oluştur, üst yüzeyine 8 mm yarıçaplı 10 mm derinliğinde delik aç", False],
    ["Yarıçapı 60 mm, kalınlığı 8 mm disk oluştur ve PCD 45 mm üzerinde 6 adet 4 mm yarıçaplı deliği dairesel dizilim ile aç", False],
    ["Dikey kenarlara 5 mm fillet uygula", True],
]


def build():
    with gr.Blocks(css=CSS, title="NL → VBA + 3D CAD",
                   theme=gr.themes.Soft(primary_hue="orange")) as demo:
        gr.Markdown("# 🛠️ NL → SolidWorks VBA + Canlı 3D Önizleme",
                    elem_id="title")
        gr.Markdown("Doğal dil ile tasarla → SolidWorks VBA kodunu indir, "
                    "3D modeli Colab'de canlı izle.", elem_id="subtitle")

        with gr.Row():
            # Sol panel
            with gr.Column(scale=1):
                prompt = gr.Textbox(
                    label="Komut",
                    placeholder="Örn: 100x60x10 mm plaka oluştur ve dikey "
                                "kenarlara 5 mm fillet uygula",
                    lines=4,
                )
                incr = gr.Checkbox(
                    label="Mevcut parça üzerine ekle (Incremental / Context)",
                    value=False,
                )
                with gr.Row():
                    btn = gr.Button("🚀 Üret", variant="primary")
                    btn_reset = gr.Button("♻️ Sıfırla")
                gr.Markdown("**Geçmiş adımlar**")
                history_md = gr.Markdown("_(boş)_")
                gr.Examples(EXAMPLES, inputs=[prompt, incr])

            # Sağ panel
            with gr.Column(scale=2):
                viewer = gr.HTML(
                    "<div style='height:520px;display:flex;align-items:center;"
                    "justify-content:center;background:#1a1d24;color:#666;"
                    "border-radius:12px'>3D önizleme burada görünecek</div>"
                )
                with gr.Accordion("Üretilen Kodlar", open=False):
                    with gr.Tabs():
                        with gr.Tab("SolidWorks VBA"):
                            vba_out = gr.Code(label="VBA")
                        with gr.Tab("CadQuery (Python)"):
                            cq_out = gr.Code(language="python", label="CadQuery")
                vba_file = gr.File(label="📥 VBA dosyasını indir (.swp)",
                                   visible=False)

        with gr.Accordion("📊 Akademik Metrikler", open=False):
            with gr.Row():
                eval_n = gr.Slider(20, 1000, value=100, step=10,
                                   label="Örnek sayısı")
                eval_validity = gr.Checkbox(label="CadQuery yürütme testi",
                                            value=True)
            eval_btn = gr.Button("Metrikleri Hesapla")
            eval_text = gr.Textbox(label="Rapor", lines=10)
            eval_json = gr.Code(language="json", label="JSON")

        btn.click(on_generate, [prompt, incr],
                  [vba_out, cq_out, viewer, vba_file, history_md])
        btn_reset.click(on_reset, None,
                        [vba_out, cq_out, viewer, vba_file, history_md])
        eval_btn.click(on_eval, [eval_n, eval_validity],
                       [eval_text, eval_json])

    return demo


if __name__ == "__main__":
    demo = build()
    demo.launch(share=True, server_name="0.0.0.0")
