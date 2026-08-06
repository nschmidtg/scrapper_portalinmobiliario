"""
Un mismo departamento aparece varias veces en la búsqueda: el corredor republica
el aviso con otro MLC-id cada tanto (para volver arriba en el listado, o al bajar
el precio). Para el scraper son publicaciones distintas; para quien busca depto es
una sola propiedad, y verla ocho veces solo ensucia los reportes y el mapa —
además los ocho pines caen en la misma coordenada y se tapan entre sí, así que el
contador del panel no coincidía con los pines visibles.

Acá se juntan esas republicaciones y se deja una sola vigente. Las tapadas no se
pierden: siguen en already_recommended.csv (así no se vuelven a evaluar) y el
popup del mapa dice cuántas hay detrás del pin.

El criterio es conservador a propósito: solo se agrupan publicaciones que
coinciden en coordenada, dormitorios, baños, superficie y piso. Se prefiere dejar
pasar un duplicado (falso negativo, molesto) antes que fusionar dos deptos
distintos del mismo edificio (falso positivo, que borraría del mapa una propiedad
real). Por eso el piso entra en la clave: si dos avisos declaran pisos distintos
son deptos distintos con certeza, y si uno lo declara y el otro no, no hay
evidencia suficiente para juntarlos.
"""

from src.propiedades import mlc_id

# Los campos que tienen que coincidir para considerar que dos publicaciones son
# el mismo departamento. El precio queda fuera: justamente suele ser lo único que
# cambia entre una republicación y la siguiente.
CAMPOS_IDENTIDAD = (
    "dormitorios",
    "banos",
    "superficie_util",
    "superficie_total",
    "piso",
)

# Qué estado conviene conservar cuando las republicaciones no coinciden: el aviso
# que trae los datos suficientes para decidir que cumple es más útil que el que
# dejó el filtro a medias.
PRIORIDAD_ESTADO = {"cumple": 0, "revisar": 1, "no_cumple": 2}


def clave_identidad(datos: dict | None) -> tuple | None:
    """
    Qué hace que dos publicaciones sean el mismo depto, o None si no alcanza para
    decidirlo. Sin coordenada no hay caso: dos avisos sin ubicación cacheada no
    tienen nada que los ate al mismo edificio.
    """
    if not datos or datos.get("lat") is None or datos.get("lon") is None:
        return None

    return (
        datos["lat"],
        datos["lon"],
        *((datos.get(campo) or "").strip() for campo in CAMPOS_IDENTIDAD),
    )


def _preferencia(publicacion: tuple, cache: dict) -> tuple:
    """
    Orden de preferencia dentro de un grupo, menor gana: primero el mejor estado,
    después la más barata. Los empates los rompe el orden en que llega el grupo.
    """
    link, estado, _timestamp = publicacion
    precio = (cache.get(mlc_id(link) or "") or {}).get("precio")
    return (
        PRIORIDAD_ESTADO.get(estado, len(PRIORIDAD_ESTADO)),
        # Sin precio no se puede comparar la oferta, así que va al final del grupo.
        (precio is None, precio or 0),
    )


def agrupar(saved_links: dict, cache: dict) -> tuple[dict, dict]:
    """
    Junta las republicaciones del mismo departamento.

    Recibe el {link_normalizado: (link, estado, timestamp)} de
    already_recommended.csv y devuelve:

      - una copia con una sola publicación por departamento, en el orden en que
        cada departamento apareció por primera vez (los reportes reordenan por su
        cuenta, pero el mapa dibuja en este orden y conviene que sea estable);
      - {mlc_id_vigente: [mlc_ids_de_las_republicaciones]}, solo para las
        publicaciones que efectivamente taparon a alguna otra.

    Es idempotente: agrupar lo ya agrupado devuelve lo mismo y ninguna
    republicación, así que se puede llamar en el pipeline y otra vez en el mapa.
    """
    grupos: dict[tuple, list] = {}
    for clave_saved, publicacion in saved_links.items():
        clave = clave_identidad(cache.get(mlc_id(publicacion[0]) or ""))
        # Las que no se pueden identificar quedan cada una en su propio grupo: sin
        # datos no se agrupan, pero tampoco se descartan del mapa.
        if clave is None:
            clave = ("sin-identidad", clave_saved)
        grupos.setdefault(clave, []).append((clave_saved, publicacion))

    vigentes = {}
    republicaciones = {}

    for grupo in grupos.values():
        # Entre iguales gana la que llegó primero, y el grupo llega ordenado de más
        # nueva a más vieja, así que a igual estado y precio queda la más reciente.
        por_fecha = sorted(grupo, key=lambda par: par[1][2] or "", reverse=True)
        clave_saved, elegida = min(por_fecha, key=lambda par: _preferencia(par[1], cache))
        vigentes[clave_saved] = elegida

        tapadas = [mlc_id(otra[0]) for _clave, otra in grupo if otra is not elegida]
        if tapadas:
            republicaciones[mlc_id(elegida[0])] = tapadas

    return vigentes, republicaciones
