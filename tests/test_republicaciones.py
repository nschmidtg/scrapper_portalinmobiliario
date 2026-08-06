import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.republicaciones import agrupar


def datos(**overrides):
    base = {
        "lat": -33.4266723, "lon": -70.598759, "dormitorios": "3", "banos": "3",
        "superficie_util": "105 m²", "superficie_total": "120 m²", "piso": "",
        "precio": 355349688,
    }
    return {**base, **overrides}


def publicacion(mlc, estado="revisar", timestamp="2026-08-02T21:40:00"):
    link = f"https://portalinmobiliario.com/{mlc}-depto_JM"
    return link, (link, estado, timestamp)


def saved(*publicaciones):
    return dict(publicaciones)


class TestAgruparMismoDepto:
    """
    Un mismo departamento aparece varias veces en la búsqueda porque el corredor
    republica el aviso con otro MLC-id. Son publicaciones distintas para el
    scraper, pero una sola propiedad para quien busca depto.
    """

    def test_dos_publicaciones_del_mismo_depto_dejan_una(self):
        vigentes, republicaciones = agrupar(
            saved(publicacion("MLC-1"), publicacion("MLC-2")),
            {"MLC-1": datos(), "MLC-2": datos()},
        )
        assert len(vigentes) == 1

    def test_las_tapadas_quedan_anotadas_en_el_representante(self):
        vigentes, republicaciones = agrupar(
            saved(publicacion("MLC-1"), publicacion("MLC-2"), publicacion("MLC-3")),
            {"MLC-1": datos(), "MLC-2": datos(), "MLC-3": datos()},
        )
        (representante,) = republicaciones
        assert sorted(republicaciones[representante]) == ["MLC-2", "MLC-3"]

    def test_una_publicacion_sola_no_queda_anotada(self):
        vigentes, republicaciones = agrupar(
            saved(publicacion("MLC-1")), {"MLC-1": datos()}
        )
        assert republicaciones == {}


class TestQueSeConsideraElMismoDepto:
    def test_coordenadas_distintas_son_deptos_distintos(self):
        vigentes, _ = agrupar(
            saved(publicacion("MLC-1"), publicacion("MLC-2")),
            {"MLC-1": datos(), "MLC-2": datos(lat=-33.43)},
        )
        assert len(vigentes) == 2

    def test_misma_direccion_con_otra_superficie_son_deptos_distintos(self):
        vigentes, _ = agrupar(
            saved(publicacion("MLC-1"), publicacion("MLC-2")),
            {"MLC-1": datos(), "MLC-2": datos(superficie_util="130 m²")},
        )
        assert len(vigentes) == 2

    def test_misma_planta_en_otro_piso_son_deptos_distintos(self):
        vigentes, _ = agrupar(
            saved(publicacion("MLC-1"), publicacion("MLC-2")),
            {"MLC-1": datos(piso="4"), "MLC-2": datos(piso="7")},
        )
        assert len(vigentes) == 2

    def test_sin_ubicacion_no_se_agrupan(self):
        """Sin coordenada no hay evidencia de que sean el mismo edificio."""
        vigentes, _ = agrupar(
            saved(publicacion("MLC-1"), publicacion("MLC-2")),
            {"MLC-1": datos(lat=None, lon=None), "MLC-2": datos(lat=None, lon=None)},
        )
        assert len(vigentes) == 2

    def test_sin_datos_cacheados_no_se_agrupan(self):
        vigentes, _ = agrupar(saved(publicacion("MLC-1"), publicacion("MLC-2")), {})
        assert len(vigentes) == 2


