import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import descartar as mod_descartar
from src.mapa import build_puntos, generar_mapa, motivo_de, render

PUNTO = {
    "lat": -33.42, "lon": -70.59, "mlc_id": "MLC-1", "estado": "cumple", "motivo": "",
    "titulo": "Depto", "link": "https://x/MLC-1_JM",
    "precio": 350000000, "precio_m2": 3000000, "base_m2": "útil", "gastos_comunes": 250000,
    "dormitorios": "4", "banos": "3", "piso": "5", "superficie_util": "100 m²",
    "superficie_total": "120 m²", "superficie_terraza": "10 m²", "orientacion": "N",
    "servicio": "Sí", "escritorio": "", "timestamp": "2026-08-02",
}


def elementos_con_hidden(html):
    """[(id, clase)] de los elementos que se ocultan con el atributo hidden."""
    return [
        (re.search(r'id="([^"]+)"', tag).group(1) if 'id="' in tag else "",
         re.search(r'class="([^"]+)"', tag).group(1) if 'class="' in tag else "")
        for tag in re.findall(r'<div[^>]*\bhidden\b[^>]*>', html)
    ]


def declara_display(html, selector):
    """True si el CSS del autor le fija un `display` a ese selector."""
    bloque = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', html)
    return bool(bloque and re.search(r'\bdisplay\s*:', bloque.group(1)))


class TestOcultarConHidden:
    """
    El atributo `hidden` sirve porque el user-agent stylesheet trae
    `[hidden] { display: none }`, pero cualquier regla de la hoja del autor que
    fije `display` en el mismo elemento le gana en la cascada y lo deja visible.
    Cuando eso pasó, el div del mensaje "no hay pines" tapó el mapa entero.
    """

    def test_hay_elementos_que_dependen_de_hidden(self):
        assert elementos_con_hidden(render([PUNTO])), "el test perdió su objeto de prueba"

    def test_el_css_protege_el_atributo_hidden(self):
        html = render([PUNTO])
        regla = re.search(r'\[hidden\]\s*\{([^}]*)\}', html)
        assert regla, "falta la regla [hidden] que garantiza que ocultar funcione"
        assert re.search(r'display\s*:\s*none\s*!important', regla.group(1)), \
            "la regla [hidden] necesita !important para ganarle a las reglas con display"

    def test_ninguna_clase_con_display_queda_sin_proteger(self):
        html = render([PUNTO])
        for elemento_id, clases in elementos_con_hidden(html):
            for selector in [f"#{elemento_id}"] + [f".{c}" for c in clases.split() if c]:
                if declara_display(html, selector):
                    assert re.search(r'\[hidden\]\s*\{[^}]*!important', html), (
                        f"{selector} fija display y se oculta con hidden, "
                        "pero no hay una regla [hidden] con !important"
                    )


class TestMensajeVacio:
    def test_el_mensaje_esta_oculto_cuando_hay_puntos(self):
        html = render([PUNTO])
        tag = re.search(r'<div class="vacio"[^>]*>', html).group(0)
        assert "hidden" in tag

    def test_los_puntos_se_embeben(self):
        html = render([PUNTO])
        assert "__PUNTOS__" not in html
        assert '"precio_m2": 3000000' in html or '"precio_m2":3000000' in html


def datos_cacheados(**overrides):
    base = {
        "mlc_id": "MLC-1", "lat": -33.42, "lon": -70.59, "titulo": "Depto",
        "precio": 350000000, "precio_m2": 3000000, "base_m2": "útil",
        "gastos_comunes": 250000, "dormitorios": "4", "banos": "3", "piso": "5",
        "superficie_util": "100 m²", "superficie_total": "120 m²",
        "superficie_terraza": "10 m²", "orientacion": "N", "servicio": "", "escritorio": "",
    }
    return {**base, **overrides}


class TestMotivo:
    def test_el_que_cumple_no_lleva_motivo(self):
        assert motivo_de("cumple", datos_cacheados()) == ""

    def test_el_descartado_explica_por_que(self):
        motivo = motivo_de("no_cumple", datos_cacheados(orientacion="SP"))
        assert "orientación SP" in motivo

    def test_el_dudoso_explica_que_falta(self):
        motivo = motivo_de("revisar", datos_cacheados(superficie_terraza=""))
        assert "terraza" in motivo

    def test_el_popup_muestra_el_motivo(self):
        html = render([{**PUNTO, "estado": "no_cumple", "motivo": "orientación SP"}])
        assert '"motivo": "orientación SP"' in html or '"motivo":"orientación SP"' in html
        assert 'class="motivo"' in html

    def test_build_puntos_lo_calcula_desde_el_cache(self):
        saved = {"https://x/MLC-1_JM": ("https://x/MLC-1_JM", "no_cumple", "2026-08-02")}
        cache = {"MLC-1": datos_cacheados(piso="20")}
        puntos = build_puntos(saved, cache)
        assert "piso 20" in puntos[0]["motivo"]


class TestBotonDescartar:
    """
    El botón solo puede funcionar si el mapa lo sirve src/servidor.py: abierto
    como archivo no hay nadie que escriba el CSV. El HTML es el mismo en los dos
    casos y el botón se decide en el navegador según el protocolo.
    """

    def test_el_boton_esta_en_el_popup(self):
        html = render([PUNTO])
        assert 'class="descartar"' in html
        assert "data-mlc=" in html

    def test_el_boton_depende_de_estar_en_un_servidor(self):
        html = render([PUNTO])
        assert "EN_SERVIDOR" in html
        assert 'location.protocol === "http:"' in html

    def test_el_id_viaja_en_los_puntos(self):
        html = render([PUNTO])
        assert '"mlc_id": "MLC-1"' in html or '"mlc_id":"MLC-1"' in html

    def test_build_puntos_incluye_el_id(self):
        saved = {"https://x/MLC-1_JM": ("https://x/MLC-1_JM", "cumple", "2026-08-02")}
        puntos = build_puntos(saved, {"MLC-1": datos_cacheados()})
        assert puntos[0]["mlc_id"] == "MLC-1"

    def test_el_popup_pide_descartar_y_deshacer(self):
        html = render([PUNTO])
        assert '"/descartar"' in html
        assert '"/quitar"' in html


class TestDescartadosFueraDelMapa:
    def test_el_mapa_no_dibuja_los_descartados(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod_descartar, "descartados_filename", str(tmp_path / "d.csv"))
        monkeypatch.setattr("src.mapa.mapa_filename", str(tmp_path / "mapa.html"))
        monkeypatch.setattr("src.mapa.load_cache", lambda: {"MLC-1": datos_cacheados()})
        saved = {"https://x/MLC-1_JM": ("https://x/MLC-1_JM", "cumple", "2026-08-02")}

        generar_mapa(saved)
        assert '"titulo": "Depto"' in (tmp_path / "mapa.html").read_text(encoding="utf-8")

        mod_descartar.descartar("MLC-1", "edificio feo")
        generar_mapa(saved)
        html = (tmp_path / "mapa.html").read_text(encoding="utf-8")
        assert "const PUNTOS = [];" in html
