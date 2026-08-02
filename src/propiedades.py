"""
Extracción y cacheo de los datos de una publicación que alimentan el mapa:
el pin (lat/lon), el título, el precio y las specs que sirven para decidir
a simple vista si vale la pena abrir el link.

El pin no está en un atributo del HTML sino en la URL de la imagen estática
de Google Maps que Portal Inmobiliario embebe en la sección "Ubicación":
    .../staticmap?...&center=-33.4286091%2C-70.5924954&zoom=16&...
Ese `center` es la coordenada que el sitio usa para dibujar el mapa, así que
es el pin. (El "latitude"/"longitude" del JSON embebido es el centro de Chile,
no la propiedad — no sirve.)
"""

import csv
import html as html_module
import os.path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

cache_filename = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "propiedades.csv"
)

# `center=<lat>,<lon>` dentro de la URL del staticmap. La coma suele venir
# percent-encoded (%2C) y los & escapados como &amp;, así que desescapamos antes.
STATICMAP_CENTER_PATTERN = re.compile(
    r'staticmap[^"\'<>\s]*?[?&]center=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)'
)

MLC_ID_PATTERN = re.compile(r'(MLC-\d+)')

# Caja generosa alrededor de Chile continental, para descartar coordenadas de
# mapas que no son de la propiedad (avisos, mapas de ayuda, etc.).
CHILE_LAT_RANGE = (-56.0, -17.0)
CHILE_LON_RANGE = (-76.0, -66.0)

CAMPOS = [
    "mlc_id",
    "link",
    "lat",
    "lon",
    "titulo",
    "precio",
    "precio_m2",
    "base_m2",
    "gastos_comunes",
    "dormitorios",
    "banos",
    "piso",
    "superficie_total",
    "superficie_util",
    "superficie_terraza",
    "orientacion",
    "servicio",
    "escritorio",
]

M2_PATTERN = re.compile(r'(\d+(?:[.,]\d+)?)')

# Menciones de dormitorio/pieza/cuarto "de servicio" en el título o la descripción,
# como respaldo cuando el atributo estructurado no está disponible.
SERVICIO_TEXTO_PATTERN = re.compile(
    r'(dormitorio|pieza|cuarto|habitaci[oó]n)\w*\s+(y\s+ba[ñn]o\s+)?de\s+servicio',
    re.IGNORECASE,
)

# Portal Inmobiliario no tiene un atributo estructurado para "escritorio", así que
# la única señal es el texto. "sala de estudio" se acepta como equivalente; se evita
# "estudio" suelto porque un "departamento estudio" es justamente lo contrario.
ESCRITORIO_TEXTO_PATTERN = re.compile(
    r'\bescritorios?\b|\bsala\s+de\s+estudio\b',
    re.IGNORECASE,
)


def mlc_id(link: str) -> str | None:
    """Identificador estable de la publicación, usado como key del cache."""
    match = MLC_ID_PATTERN.search(link)
    return match.group(1) if match else None


def extract_geo(content: str) -> tuple[float | None, float | None]:
    """Devuelve (lat, lon) del pin del mapa, o (None, None) si no está."""
    if not content:
        return (None, None)

    texto = unquote(html_module.unescape(content))
    for lat_str, lon_str in STATICMAP_CENTER_PATTERN.findall(texto):
        lat, lon = float(lat_str), float(lon_str)
        if (
            CHILE_LAT_RANGE[0] <= lat <= CHILE_LAT_RANGE[1]
            and CHILE_LON_RANGE[0] <= lon <= CHILE_LON_RANGE[1]
        ):
            return (lat, lon)

    return (None, None)


def parse_m2(texto: str | None) -> float | None:
    """'124 m²' -> 124.0. None si no hay un número reconocible."""
    match = M2_PATTERN.search(texto or '')
    return float(match.group(1).replace(',', '.')) if match else None


def precio_m2(
    precio: int | None, superficie_util: str | None, superficie_total: str | None
) -> tuple[int | None, str]:
    """
    Precio por m² y sobre qué superficie se calculó.

    Se prefiere la superficie útil porque es la que se filtra en la búsqueda y
    no infla el metraje con terrazas; si la publicación no la declara se cae a
    la total. El popup del mapa muestra cuál se usó, porque un $/m² "útil" y
    otro "total" no son directamente comparables.
    """
    if not precio:
        return (None, "")

    for superficie, base in ((superficie_util, "útil"), (superficie_total, "total")):
        m2 = parse_m2(superficie)
        if m2:
            return (round(precio / m2), base)

    return (None, "")


