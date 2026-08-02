import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import TERRAZA_MINIMA_M2, check_bedrooms, check_terraza


def specs(dormitorios, servicio=None, texto=""):
    d = {"Dormitorios": str(dormitorios), "_texto": texto}
    if servicio is not None:
        d["Dormitorio y baño de servicio"] = servicio
    return d


class TestCuatroOMas:
    def test_cuatro_dormitorios_cumple_sin_mas_requisitos(self):
        assert check_bedrooms(specs(4)) is True

    def test_cinco_dormitorios_cumple(self):
        assert check_bedrooms(specs(5)) is True


class TestTresConHabitacionDeServicio:
    def test_atributo_estructurado_si(self):
        assert check_bedrooms(specs(3, servicio="Sí")) is True

    def test_mencion_en_el_texto(self):
        assert check_bedrooms(specs(3, texto="Amplio depto con pieza de servicio")) is True


class TestTresConEscritorio:
    def test_escritorio_mencionado_en_el_texto(self):
        assert check_bedrooms(specs(3, texto="3 dormitorios más escritorio independiente")) is True

    def test_escritorio_cumple_aunque_no_haya_servicio(self):
        assert check_bedrooms(specs(3, servicio="No", texto="con escritorio")) is True

    def test_sala_de_estudio_cuenta_como_escritorio(self):
        assert check_bedrooms(specs(3, texto="living, comedor y sala de estudio")) is True


class TestTresQueNoCumplen:
    def test_sin_servicio_ni_escritorio_confirmado(self):
        assert check_bedrooms(specs(3, servicio="No", texto="Depto luminoso")) is False

    def test_sin_datos_concluyentes_va_a_revisar(self):
        assert check_bedrooms(specs(3, texto="Depto luminoso")) is None


class TestMenosDeTres:
    def test_dos_dormitorios_no_cumple(self):
        assert check_bedrooms(specs(2, texto="con escritorio y pieza de servicio")) is False


class TestDatoAusente:
    def test_sin_dormitorios_va_a_revisar(self):
        assert check_bedrooms({"_texto": ""}) is None


class TestTerraza:
    """
    Los casos se derivan de TERRAZA_MINIMA_M2 en vez de hardcodear el número,
    para que ajustar el umbral no rompa los tests: lo que se verifica es el
    borde (el mínimo exacto cumple) y los tres estados, no el valor puntual.
    """

    def terraza(self, m2):
        # Se formatea con coma decimal, como lo publica Portal Inmobiliario.
        return {"Superficie de terraza": f"{m2} m²".replace(".", ",")}

    def test_terraza_bien_sobre_el_minimo_cumple(self):
        assert check_terraza(self.terraza(TERRAZA_MINIMA_M2 * 2)) is True

    def test_terraza_igual_al_minimo_cumple(self):
        assert check_terraza(self.terraza(TERRAZA_MINIMA_M2)) is True

    def test_terraza_decimal_sobre_el_minimo_cumple(self):
        assert check_terraza(self.terraza(TERRAZA_MINIMA_M2 + 0.5)) is True

    def test_terraza_decimal_bajo_el_minimo_no_cumple(self):
        assert check_terraza(self.terraza(TERRAZA_MINIMA_M2 - 0.5)) is False

    def test_terraza_mucho_mas_chica_no_cumple(self):
        assert check_terraza({"Superficie de terraza": "1 m²"}) is False

    def test_sin_superficie_declarada_va_a_revisar(self):
        assert check_terraza({}) is None

    def test_superficie_vacia_va_a_revisar(self):
        assert check_terraza({"Superficie de terraza": ""}) is None
