import csv
import os.path
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import time
from requests import Session
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.ie.webdriver import WebDriver

# Permite correr esto tanto como `python src/main.py` como `python -m src.main`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mapa import generar_mapa
from src.propiedades import (
    ESCRITORIO_TEXTO_PATTERN,
    SERVICIO_TEXTO_PATTERN,
    extract_datos,
    load_cache,
    mlc_id,
    parse_m2,
    update_cache,
)

csv_filename = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "already_recommended.csv")
report_filename = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cumplen.csv")
revisar_filename = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "revisar.csv")
base_url = "https://www.portalinmobiliario.com/venta/departamento/_DisplayType_M_PriceRange_320000000CLP-390000000CLP_BEDROOMS_3-*_COVERED*AREA_95m%C2%B2-*_FULL*BATHROOMS_2-*_HAS*LIFT_242085_HAS*TERRACE_242085_MAINTENANCE*FEE_*-350000CLP_PARKING*LOTS_1-*_item*location_lat:-33.43442709417597*-33.423592809404326,lon:-70.60679095245361*-70.58747904754638?polygon_location=lr%60kEhp%7CmL%7DCb%40%3FFc%40%3FkDtA%7BAXkDX%3FFeFF%3FFmAH%3FFaA%3Fi%40_CGmAi%40oBq%40oF_AyCUkD%5DeB%3Fs%40a%40aCO%7BD%5B_Cy%40%7BCa%40qG%3FmAR%7DA%7CA%3Fp%40Y%3Fi%40x%40sD%3Fs%40Ra%40%60C%3FLG%3Fc%40Ti%40lAF%3FHnC%3FbBs%40tAIZOvIGxBz%40tAjAT%60%40L%3F%7E%40tAZP%60AlAb%40jARpC%60A%60Gp%40rHDnBx%40nFD%60GMr%40EfCO%7EASp%40gCzCuAbAyBbAgAHfAc%40"

# Atributos técnicos ("Dormitorios", "Dormitorio y baño de servicio", etc.) que Portal Inmobiliario
# no siempre renderiza en la tabla visible, pero sí incluye en el JSON embebido de la página.
JSON_ATTR_PATTERN = re.compile(r'\{"id":"([^"]+)","text":"([^"]*)"\}')

# Los patrones de habitación de servicio y escritorio viven en src/propiedades.py
# para que el filtro y los datos que alimentan el mapa usen la misma definición.

# Superficie mínima de terraza exigida, en m².
TERRAZA_MINIMA_M2 = 8.0

# Menciones a que la propiedad necesita reforma/remodelación en el título o la descripción.
# Los lookbehind excluyen negaciones directas ("no necesita reforma", "sin necesidad de remodelar").
REFORMA_TEXTO_PATTERNS = [
    re.compile(r'(?<!no )(?<!sin )\b(?:a|para|por)\s+reformar\b', re.IGNORECASE),
    re.compile(r'(?<!no )(?<!sin )\b(?:a|para|por)\s+remodelar\b', re.IGNORECASE),
    re.compile(r'(?<!no )(?<!sin )\b(?:a|para|por)\s+refaccionar\b', re.IGNORECASE),
    re.compile(r'(?<!no )(?<!sin )\bnecesita\w*\s+(?:reforma|remodelaci[oó]n|refacci[oó]n)\w*\b', re.IGNORECASE),
    re.compile(r'(?<!no )(?<!sin )\brequiere\w*\s+(?:reforma|remodelaci[oó]n)\w*\b', re.IGNORECASE),
]


def extract_links(session: Session) -> list[str]:
    response = session.get(base_url)
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.content, 'html.parser')
    tag_elements = soup.find_all("a", class_="poly-component__title")
    links = [tag.get("href") for tag in tag_elements]

    return links


def check_orientation(specs):
    try:
        orientation = specs["Orientación"]
    except:
        return True
    return 'N' in orientation

def check_floor(specs):
    try:
        floor = int(specs["Número de piso de la unidad"])
    except:
        return True
    return floor >= 4 and floor <= 8