class TestCualSobrevive:
    def mlc_ids(self, vigentes):
        return [valor[0].split("/")[-1].split("-depto")[0] for valor in vigentes.values()]

    def test_gana_la_mas_barata(self):
        """Las republicaciones suelen diferir en precio: interesa la mejor oferta."""
        vigentes, _ = agrupar(
            saved(publicacion("MLC-1"), publicacion("MLC-2")),
            {"MLC-1": datos(precio=355349688), "MLC-2": datos(precio=347180730)},
        )
        assert self.mlc_ids(vigentes) == ["MLC-2"]

    def test_el_estado_manda_sobre_el_precio(self):
        """
        Si una republicación trae los datos que hacen falta para decidir que
        cumple, esa es la que sirve, aunque el aviso más barato quedara a revisar.
        """
        vigentes, _ = agrupar(
            saved(publicacion("MLC-1", estado="cumple"), publicacion("MLC-2", estado="revisar")),
            {"MLC-1": datos(precio=355349688), "MLC-2": datos(precio=347180730)},
        )
        assert self.mlc_ids(vigentes) == ["MLC-1"]

    def test_a_igual_precio_gana_la_publicada_mas_tarde(self):
        vigentes, _ = agrupar(
            saved(
                publicacion("MLC-1", timestamp="2026-08-02T21:40:00"),
                publicacion("MLC-2", timestamp="2026-08-02T21:40:30"),
            ),
            {"MLC-1": datos(), "MLC-2": datos()},
        )
        assert self.mlc_ids(vigentes) == ["MLC-2"]

    def test_la_que_no_tiene_precio_no_le_gana_a_la_que_si(self):
        vigentes, _ = agrupar(
            saved(publicacion("MLC-1"), publicacion("MLC-2")),
            {"MLC-1": datos(precio=None), "MLC-2": datos(precio=355349688)},
        )
        assert self.mlc_ids(vigentes) == ["MLC-2"]


class TestReportes:
    """revisar.csv y cumplen.csv son la otra cara del mapa: mismo criterio."""

    def test_revisar_csv_lista_una_fila_por_depto(self, tmp_path, monkeypatch):
        import csv

        from src import main

        cache = {
            "MLC-1": {**datos(precio=355349688), "mlc_id": "MLC-1"},
            "MLC-2": {**datos(precio=347180730), "mlc_id": "MLC-2"},
        }
        revisar = tmp_path / "revisar.csv"
        monkeypatch.setattr(main, "revisar_filename", str(revisar))
        monkeypatch.setattr(main, "report_filename", str(tmp_path / "cumplen.csv"))
        monkeypatch.setattr(main, "load_cache", lambda: cache)
        monkeypatch.setattr(main, "sin_descartados", dict)
        monkeypatch.setattr(main, "generar_mapa", lambda *a, **k: "")

        main.save_reports(saved(publicacion("MLC-1"), publicacion("MLC-2")))

        filas = list(csv.DictReader(revisar.open(encoding="utf-8")))
        assert len(filas) == 1
        assert "MLC-2" in filas[0]["link"]

    def test_el_mapa_del_pipeline_sigue_contando_las_republicaciones(
        self, tmp_path, monkeypatch
    ):
        """
        save_reports agrupa para los CSV y generar_mapa agrupa de nuevo; si le
        pasa lo ya agrupado, el segundo pase no encuentra republicaciones y el
        popup pierde el dato.
        """
        from src import main

        cache = {
            "MLC-1": {**datos(precio=355349688), "mlc_id": "MLC-1", "titulo": "Depto"},
            "MLC-2": {**datos(precio=347180730), "mlc_id": "MLC-2", "titulo": "Depto"},
        }
        mapa = tmp_path / "mapa.html"
        monkeypatch.setattr(main, "revisar_filename", str(tmp_path / "revisar.csv"))
        monkeypatch.setattr(main, "report_filename", str(tmp_path / "cumplen.csv"))
        monkeypatch.setattr(main, "load_cache", lambda: cache)
        monkeypatch.setattr(main, "sin_descartados", dict)
        monkeypatch.setattr("src.mapa.mapa_filename", str(mapa))
        monkeypatch.setattr("src.mapa.load_cache", lambda: cache)
        monkeypatch.setattr("src.mapa.sin_descartados", dict)

        main.save_reports(saved(publicacion("MLC-1"), publicacion("MLC-2")))

        assert '"republicaciones": 1' in mapa.read_text(encoding="utf-8")


class TestIdempotencia:
    def test_agrupar_lo_ya_agrupado_no_cambia_nada(self):
        cache = {"MLC-1": datos(), "MLC-2": datos()}
        vigentes, _ = agrupar(saved(publicacion("MLC-1"), publicacion("MLC-2")), cache)
        otra_vez, republicaciones = agrupar(vigentes, cache)
        assert otra_vez == vigentes
        assert republicaciones == {}
