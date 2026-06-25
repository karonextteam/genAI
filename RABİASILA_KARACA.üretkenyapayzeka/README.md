# NL → SolidWorks VBA + Canlı 3D (Colab)

Doğal dilden hem **SolidWorks VBA makrosu** hem de **CadQuery Python kodu** üreten,
Colab'de canlı 3D önizleme veren hibrit AI + CAD sistemidir. **SolidWorks lokal
makineye kurulu olmasına gerek yoktur** — VBA çıktısı teslim/ödev için, 3D render
ise CadQuery üzerinden yapılır.

## İçerik

| Dosya | Görev |
|---|---|
| `data_generator.py` | 50.000 örneklik `{NL → VBA, CadQuery}` veri seti üretici |
| `ai_model_setup.py` | CodeT5/DeepSeek fine-tune pipeline + `ConversationState` (context-aware) + Deterministic fallback |
| `visualizer.py` | CadQuery → STL → Three.js iframe (Colab içi 3D) |
| `export_report.py` | `.swp/.txt` indirme + Accuracy / Millimetric Consistency / Code Validity metrikleri |
| `app.py` | Gradio arayüzü (sol: komut, sağ: 3D, alt: VBA + indir) |
| `requirements.txt` | Colab uyumlu bağımlılıklar |
| `colab_quickstart.ipynb` | Tek tıkla Colab'de kurulum + çalıştırma |

## Hızlı başlangıç (Colab)

```python
!git clone <repo_url> uretken && cd uretken && pip install -r requirements.txt
!python data_generator.py -n 50000           # veri setini üret
# Opsiyonel — fine-tune (T4 GPU önerilir):
!python ai_model_setup.py --train --subset 5000 --epochs 1
# Web UI:
!python app.py    # share=True olduğu için public URL verir
```

## Mimari

```
┌───────────────────────────┐      ┌─────────────────────────┐
│ data_generator.py (50k)   │ ───► │ ai_model_setup.py       │
└───────────────────────────┘      │  ├─ FineTunedModel      │
                                   │  ├─ DeterministicFallback│
                                   │  └─ ConversationState   │
                                   └────────────┬────────────┘
                                                │ predict(prompt)
                              ┌─────────────────┴───────────────┐
                              ▼                                 ▼
                  ┌────────────────────┐            ┌────────────────────┐
                  │ visualizer.py      │            │ export_report.py   │
                  │ CadQuery → STL →   │            │  .swp + Accuracy + │
                  │ Three.js iframe    │            │  Millimetric Cons. │
                  └─────────┬──────────┘            └──────────┬─────────┘
                            │                                  │
                            └────────── app.py (Gradio) ──────┘
```

## Notlar

- **`pywin32`** sadece SolidWorks yüklü Windows ortamında, opsiyonel olarak
  kullanılır. Colab Linux'ta yüklenmez. Bu nedenle `requirements.txt` içinde
  yorum satırına alınmıştır.
- **`State Management`** `ai_model_setup.ConversationState` üzerinden çalışır.
  Arayüzde "Mevcut parça üzerine ekle" kutusu işaretliyken yeni komut, mevcut
  CadQuery `result` değişkeninin üzerine eklenir (incremental modeling).
- **Akademik Metrikler**:
  - *Op Accuracy*: tahmin edilen operasyon etiketi ile beklenenin eşleşme oranı.
  - *Millimetric Consistency*: NL prompt'taki sayısal değerlerin VBA + CadQuery
    çıktılarında doğru korunma oranı (mm ↔ m dönüşümü dahil).
  - *Code Validity*: CadQuery kodunun gerçek bir `result` üretebilme oranı.
