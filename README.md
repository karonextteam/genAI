# 📌 GEN-DRAFT: Text-to-Parametric 3D CAD & SolidWorks VBA Generation Motor

### 🚀 Proje Özeti
**GEN-DRAFT**, doğal dil komutlarını doğrudan mühendislik standartlarında ölçülebilir, parametrik 3D modelleme verilerine ve yürütülebilir **SolidWorks VBA (.swp)** makro kodlarına dönüştüren yenilikçi bir üretken tasarım (Generative Design) motorudur. Geleneksel yapay zeka modellerinin piksel tabanlı görsel çıktılarının aksine, imalata ve endüstriyel manipülasyona uygun dinamik katı geometri üretimi gerçekleştirir.

### 🎯 Problem ve Hedef
* **Problem:** Teknik çizim süreçlerinin yüksek uzmanlık gerektirmesi, CAD yazılımları için VBA makro yazımının ek programlama bilgisi istemesi ve mevcut generatif yapay zekaların mühendislik standartlarında ölçülebilir katı model üretememesi.
* **Hedef:** Doğal dilden çalışan otomatik makro ve CAD kodu üretimi sağlayarak teknik tasarımı demokratikleştirmek ve üretim maliyetleri ile süreçlerini optimize etmek.

---

### ⚙️ Teknik Mimari ve Uçtan Uca İş Hattı (Pipeline)
Sistem, kullanıcının verdiği doğal dil komutunu alarak saniyeler içinde SolidWorks makrosuna ve eş zamanlı 3D önizlemeye dönüştürür:
1. **Doğal Dil Komut Girişi**
2. **Tokenizer + Encode:** Verinin modele uygun hale getirilmesi, padding ve truncation süreçleri.
3. **Fine-tuned CodeT5:** Salesforce tabanlı `CodeT5-small` mimarisi üzerinde Seq2Seq (Sequence-to-Sequence) yaklaşımı ve AdamW optimizasyonu ile eğitilmiş çekirdek motor.
4. **JSON Çözücü:** Çıktının eş zamanlı olarak `{vba, cadquery}` formatlarına ayrıştırılması.
5. **CadQuery Yürütme & STL Mesh üretimi**.
6. **3D Önizleme & İndirme:** Three.js iframe mimarisi (visualizer.py) ile Colab üzerinde canlı 3D gösterim ve üretilen `.swp` dosyasının teslimi.

---

### 🧠 Bağlamsal Modelleme & Durum Yönetimi (State Management)
Sistem, tasarımların karmaşıklaşmasını sağlayan güçlü bir hafıza yönetim katmanına sahiptir:
* **Context Awareness & Incremental Pipeline:** Kullanıcının geçmiş komutlarını unutmadan tasarımı adım adım (birikimli) inşa eder.
* **ConversationState Sınıfı:** Üretilen CadQuery kodlarını hafızada bir "durum" (state) olarak saklayarak baz şekli atlar ve yalnızca yeni gelen zincir operasyonları birikimli koda iliştirir (Örn: Plaka oluşturma -> Fillet ekleme -> Chamfer ekleme).
* **Deterministic Fallback:** Beklenmedik durumlarda rule-based (kural tabanlı) yedek mekanizmayı devreye sokarak sistem kararlılığını korur.

---

### 📊 Algoritmik Veri Seti Operasyon Dağılımı
Hazır veri seti kullanmak yerine, problemin doğasına uygun **50.000 benzersiz sentetik örneklem (NL → VBA / CadQuery)** algoritmik olarak sıfırdan kurgulanıp üretilmiştir. Veri seti içerisinde şu kritik mühendislik operasyonları dengeli bir şekilde dağıtılmıştır:
* Extrude (%14.3) | Revolve (%14.3) | Cut-Extrude (%14.3)
* Fillet (%14.3) | Chamfer (%14.3)
* Linear Pattern (%14.3) | Circular Pattern (%14.3)

---

### 📈 Performans Analizi ve Başarı Metrikleri
Modelin eğitimi sırasında `Final Train Loss = 0.127` ve `Eval Loss = 0.020` seviyelerine ulaşılmıştır. Yapılan randomize testler sonucunda şu akademik başarılar elde edilmiştir:
* **Operasyon Doğruluğu (Op-Accuracy):** **%92.00** semantik kararlılık oranı.
* **Milimetrik Tutarlılık (Millimetric Consistency):** Parametrelerin tam uyumu için **%84.47** başarı.
* **Operasyon Bazında Doğruluk:** Extrude, Cut-Extrude, Fillet, Chamfer, Revolve ve Circular Pattern operasyonlarının her birinde tekil komut doğruluğu **%100** olarak ölçülmüştür (Hedeflenen %90 barajı başarıyla aşılmıştır).

### 🛠️ Kullanılan Teknolojiler
* **Yapay Zeka:** CodeT5-small (Salesforce), Hugging Face Transformers, Tokenizers
* **CAD & Modelleme:** SolidWorks VBA API, CadQuery (Python)
* **Arayüz & Görselleştirme:** Gradio UI (app.py), Three.js iframe (visualizer.py)
