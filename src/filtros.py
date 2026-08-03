"""
Los filtros que deciden si una publicación cumple, y el motivo cuando no.

Viven en su propio módulo porque los usan dos lados: src/main.py al clasificar
una publicación recién scrapeada, y src/mapa.py para mostrar el motivo en el
popup, recalculándolo desde propiedades.csv sin volver a bajar la página.

Cada filtro devuelve un Resultado con tres estados posibles:

    cumple=True   la publicación pasa el filtro
    cumple=False  se descarta, y `motivo` dice por qué
    cumple=None   el dato no es concluyente: va a "revisar" en vez de perderse

La regla general es no descartar por falta de datos. Un aviso que no declara la
orientación puede igual dar al norte, así que se revisa a mano.
"""

import re
from typing import NamedTuple

from src.propiedades import ESCRITORIO_TEXTO_PATTERN, SERVICIO_TEXTO_PATTERN, parse_m2

CUMPLE = "cumple"
NO_CUMPLE = "no_cumple"
REVISAR = "revisar"

# Superficie mínima de terraza exigida, en m².
TERRAZA_MINIMA_M2 = 8.0

# Rango de pisos aceptado: abajo se pierde vista y luz, arriba incomoda el
# ascensor y sube la exposición al viento.
PISO_MINIMO = 4
PISO_MAXIMO = 8

# Portal Inmobiliario publica la orientación como una combinación de letras
# ("N", "O", "NP", "SO", "NOSP"), donde P es poniente y O oriente.
ORIENTACION_NORTE = "N"
ORIENTACION_ORIENTE = "O"
ORIENTACION_SUR = "S"

DORMITORIOS_SIN_CONDICIONES = 4
DORMITORIOS_MINIMOS = 3


class Resultado(NamedTuple):
    cumple: bool | None
    motivo: str = ""


def _fmt(valor: float) -> str:
    """8.0 -> '8', 3.5 -> '3,5' (coma decimal, como en las publicaciones)."""
    return f"{valor:g}".replace(".", ",")


def _servicio(specs) -> str:
    """
    "Sí", "No" o "" (sin dato). El atributo estructurado manda; si no está, se
    busca la mención en el texto del aviso. `servicio` es la columna equivalente
    de propiedades.csv, que ya trae esa resolución hecha.
    """
    valor = specs.get("Dormitorio y baño de servicio") or specs.get("servicio")
    if valor in ("Sí", "No"):
        return valor
    return "Sí" if SERVICIO_TEXTO_PATTERN.search(specs.get("_texto", "")) else ""


def _escritorio(specs) -> bool:
    """
    Portal Inmobiliario no expone el escritorio como atributo, así que la única
    señal es el texto del aviso (o la columna ya derivada del cache).
    """
    if specs.get("escritorio") == "Sí":
        return True
    return bool(ESCRITORIO_TEXTO_PATTERN.search(specs.get("_texto", "")))


def check_orientation(specs) -> Resultado:
    """
    El criterio es que el departamento no sea oscuro:

      - Norte: siempre cumple, en cualquier combinación ("N", "NP", "NOSP").
      - Oriente: cumple solo si no viene combinado con sur, porque un
        sur-oriente ("SO") recibe muy poco sol.
      - Sur y poniente solos: no cumplen.

    Si la publicación no declara orientación, no se descarta.
    """
    orientacion = specs.get("Orientación")
    if not orientacion:
        return Resultado(True)
    if ORIENTACION_NORTE in orientacion:
        return Resultado(True)
    if ORIENTACION_ORIENTE in orientacion and ORIENTACION_SUR not in orientacion:
        return Resultado(True)
    return Resultado(False, f"orientación {orientacion}")


def check_floor(specs) -> Resultado:
    """
    El piso tiene que estar entre PISO_MINIMO y PISO_MAXIMO. Si no viene el
    dato, o viene algo que no es un número ("Zócalo"), no se descarta.
    """
    try:
        piso = int(specs["Número de piso de la unidad"])
    except (KeyError, TypeError, ValueError):
        return Resultado(True)
    if PISO_MINIMO <= piso <= PISO_MAXIMO:
        return Resultado(True)
    return Resultado(False, f"piso {piso} (fuera de {PISO_MINIMO}-{PISO_MAXIMO})")


