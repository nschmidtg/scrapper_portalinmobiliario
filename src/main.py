import csv
import os.path
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

csv_filename = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "already_recommended.csv")
base_url = "https://www.portalinmobiliario.com/venta/departamento/_DisplayType_M_PriceRange_330000000CLP-420000000CLP_BEDROOMS_3-*_COVERED*AREA_110m%C2%B2-*_FULL*BATHROOMS_2-*_HAS*LIFT_242085_MAINTENANCE*FEE_*-350000CLP_PARKING*LOTS_1-*_item*location_lat:-33.43787952750852*-33.41621046762059,lon:-70.60850690490723*-70.56988309509278?polygon_location=%60xakEzl%7CmLp%40_%60%40y%40oJqDgQeDsZoMy%60%40iC_YqByFiIkLgGmEyDeAiIXaZvI%7DRdT%7DE%7CLiIbi%40i%40hR%7E%40l%5BlApNxBlIFzR%7EBfNjBnBrj%40Q%60TqC%60GeBlL%7BGrWPrF_FUlA"


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


def is_link_suitable(driver: WebDriver, link: str) -> bool:
    content = navigate_and_extract_content(driver, link)

    specs = extract_specs(content)
    return (check_orientation(specs)
            and check_floor(specs))


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
    Lee el CSV existente y retorna un diccionario con link_normalizado: (link_original, cumple_requisitos, timestamp)
    """
    already_saved = {}
    if os.path.exists(csv_filename):
        with open(csv_filename, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if len(row) >= 2:
                    link = row[0]
                    cumple = row[1].lower() == 'true'
                    timestamp = row[2] if len(row) >= 3 else ''
                    link_normalizado = normalize_link(link)
                    # Guardamos con link normalizado como key, pero mantenemos el original
                    already_saved[link_normalizado] = (link, cumple, timestamp)

    return already_saved


def save_links(links_dict):
    """
    Guarda todos los links con su estado en el CSV
    links_dict tiene formato: {link_normalizado: (link_original, cumple, timestamp)}
    """
    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        for link_normalizado, (link_original, cumple, timestamp) in links_dict.items():
            writer.writerow([link_original, cumple, timestamp])


if __name__ == "__main__":
    # Cargar links ya procesados PRIMERO (antes de iniciar driver)
    # saved_links tiene formato: {link_normalizado: (link_original, cumple)}
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
    else:
        # Solo iniciar driver si hay links nuevos
        driver = webdriver.Chrome()

        nuevos_que_cumplen = []

        for i, link in enumerate(links_nuevos, 1):
            print(f"\n[{i}/{len(links_nuevos)}] Analizando: {link}")
            cumple = is_link_suitable(driver, link)
            link_normalizado = normalize_link(link)
            # Guardamos con el link original completo (con tracking_id)
            timestamp = datetime.now().isoformat()
            saved_links[link_normalizado] = (link, cumple, timestamp)

            if cumple:
                nuevos_que_cumplen.append(link)
                print(f"✓ CUMPLE REQUISITOS")
            else:
                print(f"✗ No cumple requisitos")

            time.sleep(0.5)

        driver.close()

        # Guardar todos los links (viejos + nuevos)
        save_links(saved_links)

        # Mostrar solo los nuevos que cumplen
        print(f"\n{'=' * 60}")
        print(f"NUEVOS LINKS QUE CUMPLEN REQUISITOS:")
        print(f"{'=' * 60}")
        for link in nuevos_que_cumplen:
            print(link)

        # Resumen
        print(f"\n{'=' * 60}")
        print(f"RESUMEN:")
        print(f"Total de links en búsqueda actual: {len(links)}")
        print(f"Links que ya estaban guardados: {len(links) - len(links_nuevos)}")
        print(f"Nuevos links procesados: {len(links_nuevos)}")
        print(f"Nuevos que CUMPLEN requisitos: {len(nuevos_que_cumplen)}")
        print(f"Total acumulado en CSV: {len(saved_links)}")
        print(f"{'=' * 60}")