"""
Sirve el mapa en localhost para poder descartar publicaciones con un click.

El mapa abierto como archivo (file://) no puede escribir en el disco, así que el
botón "descartar" del popup necesita alguien que reciba el click y edite
descartados.csv. Eso es todo lo que hace este servidor: dos POST y el HTML.

    python src/servidor.py                # http://127.0.0.1:8000
    python src/servidor.py --puerto 8080
    python src/servidor.py --backfill     # busca las coordenadas que falten

El mapa se regenera en cada carga de la página, así que refleja lo que haya en
already_recommended.csv, propiedades.csv y descartados.csv en ese momento.

Escucha solo en 127.0.0.1: no queda expuesto a la red.
"""

import json
import os.path
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.descartar import descartar, quitar_descartado
from src.mapa import generar_mapa

HOST = "127.0.0.1"
PUERTO_DEFECTO = 8000

# Un cuerpo JSON obliga al navegador a pedir permiso con un preflight CORS que
# este servidor no responde, así que una página cualquiera no puede escribir en
# el CSV a nuestras espaldas (un <form> sí puede hacer POST, pero no con este
# Content-Type).
CONTENT_TYPE_ESPERADO = "application/json"

MOTIVO_DESDE_EL_MAPA = "descartada desde el mapa"


class Handler(BaseHTTPRequestHandler):
    server_version = "mapa-departamentos"

    def do_GET(self):
        if self.ruta() not in ("/", "/mapa.html"):
            self.responder(404, {"error": "no existe"})
            return

        # Se regenera en cada carga: es barato (leer dos CSV y armar el HTML) y
        # evita mostrar publicaciones que ya se descartaron en otra pestaña.
        # Se sirve la ruta que devuelve generar_mapa, no una guardada al
        # importar, para no leer un archivo distinto del que se acaba de escribir.
        ruta = generar_mapa(self.server.leer_links(), resumen=False)
        with open(ruta, encoding="utf-8") as f:
            self.responder_html(f.read())

    def do_POST(self):
        acciones = {"/descartar": self.descartar, "/quitar": self.quitar}
        accion = acciones.get(self.ruta())
        if not accion:
            self.responder(404, {"error": "no existe"})
            return

        if self.headers.get("Content-Type", "").split(";")[0].strip() != CONTENT_TYPE_ESPERADO:
            self.responder(415, {"error": f"se espera {CONTENT_TYPE_ESPERADO}"})
            return

        cuerpo = self.leer_json()
        if cuerpo is None:
            self.responder(400, {"error": "el cuerpo no es JSON válido"})
            return

        accion(cuerpo)

    def descartar(self, cuerpo: dict):
        identificador = descartar(
            str(cuerpo.get("mlc_id") or ""),
            str(cuerpo.get("motivo") or MOTIVO_DESDE_EL_MAPA),
        )
        if not identificador:
            self.responder(400, {"error": "falta un MLC-id válido"})
            return
        print(f"→ {identificador} descartada")
        self.responder(200, {"mlc_id": identificador})

    def quitar(self, cuerpo: dict):
        identificador = quitar_descartado(str(cuerpo.get("mlc_id") or ""))
        if not identificador:
            self.responder(404, {"error": "no estaba descartada"})
            return
        print(f"← {identificador} vuelve al mapa")
        self.responder(200, {"mlc_id": identificador})

    def ruta(self) -> str:
        return self.path.split("?")[0]

    def leer_json(self) -> dict | None:
        try:
            largo = int(self.headers.get("Content-Length") or 0)
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except (ValueError, TypeError):
            return None
        return cuerpo if isinstance(cuerpo, dict) else None

    def responder(self, status: int, cuerpo: dict):
        self.enviar(status, "application/json; charset=utf-8", json.dumps(cuerpo).encode("utf-8"))

    def responder_html(self, html: str):
        self.enviar(200, "text/html; charset=utf-8", html.encode("utf-8"))

    def enviar(self, status: int, content_type: str, cuerpo: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, formato, *args):
        # El log por request no aporta nada acá; los descartes ya se imprimen.
        pass


class Servidor(ThreadingHTTPServer):
    """
    `leer_links` es una función que devuelve el dict de already_recommended.csv.
    Se pasa así para no importar src.main (y con él Selenium) desde el handler,
    y para poder inyectar datos de prueba en los tests.
    """

    allow_reuse_address = True

    def __init__(self, direccion, leer_links):
        super().__init__(direccion, Handler)
        self.leer_links = leer_links


def _main(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(__doc__.strip())
        return 0

    puerto = PUERTO_DEFECTO
    if "--puerto" in argv:
        try:
            puerto = int(argv[argv.index("--puerto") + 1])
        except (IndexError, ValueError):
            print("✗ --puerto necesita un número")
            return 1

    from src.main import open_or_create_csv

    if "--backfill" in argv:
        generar_mapa(open_or_create_csv(), con_backfill=True)

    try:
        servidor = Servidor((HOST, puerto), open_or_create_csv)
    except OSError as error:
        print(f"✗ No pude abrir el puerto {puerto}: {error}")
        print("  Probá con otro: python src/servidor.py --puerto 8080")
        return 1

    url = f"http://{HOST}:{servidor.server_address[1]}/"
    print(f"Mapa en {url}")
    print("  El botón «descartar» del popup escribe en descartados.csv.")
    print("  Ctrl+C para cortar.")
    webbrowser.open(url)

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nListo.")
    finally:
        servidor.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
