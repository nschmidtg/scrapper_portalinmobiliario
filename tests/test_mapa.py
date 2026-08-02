import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mapa import render

PUNTO = {
    "lat": -33.42, "lon": -70.59, "estado": "cumple", "titulo": "Depto", "link": "https://x/MLC-1_JM",
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
