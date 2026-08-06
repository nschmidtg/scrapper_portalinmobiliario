import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.propiedades import extract_geo, extract_datos, mlc_id, parse_m2, precio_m2


FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "publicacion.html")


@pytest.fixture(scope="module")
def html():
    # El fixture es una publicación real y no se versiona: trae los datos de
    # contacto del corredor. En un clon nuevo estos tests se saltean; para
    # tenerlos, guardar una publicación como tests/fixtures/publicacion.html.
    if not os.path.exists(FIXTURE):
        pytest.skip("falta tests/fixtures/publicacion.html (no se versiona)")
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


class TestExtractGeo:
    def test_extrae_el_pin_del_staticmap(self, html):
        assert extract_geo(html) == (-33.4286091, -70.5924954)

    def test_devuelve_none_si_no_hay_mapa(self):
        assert extract_geo("<html><body>sin mapa</body></html>") == (None, None)

    def test_tolera_entidades_html_escapadas(self):
        # El HTML de Portal Inmobiliario a veces escapa los & como &amp;
        fragmento = (
            '<img src="https://maps.googleapis.com/maps/api/staticmap?key=X'
            '&amp;center=-33.4286091%2C-70.5924954&amp;zoom=16">'
        )
        assert extract_geo(fragmento) == (-33.4286091, -70.5924954)

    def test_ignora_coordenadas_fuera_de_chile(self):
        fragmento = 'staticmap?center=48.8584%2C2.2945&zoom=16'
        assert extract_geo(fragmento) == (None, None)


class TestParseM2:
    def test_parsea_metros_cuadrados(self):
        assert parse_m2("124 m²") == 124.0

    def test_parsea_decimales_con_coma(self):
        assert parse_m2("104,5 m²") == 104.5

    def test_devuelve_none_si_no_hay_numero(self):
        assert parse_m2("") is None
        assert parse_m2(None) is None


class TestPrecioM2:
    def test_usa_superficie_util_cuando_esta(self):
        # 367.603.126 / 104 = 3.534.645
        assert precio_m2(367603126, "104 m²", "124 m²") == (3534645, "útil")

    def test_cae_a_superficie_total_si_no_hay_util(self):
        assert precio_m2(367603126, None, "124 m²") == (2964541, "total")

    def test_devuelve_none_sin_precio_o_sin_superficie(self):
        assert precio_m2(None, "104 m²", "124 m²") == (None, "")
        assert precio_m2(367603126, None, None) == (None, "")

    def test_ignora_superficie_cero(self):
        assert precio_m2(367603126, "0 m²", None) == (None, "")


class TestExtractDatos:
    def test_extrae_los_campos_del_popup(self, html):
        datos = extract_datos(html)
        assert datos["lat"] == -33.4286091
        assert datos["lon"] == -70.5924954
        assert datos["titulo"] == "Oportunidad. Exclusivo. Bien Mantenido. Barrio Residencial"
        assert datos["precio"] == 367603126
        assert datos["gastos_comunes"] == 300000
        assert datos["dormitorios"] == "4"
        assert datos["banos"] == "3"
        assert datos["piso"] == "4"
        assert datos["superficie_total"] == "124 m²"
        assert datos["orientacion"] == "NP"

    def test_calcula_el_precio_por_m2(self, html):
        datos = extract_datos(html)
        assert datos["precio_m2"] == 3534645
        assert datos["base_m2"] == "útil"

    def test_no_explota_con_html_vacio(self):
        datos = extract_datos("<html></html>")
        assert datos["lat"] is None
        assert datos["precio"] is None
        assert datos["titulo"] == ""


class TestMlcId:
    def test_extrae_el_id_de_la_publicacion(self):
        link = "https://portalinmobiliario.com/MLC-2037610125-oportunidad-_JM#polycard_client=search"
        assert mlc_id(link) == "MLC-2037610125"

    def test_devuelve_none_si_el_link_no_tiene_id(self):
        assert mlc_id("https://portalinmobiliario.com/venta/departamento/") is None
