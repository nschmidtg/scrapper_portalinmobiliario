import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import descartar as mod


@pytest.fixture(autouse=True)
def archivo_temporal(tmp_path, monkeypatch):
    """Aísla el descartados.csv real: cada test escribe en su propio archivo."""
    ruta = tmp_path / "descartados.csv"
    monkeypatch.setattr(mod, "descartados_filename", str(ruta))
    return ruta


LINK = "https://portalinmobiliario.com/MLC-123-depto-_JM#tracking_id=abc"


class TestDescartar:
    def test_agrega_una_publicacion_por_link(self):
        assert mod.descartar(LINK, "edificio feo") == "MLC-123"
        assert "MLC-123" in mod.load_descartados()

    def test_agrega_una_publicacion_por_id(self):
        assert mod.descartar("MLC-456") == "MLC-456"
        assert "MLC-456" in mod.load_descartados()

    def test_guarda_el_motivo_y_el_timestamp(self):
        mod.descartar(LINK, "pasaje sin salida")
        fila = mod.load_descartados()["MLC-123"]
        assert fila["motivo"] == "pasaje sin salida"
        assert fila["timestamp"]

    def test_no_duplica_y_actualiza_el_motivo(self):
        mod.descartar(LINK, "primer motivo")
        timestamp_original = mod.load_descartados()["MLC-123"]["timestamp"]

        mod.descartar(LINK, "motivo corregido")

        descartados = mod.load_descartados()
        assert len(descartados) == 1
        assert descartados["MLC-123"]["motivo"] == "motivo corregido"
        # El timestamp es cuándo se descartó, no cuándo se editó el motivo.
        assert descartados["MLC-123"]["timestamp"] == timestamp_original

    def test_ignora_una_referencia_sin_id(self):
        assert mod.descartar("https://portalinmobiliario.com/venta/departamento/") is None
        assert mod.load_descartados() == {}


class TestQuitarDescartado:
    def test_saca_una_publicacion_de_la_lista(self):
        mod.descartar("MLC-1")
        assert mod.quitar_descartado("MLC-1") == "MLC-1"
        assert mod.load_descartados() == {}

    def test_acepta_el_link_completo(self):
        mod.descartar(LINK)
        assert mod.quitar_descartado(LINK) == "MLC-123"

    def test_no_toca_a_las_demas(self):
        mod.descartar("MLC-1")
        mod.descartar("MLC-2")
        mod.quitar_descartado("MLC-1")
        assert list(mod.load_descartados()) == ["MLC-2"]

    def test_devuelve_none_si_no_estaba(self):
        assert mod.quitar_descartado("MLC-9") is None

    def test_devuelve_none_sin_id(self):
        assert mod.quitar_descartado("https://portalinmobiliario.com/venta/") is None


class TestLoadDescartados:
    def test_sin_archivo_devuelve_vacio(self):
        assert mod.load_descartados() == {}

    def test_tolera_lineas_sin_id(self, archivo_temporal):
        archivo_temporal.write_text(
            "mlc_id,motivo,timestamp\n,sin id,2026-08-02T18:40\nMLC-1,ok,2026-08-02T18:41\n",
            encoding="utf-8",
        )
        assert list(mod.load_descartados()) == ["MLC-1"]

    def test_tolera_un_archivo_de_solo_ids(self, archivo_temporal):
        # Pegar ids a mano sin motivo ni timestamp tiene que funcionar igual.
        archivo_temporal.write_text("mlc_id,motivo,timestamp\nMLC-1\nMLC-2\n", encoding="utf-8")
        assert list(mod.load_descartados()) == ["MLC-1", "MLC-2"]


class TestSinDescartados:
    def saved_links(self):
        return {
            "https://x/MLC-1_JM": ("https://x/MLC-1_JM#t=1", "cumple", "2026-08-02"),
            "https://x/MLC-2_JM": ("https://x/MLC-2_JM#t=2", "revisar", "2026-08-02"),
            "https://x/MLC-3_JM": ("https://x/MLC-3_JM#t=3", "no_cumple", "2026-08-02"),
        }

    def test_saca_los_descartados(self):
        mod.descartar("MLC-2", "ya la vi")
        vigentes = mod.sin_descartados(self.saved_links())
        assert [mod.mlc_id(link) for link, _e, _t in vigentes.values()] == ["MLC-1", "MLC-3"]

    def test_sin_descartados_devuelve_todo(self):
        assert len(mod.sin_descartados(self.saved_links())) == 3

    def test_no_modifica_el_diccionario_original(self):
        mod.descartar("MLC-1")
        original = self.saved_links()
        mod.sin_descartados(original)
        assert len(original) == 3
