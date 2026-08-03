import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.filtros import (
    PISO_MAXIMO,
    PISO_MINIMO,
    TERRAZA_MINIMA_M2,
    check_bedrooms,
    check_floor,
    check_orientation,
    check_terraza,
    evaluar,
    specs_desde_cache,
)


def specs(dormitorios, servicio=None, texto=""):
    d = {"Dormitorios": str(dormitorios), "_texto": texto}
    if servicio is not None:
        d["Dormitorio y baño de servicio"] = servicio
    return d


class TestCuatroOMas:
    def test_cuatro_dormitorios_cumple_sin_mas_requisitos(self):
        assert check_bedrooms(specs(4)).cumple is True

    def test_cinco_dormitorios_cumple(self):
        assert check_bedrooms(specs(5)).cumple is True


class TestTresConHabitacionDeServicio:
    def test_atributo_estructurado_si(self):
        assert check_bedrooms(specs(3, servicio="Sí")).cumple is True

    def test_mencion_en_el_texto(self):
        assert check_bedrooms(specs(3, texto="Amplio depto con pieza de servicio")).cumple is True


class TestTresConEscritorio:
    def test_escritorio_mencionado_en_el_texto(self):
        assert check_bedrooms(specs(3, texto="3 dormitorios más escritorio independiente")).cumple is True

    def test_escritorio_cumple_aunque_no_haya_servicio(self):
        assert check_bedrooms(specs(3, servicio="No", texto="con escritorio")).cumple is True

    def test_sala_de_estudio_cuenta_como_escritorio(self):
        assert check_bedrooms(specs(3, texto="living, comedor y sala de estudio")).cumple is True


class TestTresQueNoCumplen:
    def test_sin_servicio_ni_escritorio_confirmado(self):
        resultado = check_bedrooms(specs(3, servicio="No", texto="Depto luminoso"))
        assert resultado.cumple is False
        assert "servicio" in resultado.motivo and "escritorio" in resultado.motivo

    def test_sin_datos_concluyentes_va_a_revisar(self):
        resultado = check_bedrooms(specs(3, texto="Depto luminoso"))
        assert resultado.cumple is None
        assert resultado.motivo


class TestMenosDeTres:
    def test_dos_dormitorios_no_cumple(self):
        resultado = check_bedrooms(specs(2, texto="con escritorio y pieza de servicio"))
        assert resultado.cumple is False
        assert "2 dormitorios" in resultado.motivo


class TestDatoAusente:
    def test_sin_dormitorios_va_a_revisar(self):
        resultado = check_bedrooms({"_texto": ""})
        assert resultado.cumple is None
        assert resultado.motivo


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
        assert check_terraza(self.terraza(TERRAZA_MINIMA_M2 * 2)).cumple is True

    def test_terraza_igual_al_minimo_cumple(self):
        assert check_terraza(self.terraza(TERRAZA_MINIMA_M2)).cumple is True

    def test_terraza_decimal_sobre_el_minimo_cumple(self):
        assert check_terraza(self.terraza(TERRAZA_MINIMA_M2 + 0.5)).cumple is True

    def test_terraza_decimal_bajo_el_minimo_no_cumple(self):
        assert check_terraza(self.terraza(TERRAZA_MINIMA_M2 - 0.5)).cumple is False

    def test_terraza_mucho_mas_chica_no_cumple(self):
        resultado = check_terraza({"Superficie de terraza": "1 m²"})
        assert resultado.cumple is False
        assert "terraza 1 m²" in resultado.motivo

    def test_sin_superficie_declarada_va_a_revisar(self):
        resultado = check_terraza({})
        assert resultado.cumple is None
        assert "terraza" in resultado.motivo

    def test_superficie_vacia_va_a_revisar(self):
        assert check_terraza({"Superficie de terraza": ""}).cumple is None


class TestOrientacion:
    """
    El criterio es que el depto no sea oscuro: el norte sirve en cualquier
    combinación y el oriente solo si no viene con sur. Sur y poniente solos
    no alcanzan.
    """

    def orientacion(self, valor):
        return {"Orientación": valor}

    def test_norte_cumple(self):
        assert check_orientation(self.orientacion("N")).cumple is True

    def test_oriente_cumple(self):
        assert check_orientation(self.orientacion("O")).cumple is True

    def test_norte_poniente_cumple(self):
        assert check_orientation(self.orientacion("NP")).cumple is True

    def test_sur_oriente_no_cumple(self):
        resultado = check_orientation(self.orientacion("SO"))
        assert resultado.cumple is False
        assert "SO" in resultado.motivo

    def test_todas_las_orientaciones_cumple_por_el_norte(self):
        assert check_orientation(self.orientacion("NOSP")).cumple is True

    def test_sur_no_cumple(self):
        assert check_orientation(self.orientacion("S")).cumple is False

    def test_sur_poniente_no_cumple(self):
        assert check_orientation(self.orientacion("SP")).cumple is False

    def test_poniente_no_cumple(self):
        assert check_orientation(self.orientacion("P")).cumple is False

    def test_sin_orientacion_no_descarta(self):
        assert check_orientation({}).cumple is True

    def test_orientacion_vacia_no_descarta(self):
        assert check_orientation(self.orientacion("")).cumple is True