def check_bedrooms(specs) -> Resultado:
    """
      - 4+ dormitorios: cumple.
      - 3 dormitorios: cumple si hay habitación de servicio O escritorio.
      - Menos de 3: no cumple.

    Con 3 dormitorios, si el atributo de servicio dice "No" y tampoco hay
    mención de escritorio, se descarta; si el atributo no viene, queda en
    "revisar" en vez de descartarse.
    """
    try:
        dormitorios = int(specs["Dormitorios"])
    except (KeyError, TypeError, ValueError):
        return Resultado(None, "no declara dormitorios")
    if dormitorios >= DORMITORIOS_SIN_CONDICIONES:
        return Resultado(True)
    if dormitorios < DORMITORIOS_MINIMOS:
        return Resultado(False, f"{dormitorios} dormitorios")

    servicio = _servicio(specs)
    if servicio == "Sí" or _escritorio(specs):
        return Resultado(True)
    if servicio == "No":
        return Resultado(False, f"{dormitorios} dorm. sin servicio ni escritorio")
    return Resultado(None, f"{dormitorios} dorm.: servicio y escritorio sin confirmar")


def check_terraza(specs) -> Resultado:
    """
    La terraza tiene que tener al menos TERRAZA_MINIMA_M2 m².

    La búsqueda ya filtra por HAS_TERRACE, así que una publicación sin el
    atributo igual tiene terraza, solo que no declara cuánto mide: no alcanza
    para descartarla, se manda a revisar.
    """
    m2 = parse_m2(specs.get("Superficie de terraza"))
    if m2 is None:
        return Resultado(None, "no declara superficie de terraza")
    if m2 >= TERRAZA_MINIMA_M2:
        return Resultado(True)
    return Resultado(False, f"terraza {_fmt(m2)} m² (mínimo {_fmt(TERRAZA_MINIMA_M2)})")


# Menciones a que la propiedad necesita reforma/remodelación en el título o la descripción.
# Los lookbehind excluyen negaciones directas ("no necesita reforma", "sin necesidad de remodelar").
REFORMA_TEXTO_PATTERNS = [
    re.compile(r'(?<!no )(?<!sin )\b(?:a|para|por)\s+reformar\b', re.IGNORECASE),
    re.compile(r'(?<!no )(?<!sin )\b(?:a|para|por)\s+remodelar\b', re.IGNORECASE),
    re.compile(r'(?<!no )(?<!sin )\b(?:a|para|por)\s+refaccionar\b', re.IGNORECASE),
    re.compile(r'(?<!no )(?<!sin )\bnecesita\w*\s+(?:reforma|remodelaci[oó]n|refacci[oó]n)\w*\b', re.IGNORECASE),
    re.compile(r'(?<!no )(?<!sin )\brequiere\w*\s+(?:reforma|remodelaci[oó]n)\w*\b', re.IGNORECASE),
]


def check_reforma(specs) -> Resultado:
    """
    Descarta si el título/descripción menciona que la propiedad necesita
    reforma/remodelación/refacción (excluyendo negaciones como "no necesita
    reforma").

    Está fuera de FILTROS: depende del texto del aviso, que es ruidoso y no se
    cachea. Para activarlo, agregarlo a la tupla de abajo.
    """
    texto = specs.get("_texto", "")
    if any(pattern.search(texto) for pattern in REFORMA_TEXTO_PATTERNS):
        return Resultado(False, "menciona que necesita reforma")
    return Resultado(True)


FILTROS = (check_orientation, check_floor, check_bedrooms, check_terraza)


def evaluar(specs) -> tuple[str, str]:
    """
    Corre todos los filtros y devuelve (estado, motivo).

    Un solo descarte confirmado alcanza para "no_cumple", y le gana a cualquier
    dato dudoso: no tiene sentido revisar a mano algo que ya está fuera. Si no
    hay descartes pero sí datos no concluyentes, va a "revisar". El motivo junta
    todos los que aplican, para no tener que arreglar un filtro y descubrir que
    faltaba otro.
    """
    resultados = [filtro(specs) for filtro in FILTROS]

    descartes = [r.motivo for r in resultados if r.cumple is False]
    if descartes:
        return (NO_CUMPLE, "; ".join(descartes))

    dudas = [r.motivo for r in resultados if r.cumple is None]
    if dudas:
        return (REVISAR, "; ".join(dudas))

    return (CUMPLE, "")


def specs_desde_cache(datos: dict) -> dict:
    """
    Traduce una fila de propiedades.csv al dict que esperan los filtros, para
    poder recalcular el motivo sin volver a scrapear la publicación.

    El texto del aviso no se cachea, pero sí las dos señales que se derivan de
    él (servicio y escritorio), así que los filtros las leen de esas columnas.
    """
    return {
        "Dormitorios": datos.get("dormitorios") or "",
        "Orientación": datos.get("orientacion") or "",
        "Número de piso de la unidad": datos.get("piso") or "",
        "Superficie de terraza": datos.get("superficie_terraza") or "",
        "servicio": datos.get("servicio") or "",
        "escritorio": datos.get("escritorio") or "",
    }