def check_bedrooms(specs):
    """
    Devuelve True (cumple), False (no cumple) o None (dato no concluyente,
    requiere revisión manual):

      - 4+ dormitorios: cumple.
      - 3 dormitorios: cumple si hay habitación de servicio O escritorio.
        El servicio se confirma por el atributo estructurado o por mención en
        el título/descripción; el escritorio solo por texto, porque Portal
        Inmobiliario no lo expone como atributo.
      - Menos de 3: no cumple.

    Con 3 dormitorios, si el atributo de servicio dice "No" y tampoco hay
    mención de escritorio, se descarta; si el atributo no viene, queda en
    "revisar" en vez de descartarse.
    """
    try:
        dormitorios = int(specs["Dormitorios"])
    except:
        return None
    if dormitorios >= 4:
        return True
    if dormitorios < 3:
        return False

    texto = specs.get("_texto", "")
    servicio = specs.get("Dormitorio y baño de servicio")
    if servicio == "Sí" or SERVICIO_TEXTO_PATTERN.search(texto):
        return True
    if ESCRITORIO_TEXTO_PATTERN.search(texto):
        return True
    if servicio == "No":
        return False
    return None


def check_terraza(specs):
    """
    Devuelve True (cumple), False (no cumple) o None (dato no concluyente,
    requiere revisión manual): la terraza debe tener al menos
    TERRAZA_MINIMA_M2 m².

    La búsqueda ya filtra por HAS_TERRACE, así que una publicación sin el
    atributo igual tiene terraza, solo que no declara cuánto mide: no alcanza
    para descartarla, se manda a revisar.
    """
    m2 = parse_m2(specs.get("Superficie de terraza"))
    if m2 is None:
        return None
    return m2 >= TERRAZA_MINIMA_M2


def check_reforma(specs):
    """
    Devuelve False si el título/descripción menciona que la propiedad
    necesita reforma/remodelación/refacción (excluyendo negaciones como
    "no necesita reforma"). True en cualquier otro caso.
    """
    texto = specs.get("_texto", "")
    return not any(pattern.search(texto) for pattern in REFORMA_TEXTO_PATTERNS)


def classify_link(driver: WebDriver, link: str) -> str:
    """
    Clasifica un link como "cumple", "no_cumple" o "revisar" (dato no
    concluyente, requiere revisión manual). Solo se descartan los
    "no_cumple" confirmados.

    De paso cachea la ubicación y los datos de la publicación en
    propiedades.csv, que es lo que consume el mapa (src/mapa.py).
    """
    content = navigate_and_extract_content(driver, link)
    specs = extract_specs(content)

    # Se cachea antes de los filtros para que el mapa pueda mostrar también
    # los descartados como contexto del barrio.
    update_cache(extract_datos(content, link))

    if not check_orientation(specs):
        return "no_cumple"
    if not check_floor(specs):
        return "no_cumple"
    # if not check_reforma(specs):
    #     return "no_cumple"

    # Filtros tri-estado: basta un False confirmado para descartar, y si no hay
    # ninguno, cualquier dato no concluyente manda la publicación a revisar.
    resultados = [check_bedrooms(specs), check_terraza(specs)]
    if any(resultado is False for resultado in resultados):
        return "no_cumple"
    if any(resultado is None for resultado in resultados):
        return "revisar"
    return "cumple"


def extract_specs(content: str) -> dict:
    soup = BeautifulSoup(content, 'html.parser')
    tables = soup.find_all("div", class_="ui-vpp-striped-specs")
    specs = {}
    for table in tables:
        rows = table.find_all("table")[0].find_all("tr", class_="andes-table__row")
        for row in rows:
            key = row.find_all("div", class_="andes-table__header__container")[0].text
            value = row.find_all("span", class_="andes-table__column--value")[0].text
            specs[key] = value

    prices = soup.find_all("span", class_="andes-money-amount__fraction")
    if len(prices) == 1:
        specs["Precio"] = prices[0].text.replace('.', '')
        # specs["Gastos comunes"] = prices[1].text.replace('.', '')
    elif len(prices) == 2:
        specs["Precio"] = prices[1].text.replace('.', '')

    try:
        ggcc_div = soup.find("div", id="maintenance_fee_vis")
        ggcc_p = ggcc_div.find("p", class_="ui-pdp-color--GRAY ui-pdp-size--XSMALL ui-pdp-family--REGULAR ui-pdp-maintenance-fee-ltr")
        ggcc_string = ggcc_p.text.split("$ ")[1].replace('.', '')
        specs["Gastos comunes"] = ggcc_string
    except:
        print("Gastos comunes no está en el header")

    # Algunos atributos (ej. "Dormitorio y baño de servicio") no se renderizan en la tabla
    # visible, pero sí están en el JSON embebido de la página. Solo rellenamos los que
    # falten para no pisar los valores ya obtenidos de la tabla.
    for key, value in JSON_ATTR_PATTERN.findall(content):
        specs.setdefault(key, value)

    # Título + descripción, usados como respaldo por check_bedrooms para detectar
    # menciones a un dormitorio/pieza de servicio cuando el atributo no está presente.
    titulo = soup.find("h1")
    descripcion = soup.find("p", class_="ui-pdp-description__content")
    specs["_texto"] = " ".join([
        titulo.text if titulo else "",
        descripcion.text if descripcion else "",
    ])

    return specs


