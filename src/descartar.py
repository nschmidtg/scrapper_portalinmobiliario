"""
Lista negra de publicaciones: las que uno mira y decide que no van, por razones
que ningún filtro automático puede ver (el edificio, la calle, ya la visité).

Una publicación descartada desaparece del mapa y de los reportes, y src/main.py
la saltea antes de abrirla, así que tampoco se vuelve a evaluar ni gasta una
pasada de Selenium. Para revivirla, borrar su línea de descartados.csv.

Lo normal es hacerlo con un click en el botón del popup del mapa (para eso está
src/servidor.py); esta línea de comandos es el mismo mecanismo a mano.

Uso:
    python -m src.descartar <link o MLC-id> ["motivo"]
    python -m src.descartar --quitar <link o MLC-id>
    python -m src.descartar --list
"""

import csv
import os.path
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.propiedades import mlc_id

descartados_filename = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "descartados.csv"
)

CAMPOS = ["mlc_id", "motivo", "timestamp"]


def load_descartados() -> dict:
    """
    Lee descartados.csv y devuelve {mlc_id: {"motivo": ..., "timestamp": ...}}.

    El archivo está pensado para editarse a mano, así que las líneas sin id se
    ignoran y las columnas que falten quedan en "": pegar solo ids alcanza.
    """
    descartados = {}
    if not os.path.exists(descartados_filename):
        return descartados

    with open(descartados_filename, 'r', newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            identificador = mlc_id(row.get("mlc_id") or "")
            if not identificador:
                continue
            descartados[identificador] = {
                "motivo": (row.get("motivo") or "").strip(),
                "timestamp": (row.get("timestamp") or "").strip(),
            }

    return descartados


def save_descartados(descartados: dict) -> None:
    with open(descartados_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction='ignore')
        writer.writeheader()
        for identificador, datos in descartados.items():
            writer.writerow({"mlc_id": identificador, **datos})


def descartar(referencia: str, motivo: str = "") -> str | None:
    """
    Agrega una publicación a la lista negra. Acepta el link completo o el
    MLC-id pelado. Devuelve el id descartado, o None si la referencia no tiene
    uno (una URL de búsqueda, por ejemplo).

    Si ya estaba, se actualiza el motivo pero se conserva el timestamp: lo que
    interesa es cuándo se descartó, no cuándo se corrigió la nota.
    """
    identificador = mlc_id(referencia)
    if not identificador:
        return None

    descartados = load_descartados()
    anterior = descartados.get(identificador, {})
    descartados[identificador] = {
        "motivo": motivo or anterior.get("motivo", ""),
        "timestamp": anterior.get("timestamp") or datetime.now().isoformat(timespec="minutes"),
    }
    save_descartados(descartados)

    return identificador


def quitar_descartado(referencia: str) -> str | None:
    """
    Saca una publicación de la lista negra: vuelve al mapa con el estado que ya
    tenía. Devuelve el id, o None si no estaba descartada.
    """
    identificador = mlc_id(referencia)
    if not identificador:
        return None

    descartados = load_descartados()
    if identificador not in descartados:
        return None

    del descartados[identificador]
    save_descartados(descartados)

    return identificador


def sin_descartados(saved_links: dict) -> dict:
    """
    Copia de saved_links sin las publicaciones descartadas. Es el filtro que
    aplican los reportes y el mapa; no toca already_recommended.csv, así que
    quitar una línea de descartados.csv la trae de vuelta con su estado intacto.
    """
    descartados = load_descartados()
    if not descartados:
        return dict(saved_links)

    return {
        clave: valor
        for clave, valor in saved_links.items()
        if mlc_id(valor[0]) not in descartados
    }


def _main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0

    if argv[0] == "--list":
        descartados = load_descartados()
        if not descartados:
            print("No hay publicaciones descartadas.")
            return 0
        print(f"{len(descartados)} publicaciones descartadas:")
        for identificador, datos in descartados.items():
            nota = f" — {datos['motivo']}" if datos["motivo"] else ""
            print(f"  {identificador}{nota}")
        return 0

    if argv[0] == "--quitar":
        identificador = quitar_descartado(argv[1] if len(argv) > 1 else "")
        if not identificador:
            print("✗ No estaba descartada (o la referencia no tiene un MLC-id)")
            return 1
        print(f"✓ {identificador} vuelve al mapa")
        return 0

    referencia, motivo = argv[0], " ".join(argv[1:])
    identificador = descartar(referencia, motivo)
    if not identificador:
        print(f"✗ No encontré un MLC-id en «{referencia}»")
        return 1

    nota = f' ("{motivo}")' if motivo else ""
    print(f"✓ {identificador} descartada{nota}")
    print("  Corré `python src/mapa.py` para regenerar el mapa sin esa publicación.")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