def _parse_monto(texto: str) -> int | None:
    solo_digitos = re.sub(r'[^\d]', '', texto or '')
    return int(solo_digitos) if solo_digitos else None


def _extract_precio(soup) -> int | None:
    """
    El precio de la propiedad es el monto más grande de la página: los otros
    `andes-money-amount__fraction` son UF, gastos comunes o precios de avisos.
    """
    montos = [
        _parse_monto(span.text)
        for span in soup.find_all("span", class_="andes-money-amount__fraction")
    ]
    montos = [m for m in montos if m]
    return max(montos) if montos else None


def _extract_gastos_comunes(soup) -> int | None:
    div = soup.find("div", id="maintenance_fee_vis")
    if not div:
        return None
    match = re.search(r'\$\s*([\d.,]+)', div.text)
    return _parse_monto(match.group(1)) if match else None


def _extract_tabla_specs(soup) -> dict:
    specs = {}
    for table in soup.find_all("div", class_="ui-vpp-striped-specs"):
        for row in table.find_all("tr", class_="andes-table__row"):
            key = row.find("div", class_="andes-table__header__container")
            value = row.find("span", class_="andes-table__column--value")
            if key and value:
                specs[key.text.strip()] = value.text.strip()
    return specs


def extract_datos(content: str, link: str = "") -> dict:
    """
    Extrae del HTML de una publicación todo lo que el mapa necesita mostrar.
    Los campos ausentes quedan en None (o "" para el título) en vez de fallar:
    un pin sin precio sigue siendo útil.
    """
    soup = BeautifulSoup(content or "", 'html.parser')
    specs = _extract_tabla_specs(soup)
    lat, lon = extract_geo(content)
    titulo = soup.find("h1")
    descripcion = soup.find("p", class_="ui-pdp-description__content")
    texto = " ".join([
        titulo.text if titulo else "",
        descripcion.text if descripcion else "",
    ])

    superficie_util = specs.get("Superficie útil")
    superficie_total = specs.get("Superficie total")
    precio = _extract_precio(soup)
    valor_m2, base_m2 = precio_m2(precio, superficie_util, superficie_total)

    # El atributo estructurado manda; el texto es el respaldo.
    servicio = specs.get("Dormitorio y baño de servicio")
    if servicio not in ("Sí", "No"):
        servicio = "Sí" if SERVICIO_TEXTO_PATTERN.search(texto) else ""

    return {
        "mlc_id": mlc_id(link) or "",
        "link": link,
        "lat": lat,
        "lon": lon,
        "titulo": titulo.text.strip() if titulo else "",
        "precio": precio,
        "precio_m2": valor_m2,
        "base_m2": base_m2,
        "gastos_comunes": _extract_gastos_comunes(soup),
        "dormitorios": specs.get("Dormitorios"),
        "banos": specs.get("Baños"),
        "piso": specs.get("Número de piso de la unidad"),
        "superficie_total": superficie_total,
        "superficie_util": superficie_util,
        "superficie_terraza": specs.get("Superficie de terraza"),
        "orientacion": specs.get("Orientación"),
        "servicio": servicio,
        "escritorio": "Sí" if ESCRITORIO_TEXTO_PATTERN.search(texto) else "",
    }


def load_cache() -> dict:
    """Lee propiedades.csv y devuelve {mlc_id: datos}."""
    cache = {}
    if not os.path.exists(cache_filename):
        return cache

    with open(cache_filename, 'r', newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if not row.get("mlc_id"):
                continue
            for campo in ("lat", "lon"):
                row[campo] = float(row[campo]) if row.get(campo) else None
            for campo in ("precio", "precio_m2", "gastos_comunes"):
                row[campo] = int(row[campo]) if row.get(campo) else None
            cache[row["mlc_id"]] = row

    return cache


def save_cache(cache: dict) -> None:
    with open(cache_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction='ignore')
        writer.writeheader()
        for datos in cache.values():
            writer.writerow({campo: datos.get(campo) for campo in CAMPOS})


def update_cache(datos: dict) -> None:
    """Agrega o actualiza una propiedad en el cache, sin perder el resto."""
    if not datos.get("mlc_id"):
        return
    cache = load_cache()
    cache[datos["mlc_id"]] = datos
    save_cache(cache)