def navigate_and_extract_content(driver: WebDriver, link: str) -> str:
    html_after_click = None

    # Set timeout
    timeout = 5
    driver.implicitly_wait(timeout)

    # Set viewport size
    driver.set_window_size(834, 771)

    # Navigate to URL
    driver.get(link)

    # Wait for page to load
    wait = WebDriverWait(driver, timeout)

    # Try multiple strategies to find and click the button
    selectors = [
        # Try by data-testid attribute
        (By.CSS_SELECTOR, "[data-testid='action-collapsable-target']"),
        # Try by text content
        (By.XPATH, "//*[contains(text(), 'Revisar todas las características')]"),
        (By.XPATH, "//button[contains(., 'Revisar todas')]"),
        # Try by class if it's a button
        (By.XPATH, "//button[contains(@class, 'collapsable')]"),
        # Try finding any clickable element with the text
        (By.LINK_TEXT, "Revisar todas las características"),
    ]

    element = None
    for by, selector in selectors:
        try:
            element = wait.until(EC.element_to_be_clickable((by, selector)))
            break
        except Exception as e:
            print(f"Failed with {selector}: {str(e)[:50]}")
            continue

    if element:
        # Scroll element into view
        driver.execute_script("arguments[0].scrollIntoView(true);", element)
        # Wait a bit for any animations
        import time
        time.sleep(1)
        # Try to click
        try:
            element.click()

        except:
            # If regular click fails, try JavaScript click
            driver.execute_script("arguments[0].click();", element)

        html_after_click = driver.page_source
    else:
        print("Element not found with any selector")
    return html_after_click


def normalize_link(link: str) -> str:
    """
    Remueve el tracking_id del link para poder comparar correctamente.
    Ejemplo: ...?tracking_id=abc123 -> ...
    """
    if '#' in link:
        base_part = link.split('#')[0]
        return base_part
    return link


def open_or_create_csv() -> dict:
    """
    Lee el CSV existente y retorna un diccionario con
    link_normalizado: (link_original, estado, timestamp), donde estado es
    "cumple", "no_cumple" o "revisar".
    """
    already_saved = {}
    if os.path.exists(csv_filename):
        with open(csv_filename, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if len(row) >= 2:
                    link = row[0]
                    estado = row[1]
                    # Compatibilidad con el formato anterior (booleano True/False)
                    if estado.lower() in ('true', 'false'):
                        estado = 'cumple' if estado.lower() == 'true' else 'no_cumple'
                    timestamp = row[2] if len(row) >= 3 else ''
                    link_normalizado = normalize_link(link)
                    # Guardamos con link normalizado como key, pero mantenemos el original
                    already_saved[link_normalizado] = (link, estado, timestamp)

    return already_saved


def save_links(links_dict):
    """
    Guarda todos los links con su estado en el CSV
    links_dict tiene formato: {link_normalizado: (link_original, estado, timestamp)}
    """
    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        for link_normalizado, (link_original, estado, timestamp) in links_dict.items():
            writer.writerow([link_original, estado, timestamp])


REPORTE_COLUMNAS = [
    "precio",
    "precio_m2",
    "base_m2",
    "gastos_comunes",
    "dormitorios",
    "banos",
    "superficie_util",
    "superficie_total",
    "superficie_terraza",
    "piso",
    "orientacion",
    "servicio",
    "escritorio",
    "titulo",
    "lat",
    "lon",
]


def save_filtered_report(links_dict, estado_filtro, filename):
    """
    Escribe un reporte con los links en el estado dado (pasados y nuevos),
    enriquecido con los datos cacheados de cada publicación y ordenado de
    menor a mayor precio por m² (las publicaciones sin ese dato van al final).
    """
    cache = load_cache()
    filas = []
    for link_original, estado, timestamp in links_dict.values():
        if estado != estado_filtro:
            continue
        datos = cache.get(mlc_id(link_original) or "", {})
        filas.append({
            "link": link_original,
            "timestamp": timestamp,
            **{columna: datos.get(columna) for columna in REPORTE_COLUMNAS},
        })

    filas.sort(key=lambda fila: (fila["precio_m2"] is None, fila["precio_m2"] or 0))

    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f, fieldnames=["link", "timestamp"] + REPORTE_COLUMNAS, extrasaction='ignore'
        )
        writer.writeheader()
        writer.writerows(filas)


