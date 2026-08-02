"""
Genera mapa.html: un mapa Leaflet con un pin por publicación, coloreado según
su estado (cumple / revisar / no cumple) y con link a la publicación original.

Uso:
    python src/mapa.py              # genera el mapa con lo que ya está cacheado
    python src/mapa.py --backfill   # antes de generar, busca los datos que falten

El --backfill recorre los links de already_recommended.csv que todavía no tienen
coordenadas y las descarga con requests (no necesita Selenium: el pin está en el
HTML inicial). Los resultados quedan en propiedades.csv, así que el costo se paga
una sola vez por publicación.
"""

import json
import os.path
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.propiedades import (
    extract_datos,
    load_cache,
    mlc_id,
    save_cache,
)

mapa_filename = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mapa.html"
)

ESTADOS = {
    "cumple": {"label": "Cumple", "color": "#1a9850"},
    "revisar": {"label": "A revisar", "color": "#e8a33d"},
    "no_cumple": {"label": "No cumple", "color": "#9aa0a6"},
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def fetch_datos(session: requests.Session, link: str) -> dict | None:
    """Descarga una publicación y extrae sus datos. None si la request falla."""
    try:
        response = session.get(link, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"  ✗ Error al descargar: {str(e)[:80]}")
        return None
    return extract_datos(response.text, link)


def backfill(saved_links: dict) -> dict:
    """
    Completa el cache con los links que aún no tienen coordenadas.
    Devuelve el cache actualizado.
    """
    cache = load_cache()
    pendientes = []
    for link_original, _estado, _timestamp in saved_links.values():
        identificador = mlc_id(link_original)
        if not identificador:
            continue
        if cache.get(identificador, {}).get("lat") is None:
            pendientes.append((identificador, link_original))

    if not pendientes:
        print("Backfill: no hay publicaciones pendientes.")
        return cache

    print(f"Backfill: buscando datos de {len(pendientes)} publicaciones...")
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for i, (identificador, link) in enumerate(pendientes, 1):
        print(f"[{i}/{len(pendientes)}] {identificador}")
        datos = fetch_datos(session, link)
        if datos and datos.get("lat") is not None:
            cache[identificador] = datos
            print(f"  ✓ {datos['lat']}, {datos['lon']}")
        elif datos:
            # La publicación cargó pero sin mapa (suele ser un aviso dado de baja).
            cache[identificador] = datos
            print("  ? Sin pin en el mapa")
        time.sleep(0.5)

    save_cache(cache)
    return cache


def build_puntos(saved_links: dict, cache: dict) -> list[dict]:
    """Cruza los estados de already_recommended.csv con los datos cacheados."""
    puntos = []
    for link_original, estado, timestamp in saved_links.values():
        identificador = mlc_id(link_original)
        datos = cache.get(identificador)
        if not datos or datos.get("lat") is None:
            continue
        if estado not in ESTADOS:
            continue
        puntos.append({
            "lat": datos["lat"],
            "lon": datos["lon"],
            "estado": estado,
            "titulo": datos.get("titulo") or identificador,
            "link": link_original,
            "precio": datos.get("precio"),
            "precio_m2": datos.get("precio_m2"),
            "base_m2": datos.get("base_m2") or "",
            "gastos_comunes": datos.get("gastos_comunes"),
            "dormitorios": datos.get("dormitorios") or "",
            "banos": datos.get("banos") or "",
            "piso": datos.get("piso") or "",
            "superficie_util": datos.get("superficie_util") or "",
            "superficie_total": datos.get("superficie_total") or "",
            "superficie_terraza": datos.get("superficie_terraza") or "",
            "orientacion": datos.get("orientacion") or "",
            "servicio": datos.get("servicio") or "",
            "escritorio": datos.get("escritorio") or "",
            "timestamp": (timestamp or "")[:10],
        })

    # Los que cumplen se dibujan al final para que queden encima de los grises.
    orden = {"no_cumple": 0, "revisar": 1, "cumple": 2}
    puntos.sort(key=lambda p: orden[p["estado"]])
    return puntos


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mapa de departamentos</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
  * { box-sizing: border-box; }
  /* Las reglas de abajo fijan `display` en elementos que se ocultan con el atributo
     `hidden`, y una regla del autor le gana a la del user-agent stylesheet. Sin este
     !important, el aviso de "no hay pines" tapa el mapa aunque haya pines. */
  [hidden] { display: none !important; }
  html, body { margin: 0; height: 100%; }
  #mapa { position: absolute; inset: 0; }
  .panel {
    position: absolute; top: 12px; left: 12px; z-index: 1000;
    background: rgba(255,255,255,.96); border-radius: 10px; padding: 12px 14px;
    box-shadow: 0 2px 12px rgba(0,0,0,.18); min-width: 190px;
    font-size: 13px; line-height: 1.5;
  }
  .panel h1 { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
  .panel .meta { color: #5f6368; font-size: 11px; margin: 0 0 10px; }
  .panel label { display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 2px 0; }
  .panel input { margin: 0; cursor: pointer; }
  .panel hr { border: none; border-top: 1px solid #e0e0e0; margin: 10px 0; }
  .panel h2 { margin: 0 0 6px; font-size: 11px; font-weight: 600; text-transform: uppercase;
              letter-spacing: .04em; color: #5f6368; }
  .escala { margin-top: 8px; }
  .escala .barra {
    height: 10px; border-radius: 5px;
    background: linear-gradient(to right, hsl(120,65%,42%), hsl(60,75%,45%), hsl(0,70%,50%));
  }
  .escala .rotulos {
    display: flex; justify-content: space-between; font-size: 10px; color: #5f6368;
    margin-top: 3px; font-variant-numeric: tabular-nums;
  }
  .escala .nota { font-size: 10px; color: #80868b; margin-top: 4px; line-height: 1.35; }
  .dot { width: 12px; height: 12px; border-radius: 50%; border: 2px solid #fff;
         box-shadow: 0 0 0 1px rgba(0,0,0,.25); flex: none; }
  .count { color: #80868b; margin-left: auto; font-variant-numeric: tabular-nums; }
  .vacio {
    position: absolute; inset: 0; display: grid; place-items: center; z-index: 1001;
    background: #f8f9fa; text-align: center; padding: 24px;
  }
  .vacio code { background: #e8eaed; padding: 2px 6px; border-radius: 4px; }
  .popup { font-size: 13px; line-height: 1.5; min-width: 210px; }
  .popup .titulo { font-weight: 600; margin-bottom: 6px; display: block; }
  .popup .precio { font-size: 16px; font-weight: 600; margin-bottom: 2px; }
  .popup .ggcc { color: #5f6368; font-size: 11px; margin-bottom: 6px; }
  .popup .specs { color: #3c4043; margin-bottom: 8px; }
  .popup a { color: #1a73e8; font-weight: 600; text-decoration: none; }
  .popup a:hover { text-decoration: underline; }
  .leaflet-tooltip.precio-tip {
    background: rgba(32,33,36,.88); border: none; color: #fff; font-size: 11px;
    font-weight: 600; padding: 1px 5px; box-shadow: none; border-radius: 4px;
  }
  .leaflet-tooltip.precio-tip::before { display: none; }
</style>
</head>
<body>
<div id="mapa"></div>
<div class="panel" id="panel" hidden>
  <h1>Departamentos</h1>
  <p class="meta" id="meta"></p>
  <h2>Mostrar</h2>
  <div id="filtros"></div>
  <hr>
  <h2>Color</h2>
  <div id="modos"></div>
  <div class="escala" id="escala" hidden>
    <div class="barra"></div>
    <div class="rotulos"><span id="escala-min"></span><span id="escala-max"></span></div>
    <div class="nota" id="escala-nota"></div>
  </div>
</div>
<div class="vacio" id="vacio" hidden>
  <div>
    <p><strong>Todavía no hay pines para mostrar.</strong></p>
    <p>Corré <code>python src/mapa.py --backfill</code> para buscar las coordenadas<br>
       de las publicaciones ya procesadas, o <code>python src/main.py</code> para<br>
       procesar publicaciones nuevas.</p>
  </div>
</div>
<script>
const PUNTOS = __PUNTOS__;
const ESTADOS = __ESTADOS__;

const clp = n => n == null ? null : "$" + n.toLocaleString("es-CL");
const millones = n => n == null ? "" : "$" + Math.round(n / 1e6) + "M";
const uf_m2 = n => n == null ? "" : "$" + (n / 1e6).toFixed(2).replace(".", ",") + "M/m²";

// Rango de la escala de $/m², calculado sobre todos los puntos que tienen el dato
// para que los colores no cambien de significado al prender y apagar filtros.
const CON_M2 = PUNTOS.filter(p => p.precio_m2 != null).map(p => p.precio_m2);
const M2_MIN = CON_M2.length ? Math.min(...CON_M2) : 0;
const M2_MAX = CON_M2.length ? Math.max(...CON_M2) : 0;
const SIN_DATO_COLOR = "#c9ccd1";

// Verde (120°) para el $/m² más bajo, rojo (0°) para el más alto.
function colorPorM2(valor) {
  if (valor == null) return SIN_DATO_COLOR;
  const t = M2_MAX > M2_MIN ? (valor - M2_MIN) / (M2_MAX - M2_MIN) : 0;
  const hue = 120 * (1 - t);
  const sat = 65 + 10 * Math.abs(t - 0.5) * 2;
  return `hsl(${hue.toFixed(0)}, ${sat.toFixed(0)}%, 44%)`;
}

let modoColor = "estado";
const colorDe = p => modoColor === "estado" ? ESTADOS[p.estado].color : colorPorM2(p.precio_m2);

const mapa = L.map("mapa", { scrollWheelZoom: true });
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(mapa);

if (!PUNTOS.length) {
  document.getElementById("vacio").hidden = false;
  mapa.setView([-33.4286, -70.5925], 13);
} else {
  document.getElementById("panel").hidden = false;

  const capas = {};
  for (const estado of Object.keys(ESTADOS)) capas[estado] = L.layerGroup();

  const marcadores = [];

  for (const p of PUNTOS) {
    const specs = [
      p.dormitorios && p.dormitorios + " dorm.",
      p.banos && p.banos + " baños",
      p.superficie_util && p.superficie_util + " útiles",
      p.superficie_total && p.superficie_total + " totales",
      p.superficie_terraza && "terraza " + p.superficie_terraza,
      p.piso && "piso " + p.piso,
      p.orientacion && "orient. " + p.orientacion,
      p.servicio && "servicio",
      p.escritorio && "escritorio"
    ].filter(Boolean).join(" · ");

    const html = `<div class="popup">
        <span class="titulo">${escapar(p.titulo)}</span>
        ${p.precio ? `<div class="precio">${clp(p.precio)}</div>` : ""}
        ${p.precio_m2 ? `<div class="ggcc">${clp(p.precio_m2)} / m² ${escapar(p.base_m2)}</div>` : ""}
        ${p.gastos_comunes ? `<div class="ggcc">GGCC ${clp(p.gastos_comunes)}</div>` : ""}
        ${specs ? `<div class="specs">${escapar(specs)}</div>` : ""}
        <a href="${encodeURI(p.link)}" target="_blank" rel="noopener">Ver publicación →</a>
      </div>`;

    const marcador = L.circleMarker([p.lat, p.lon], {
      radius: 9,
      color: "#fff",
      weight: 2,
      fillColor: colorDe(p),
      fillOpacity: 0.95
    }).bindPopup(html, { maxWidth: 300 });

    marcador.punto = p;
    marcador.bindTooltip("", {
      permanent: true, direction: "top", offset: [0, -8], className: "precio-tip"
    });
    marcadores.push(marcador);
    marcador.addTo(capas[p.estado]);
  }

  function repintar() {
    for (const m of marcadores) {
      const p = m.punto;
      m.setStyle({ fillColor: colorDe(p) });
      const etiqueta = modoColor === "estado" ? millones(p.precio) : uf_m2(p.precio_m2);
      m.setTooltipContent(etiqueta || "s/d");
    }
    document.getElementById("escala").hidden = modoColor !== "precio_m2";
  }

  // Los pines apilados en el mismo edificio se separan levemente al hacer zoom;
  // por defecto mostramos cumple y revisar, y dejamos los descartados apagados.
  const encendidos = new Set(["cumple", "revisar"]);
  for (const estado of encendidos) capas[estado].addTo(mapa);

  const filtros = document.getElementById("filtros");
  for (const [estado, cfg] of Object.entries(ESTADOS)) {
    const total = PUNTOS.filter(p => p.estado === estado).length;
    const label = document.createElement("label");
    label.innerHTML = `
      <input type="checkbox" ${encendidos.has(estado) ? "checked" : ""}>
      <span class="dot" style="background:${cfg.color}"></span>
      <span>${cfg.label}</span><span class="count">${total}</span>`;
    label.querySelector("input").addEventListener("change", e => {
      if (e.target.checked) capas[estado].addTo(mapa);
      else mapa.removeLayer(capas[estado]);
    });
    filtros.appendChild(label);
  }

  const modos = [
    ["estado", "Por estado"],
    ["precio_m2", "Por $/m²"]
  ];
  const contenedorModos = document.getElementById("modos");
  for (const [valor, etiqueta] of modos) {
    const label = document.createElement("label");
    label.innerHTML = `
      <input type="radio" name="modo" value="${valor}" ${valor === modoColor ? "checked" : ""}>
      <span>${etiqueta}</span>`;
    label.querySelector("input").addEventListener("change", e => {
      if (!e.target.checked) return;
      modoColor = e.target.value;
      repintar();
    });
    contenedorModos.appendChild(label);
  }

  document.getElementById("escala-min").textContent = uf_m2(M2_MIN);
  document.getElementById("escala-max").textContent = uf_m2(M2_MAX);
  const sinDato = PUNTOS.length - CON_M2.length;
  document.getElementById("escala-nota").textContent =
    "Calculado sobre superficie útil (o total si no se declara)." +
    (sinDato ? ` ${sinDato} sin dato, en gris.` : "");

  document.getElementById("meta").textContent =
    PUNTOS.length + " publicaciones con ubicación";

  repintar();

  const visibles = PUNTOS.filter(p => encendidos.has(p.estado));
  const paraEncuadrar = visibles.length ? visibles : PUNTOS;
  mapa.fitBounds(paraEncuadrar.map(p => [p.lat, p.lon]), { padding: [60, 60], maxZoom: 16 });
}

function escapar(texto) {
  const div = document.createElement("div");
  div.textContent = texto == null ? "" : texto;
  return div.innerHTML;
}
</script>
</body>
</html>
"""


def render(puntos: list[dict]) -> str:
    return (
        HTML_TEMPLATE
        .replace("__PUNTOS__", json.dumps(puntos, ensure_ascii=False))
        .replace("__ESTADOS__", json.dumps(ESTADOS, ensure_ascii=False))
    )


def generar_mapa(saved_links: dict, con_backfill: bool = False) -> str:
    cache = backfill(saved_links) if con_backfill else load_cache()
    puntos = build_puntos(saved_links, cache)

    with open(mapa_filename, 'w', encoding='utf-8') as f:
        f.write(render(puntos))

    sin_ubicacion = len(saved_links) - len(puntos)
    print(f"\nMapa generado: {mapa_filename}")
    print(f"  Pines: {len(puntos)}")
    for estado, cfg in ESTADOS.items():
        total = len([p for p in puntos if p["estado"] == estado])
        print(f"    {cfg['label']}: {total}")
    if sin_ubicacion > 0:
        print(f"  Sin ubicación cacheada: {sin_ubicacion} (corré --backfill para buscarlas)")

    return mapa_filename


if __name__ == "__main__":
    from src.main import open_or_create_csv

    generar_mapa(open_or_create_csv(), con_backfill="--backfill" in sys.argv)
