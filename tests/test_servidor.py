import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import descartar as mod_descartar
from src import mapa as mod_mapa
from src.servidor import Servidor

DATOS = {
    "mlc_id": "MLC-1", "lat": -33.42, "lon": -70.59, "titulo": "Depto",
    "precio": 350000000, "precio_m2": 3000000, "base_m2": "útil",
    "gastos_comunes": 250000, "dormitorios": "4", "banos": "3", "piso": "5",
    "superficie_util": "100 m²", "superficie_total": "120 m²",
    "superficie_terraza": "10 m²", "orientacion": "N", "servicio": "", "escritorio": "",
}

SAVED_LINKS = {"https://x/MLC-1_JM": ("https://x/MLC-1_JM", "cumple", "2026-08-02")}


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    """Servidor real en un puerto libre, con sus archivos aislados en tmp_path."""
    monkeypatch.setattr(mod_descartar, "descartados_filename", str(tmp_path / "descartados.csv"))
    monkeypatch.setattr(mod_mapa, "mapa_filename", str(tmp_path / "mapa.html"))
    monkeypatch.setattr(mod_mapa, "load_cache", lambda: {"MLC-1": DATOS})

    servidor = Servidor(("127.0.0.1", 0), lambda: dict(SAVED_LINKS))
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield servidor
    servidor.shutdown()
    servidor.server_close()
    hilo.join(timeout=5)


def url_de(servidor, ruta):
    return f"http://127.0.0.1:{servidor.server_address[1]}{ruta}"


def pedir(servidor, ruta, cuerpo=None, content_type="application/json", metodo=None):
    """(status, texto). Los errores HTTP se devuelven en vez de levantarse."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    headers = {"Content-Type": content_type} if datos is not None else {}
    request = urllib.request.Request(
        url_de(servidor, ruta), data=datos, headers=headers, method=metodo
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as respuesta:
            return respuesta.status, respuesta.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


class TestServirElMapa:
    def test_la_raiz_devuelve_el_mapa(self, servidor):
        status, html = pedir(servidor, "/")
        assert status == 200
        assert "const PUNTOS" in html
        assert '"mlc_id": "MLC-1"' in html

    def test_se_regenera_en_cada_carga(self, servidor):
        # Sin regenerar, el mapa seguiría mostrando lo que ya se descartó.
        assert '"mlc_id": "MLC-1"' in pedir(servidor, "/")[1]
        mod_descartar.descartar("MLC-1", "a mano")
        assert '"mlc_id": "MLC-1"' not in pedir(servidor, "/")[1]

    def test_una_ruta_desconocida_da_404(self, servidor):
        assert pedir(servidor, "/otra-cosa")[0] == 404


class TestDescartarDesdeElMapa:
    def test_un_post_escribe_el_csv(self, servidor):
        status, cuerpo = pedir(servidor, "/descartar", {"mlc_id": "MLC-1", "motivo": "edificio feo"})
        assert status == 200
        assert json.loads(cuerpo)["mlc_id"] == "MLC-1"

        fila = mod_descartar.load_descartados()["MLC-1"]
        assert fila["motivo"] == "edificio feo"

    def test_deshacer_lo_saca_del_csv(self, servidor):
        pedir(servidor, "/descartar", {"mlc_id": "MLC-1"})
        status, _cuerpo = pedir(servidor, "/quitar", {"mlc_id": "MLC-1"})
        assert status == 200
        assert mod_descartar.load_descartados() == {}

    def test_deshacer_algo_que_no_estaba_da_404(self, servidor):
        assert pedir(servidor, "/quitar", {"mlc_id": "MLC-9"})[0] == 404

    def test_sin_id_da_400(self, servidor):
        assert pedir(servidor, "/descartar", {"motivo": "sin id"})[0] == 400

    def test_un_id_invalido_da_400(self, servidor):
        assert pedir(servidor, "/descartar", {"mlc_id": "no-es-un-id"})[0] == 400

    def test_un_cuerpo_que_no_es_json_da_400(self, servidor):
        request = urllib.request.Request(
            url_de(servidor, "/descartar"), data=b"{roto",
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=10)
        assert error.value.code == 400

    def test_exige_content_type_json(self, servidor):
        # Sin este chequeo, un formulario de cualquier página podría escribir en
        # el CSV: application/json fuerza un preflight CORS que no respondemos.
        status, _cuerpo = pedir(
            servidor, "/descartar", {"mlc_id": "MLC-1"},
            content_type="application/x-www-form-urlencoded",
        )
        assert status == 415
        assert mod_descartar.load_descartados() == {}

    def test_una_ruta_desconocida_no_acepta_post(self, servidor):
        assert pedir(servidor, "/borrar-todo", {"mlc_id": "MLC-1"})[0] == 404