def save_reports(links_dict):
    save_filtered_report(links_dict, "cumple", report_filename)
    save_filtered_report(links_dict, "revisar", revisar_filename)
    generar_mapa(links_dict)


if __name__ == "__main__":
    # Cargar links ya procesados PRIMERO (antes de iniciar driver)
    # saved_links tiene formato: {link_normalizado: (link_original, estado, timestamp)}
    saved_links = open_or_create_csv()
    print(f"Links ya guardados en CSV: {len(saved_links)}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    })

    # Obtener links de la búsqueda
    print("Extrayendo links de la búsqueda...")
    links = extract_links(session)
    print(f"Links encontrados en búsqueda: {len(links)}")

    # Identificar cuáles son nuevos (comparando versión normalizada)
    links_nuevos = [link for link in links if normalize_link(link) not in saved_links]
    print(f"Links NUEVOS a procesar: {len(links_nuevos)}")

    if len(links_nuevos) == 0:
        print("No hay links nuevos para procesar.")
        save_reports(saved_links)
    else:
        # Solo iniciar driver si hay links nuevos
        driver = webdriver.Chrome()

        nuevos_que_cumplen = []
        nuevos_a_revisar = []

        for i, link in enumerate(links_nuevos, 1):
            print(f"\n[{i}/{len(links_nuevos)}] Analizando: {link}")
            estado = classify_link(driver, link)
            link_normalizado = normalize_link(link)
            # Guardamos con el link original completo (con tracking_id)
            timestamp = datetime.now().isoformat()
            saved_links[link_normalizado] = (link, estado, timestamp)

            if estado == "cumple":
                nuevos_que_cumplen.append(link)
                print(f"✓ CUMPLE REQUISITOS")
            elif estado == "revisar":
                nuevos_a_revisar.append(link)
                print(f"? A REVISAR (dato no concluyente)")
            else:
                print(f"✗ No cumple requisitos")

            time.sleep(0.5)

        driver.close()

        # Guardar todos los links (viejos + nuevos)
        save_links(saved_links)

        # Actualizar los reportes de los que cumplen y los que hay que revisar (pasados + nuevos)
        save_reports(saved_links)

        # Mostrar solo los nuevos que cumplen
        print(f"\n{'=' * 60}")
        print(f"NUEVOS LINKS QUE CUMPLEN REQUISITOS:")
        print(f"{'=' * 60}")
        for link in nuevos_que_cumplen:
            print(link)

        print(f"\n{'=' * 60}")
        print(f"NUEVOS LINKS A REVISAR MANUALMENTE:")
        print(f"{'=' * 60}")
        for link in nuevos_a_revisar:
            print(link)

        # Resumen
        print(f"\n{'=' * 60}")
        print(f"RESUMEN:")
        print(f"Total de links en búsqueda actual: {len(links)}")
        print(f"Links que ya estaban guardados: {len(links) - len(links_nuevos)}")
        print(f"Nuevos links procesados: {len(links_nuevos)}")
        print(f"Nuevos que CUMPLEN requisitos: {len(nuevos_que_cumplen)}")
        print(f"Nuevos a revisar manualmente: {len(nuevos_a_revisar)}")
        print(f"Total acumulado en CSV: {len(saved_links)}")
        print(f"{'=' * 60}")