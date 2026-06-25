# -*- coding: utf-8 -*-
"""
visualizer.py
=============
CadQuery + (opsiyonel) jupyter-cadquery / three.js + STL fallback ile
Colab hücresinde 3D önizleme üretir.

Kullanım:
    from visualizer import render
    html, stl_bytes = render(cadquery_code)
"""

from __future__ import annotations
import io
import os
import tempfile
import textwrap
import traceback
from typing import Optional, Tuple


def execute_cadquery(code: str):
    """
    CadQuery kodunu güvenli bir namespace içinde çalıştırır ve `result`
    değişkenini döner. Hata olursa RuntimeError fırlatır.
    """
    try:
        import cadquery as cq  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "cadquery yüklü değil. Colab'de: !pip install cadquery"
        ) from e

    ns = {}
    try:
        exec(code, ns)
    except Exception as e:
        raise RuntimeError(
            f"CadQuery kodu çalıştırılamadı: {e}\n\n{traceback.format_exc()}"
        )
    if "result" not in ns:
        raise RuntimeError("Üretilen kodda `result` değişkeni bulunamadı.")
    return ns["result"]


def export_stl(result, path: Optional[str] = None) -> str:
    """Modeli STL olarak dosyaya yazar ve yolunu döner."""
    import cadquery as cq
    if path is None:
        path = tempfile.NamedTemporaryFile(suffix=".stl", delete=False).name
    cq.exporters.export(result, path)
    return path


def export_step(result, path: Optional[str] = None) -> str:
    """Modeli STEP formatında yazar."""
    import cadquery as cq
    if path is None:
        path = tempfile.NamedTemporaryFile(suffix=".step", delete=False).name
    cq.exporters.export(result, path)
    return path


# --------------------------------------------------------------------------- #
#  HTML / Three.js önizleme                                                   #
# --------------------------------------------------------------------------- #

THREEJS_TEMPLATE = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  body { margin: 0; background: #1a1d24; color: #ccc;
         font-family: -apple-system, sans-serif; }
  #c { width: 100%; height: 100vh; display: block; }
  #info { position: absolute; top: 8px; left: 12px; font-size: 12px; opacity:.7 }
</style></head>
<body>
<div id="info">Sürükle: döndür | Tekerlek: zoom | Sağ tık: pan</div>
<canvas id="c"></canvas>
<script type="importmap">
{ "imports": {
  "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
  "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
}}
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader }    from 'three/addons/loaders/STLLoader.js';

const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({canvas, antialias:true});
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1d24);

const camera = new THREE.PerspectiveCamera(45, innerWidth/innerHeight, 0.1, 5000);
camera.position.set(150, 120, 200);

const ctrl = new OrbitControls(camera, canvas);
ctrl.enableDamping = true;

scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const d1 = new THREE.DirectionalLight(0xffffff, 0.9); d1.position.set(1,1,1); scene.add(d1);
const d2 = new THREE.DirectionalLight(0x88aaff, 0.4); d2.position.set(-1,-1,-1); scene.add(d2);

const grid = new THREE.GridHelper(400, 40, 0x444, 0x2a2a2a);
scene.add(grid);
scene.add(new THREE.AxesHelper(60));

const stlData = atob("__STL_B64__");
const buf = new ArrayBuffer(stlData.length);
const view = new Uint8Array(buf);
for (let i=0;i<stlData.length;i++) view[i] = stlData.charCodeAt(i);
const geom = new STLLoader().parse(buf);
geom.computeVertexNormals();
geom.center();
const mat  = new THREE.MeshStandardMaterial({color:0xffa64d, metalness:.3, roughness:.45});
const mesh = new THREE.Mesh(geom, mat);
scene.add(mesh);

geom.computeBoundingSphere();
const r = geom.boundingSphere.radius || 100;
camera.position.set(r*1.6, r*1.2, r*2);
ctrl.target.set(0,0,0);

addEventListener('resize', ()=> {
  renderer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth/innerHeight; camera.updateProjectionMatrix();
});
function loop(){ ctrl.update(); renderer.render(scene,camera); requestAnimationFrame(loop); }
loop();
</script></body></html>
"""


def render(code: str) -> Tuple[str, bytes, Optional[str]]:
    """
    CadQuery kodundan three.js tabanlı interaktif HTML + STL bayt verisi üretir.

    Returns
    -------
    (html, stl_bytes, error_message_or_None)
    """
    import base64
    try:
        result = execute_cadquery(code)
    except Exception as e:
        return _error_html(str(e)), b"", str(e)

    stl_path = export_stl(result)
    with open(stl_path, "rb") as f:
        stl_bytes = f.read()
    try:
        os.remove(stl_path)
    except OSError:
        pass

    b64 = base64.b64encode(stl_bytes).decode("ascii")
    html = THREEJS_TEMPLATE.replace("__STL_B64__", b64)
    return html, stl_bytes, None


def _error_html(msg: str) -> str:
    safe = (msg.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))
    return textwrap.dedent(f"""
    <html><body style='background:#2a1a1a;color:#ffb;font-family:monospace;
        padding:20px'>
        <h3>CadQuery yürütme hatası</h3>
        <pre style='white-space:pre-wrap'>{safe}</pre>
    </body></html>
    """)


# --------------------------------------------------------------------------- #
#  Colab notebook helper (opsiyonel)                                          #
# --------------------------------------------------------------------------- #

def show_in_colab(code: str, height: int = 520):
    """Colab hücresinde IFrame olarak gösterir."""
    from IPython.display import HTML, display
    html, _, err = render(code)
    if err:
        print(f"[ERR] {err}")
    display(HTML(f'<iframe srcdoc="{_escape(html)}" '
                 f'style="width:100%;height:{height}px;border:0"></iframe>'))


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;")


if __name__ == "__main__":
    demo = (
        "import cadquery as cq\n"
        'result = cq.Workplane("XY").rect(60, 40).extrude(15)'
        '.edges("|Z").fillet(4)\n'
    )
    html, stl, err = render(demo)
    print("Hata:", err, "| STL bytes:", len(stl))
    with open("preview.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("preview.html yazıldı.")