class TestPiso:
    def piso(self, valor):
        return {"Número de piso de la unidad": str(valor)}

    def test_piso_en_rango_cumple(self):
        assert check_floor(self.piso(PISO_MINIMO)).cumple is True
        assert check_floor(self.piso(PISO_MAXIMO)).cumple is True

    def test_piso_bajo_el_minimo_no_cumple(self):
        resultado = check_floor(self.piso(PISO_MINIMO - 1))
        assert resultado.cumple is False
        assert f"piso {PISO_MINIMO - 1}" in resultado.motivo

    def test_piso_sobre_el_maximo_no_cumple(self):
        assert check_floor(self.piso(PISO_MAXIMO + 1)).cumple is False

    def test_sin_piso_no_descarta(self):
        assert check_floor({}).cumple is True

    def test_piso_no_numerico_no_descarta(self):
        assert check_floor(self.piso("Zócalo")).cumple is True


def specs_completas(**overrides):
    """Specs de una publicación que cumple todo, para variar un filtro a la vez."""
    base = {
        "Dormitorios": "4",
        "Orientación": "N",
        "Número de piso de la unidad": str(PISO_MINIMO),
        "Superficie de terraza": f"{TERRAZA_MINIMA_M2:g} m²",
        "_texto": "",
    }
    return {**base, **overrides}


class TestEvaluar:
    def test_cumple_sin_motivo(self):
        assert evaluar(specs_completas()) == ("cumple", "")

    def test_un_filtro_que_descarta_da_no_cumple_con_su_motivo(self):
        estado, motivo = evaluar(specs_completas(**{"Orientación": "S"}))
        assert estado == "no_cumple"
        assert motivo == "orientación S"

    def test_dato_no_concluyente_va_a_revisar(self):
        estado, motivo = evaluar(specs_completas(**{"Superficie de terraza": ""}))
        assert estado == "revisar"
        assert "terraza" in motivo

    def test_varios_motivos_se_listan_juntos(self):
        estado, motivo = evaluar(
            specs_completas(**{"Orientación": "S", "Número de piso de la unidad": "20"})
        )
        assert estado == "no_cumple"
        assert "orientación S" in motivo
        assert "piso 20" in motivo

    def test_un_descarte_confirmado_le_gana_a_un_dato_dudoso(self):
        # La orientación descarta y la terraza no está declarada: se descarta,
        # no tiene sentido mandar a revisar algo que ya está fuera.
        estado, _motivo = evaluar(
            specs_completas(**{"Orientación": "S", "Superficie de terraza": ""})
        )
        assert estado == "no_cumple"


class TestSpecsDesdeCache:
    """
    El motivo se recalcula desde propiedades.csv para el popup del mapa, así que
    una fila cacheada tiene que dar el mismo resultado que las specs en vivo.
    """

    def test_una_fila_que_cumple(self):
        datos = {
            "dormitorios": "4",
            "orientacion": "NP",
            "piso": "5",
            "superficie_terraza": "15 m²",
            "servicio": "",
            "escritorio": "",
        }
        assert evaluar(specs_desde_cache(datos)) == ("cumple", "")

    def test_una_fila_que_no_cumple(self):
        datos = {
            "dormitorios": "3",
            "orientacion": "SP",
            "piso": "2",
            "superficie_terraza": "2 m²",
            "servicio": "No",
            "escritorio": "",
        }
        estado, motivo = evaluar(specs_desde_cache(datos))
        assert estado == "no_cumple"
        assert "orientación SP" in motivo
        assert "piso 2" in motivo
        assert "terraza 2 m²" in motivo

    def test_el_escritorio_cacheado_reemplaza_al_texto(self):
        # En vivo el escritorio se detecta por texto; en el cache ya viene como
        # columna, porque el texto del aviso no se guarda.
        datos = {"dormitorios": "3", "servicio": "No", "escritorio": "Sí"}
        assert check_bedrooms(specs_desde_cache(datos)).cumple is True

    def test_el_servicio_cacheado_reemplaza_al_texto(self):
        datos = {"dormitorios": "3", "servicio": "Sí", "escritorio": ""}
        assert check_bedrooms(specs_desde_cache(datos)).cumple is True

    def test_fila_vacia_va_a_revisar(self):
        estado, _motivo = evaluar(specs_desde_cache({}))
        assert estado == "revisar"
