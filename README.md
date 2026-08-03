# Scrapper Portal Inmobiliario

Busca departamentos en venta en Portal Inmobiliario, descarta los que no cumplen
los criterios y deja los candidatos en un mapa y en un par de CSV.

La idea es no volver a mirar dos veces la misma publicación: cada una se evalúa
una sola vez, queda registrada con su estado, y las que uno descarta a mano
desaparecen para siempre.

## Instalación

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-dev.txt   # pytest, solo para correr los tests
```

Necesita Chrome instalado: el scraper usa Selenium para abrir cada publicación y
hacer click en "Revisar todas las características", que es donde Portal
Inmobiliario esconde la mitad de los atributos.

## Uso

```bash
python src/main.py         # scrapea las publicaciones nuevas y actualiza todo
python src/servidor.py     # abre el mapa en el navegador, con el botón "descartar"
```

Con eso alcanza para el día a día: `main.py` procesa lo nuevo y `servidor.py`
sirve el mapa para revisarlo.

Comandos sueltos, para cuando se necesitan:

```bash
python src/mapa.py                       # regenera mapa.html sin scrapear nada
python src/mapa.py --backfill            # busca las coordenadas que falten
python -m src.descartar <link|MLC-id> "motivo"
python -m src.descartar --quitar <link|MLC-id>
python -m src.descartar --list
```

Para cambiar la búsqueda (precio, comuna, polígono, m² mínimos) se edita
`base_url` en `src/main.py`: es la URL de la búsqueda de Portal Inmobiliario con
todos sus filtros, copiada del navegador.

## Los tres estados

Cada publicación queda en uno de tres estados. La regla es no descartar por
falta de datos: solo se descarta lo que está confirmado.

| Estado | Qué significa | Dónde queda |
| --- | --- | --- |
| `cumple` | Pasó todos los filtros | `cumplen.csv`, pin verde |
| `revisar` | Algún dato no venía y no se pudo decidir | `revisar.csv`, pin naranja |
| `no_cumple` | Al menos un filtro la descartó | pin gris (apagado por defecto) |

Los pines que no cumplen se dibujan igual, apagados, porque sirven como contexto
del barrio.

## Los filtros

Viven en `src/filtros.py`, cada uno devuelve `Resultado(cumple, motivo)`:

- **Orientación** — tiene que dar al norte (en cualquier combinación: `N`, `NP`,
  `NOSP`) o al oriente sin sur (`O`). Quedan fuera `S`, `SP`, `P` y `SO`. El
  criterio es que el departamento no sea oscuro.
- **Piso** — entre 4 y 8.
- **Dormitorios** — 4 o más pasan solos. Con 3 hace falta habitación de servicio
  o escritorio; el servicio se confirma por atributo o por el texto del aviso, el
  escritorio solo por texto porque Portal Inmobiliario no lo publica como
  atributo.
- **Terraza** — al menos 8 m². Si el aviso no declara la superficie va a
  `revisar`, no se descarta: la búsqueda ya filtra por "tiene terraza", así que
  la terraza está, solo no sabemos cuánto mide.

`check_reforma` está escrita pero desactivada (fuera de la tupla `FILTROS`),
porque depende del texto del aviso y es ruidosa.

Los umbrales son constantes arriba del módulo (`TERRAZA_MINIMA_M2`,
`PISO_MINIMO`, `PISO_MAXIMO`). Para agregar un filtro: una función que devuelva
`Resultado`, y sumarla a `FILTROS`.

### El motivo

El popup de cada pin que no cumple dice por qué: `orientación SO; piso 2 (fuera
de 4-8)`, `terraza 5 m² (mínimo 8)`, `no declara superficie de terraza`.

No se guarda en ningún CSV: se recalcula desde `propiedades.csv` cada vez que se
genera el mapa. Por eso las publicaciones viejas también lo muestran, y si mañana
se cambia un umbral los motivos se actualizan solos en vez de quedar viejos.

## Descartar a mano

Los filtros no ven el edificio, la calle ni que uno ya fue a verlo. Para eso está
la lista negra:

- **Con un click**: `python src/servidor.py`, click en el pin, botón
  `descartar`. Escribe la línea en `descartados.csv`, el pin desaparece al
  instante y queda un aviso con **Deshacer** por unos segundos.
- **A mano**: `python -m src.descartar <link|MLC-id> "motivo"`, o editando
  `descartados.csv` directamente (pegar ids sueltos alcanza, el motivo y la fecha
  son opcionales).

Una publicación descartada no se dibuja en el mapa, no aparece en los reportes y
**no se vuelve a evaluar**: `main.py` la saltea antes de abrirla, así que no gasta
una pasada de Selenium aunque siga saliendo en la búsqueda. Sigue guardada en
`already_recommended.csv` con su estado, así que borrar su línea de
`descartados.csv` la trae de vuelta intacta.

## El servidor

El mapa es un HTML estático y un archivo abierto con `file://` no puede escribir
en el disco, así que el botón necesita alguien que reciba el click:
`src/servidor.py` sirve el mapa y expone `POST /descartar` y `POST /quitar`.

- Escucha solo en `127.0.0.1`, no queda expuesto a la red.
- Exige `Content-Type: application/json`, para que una página cualquiera no pueda
  escribir en el CSV con un `<form>`.
- Regenera el mapa en cada carga, así que un reload ya refleja lo que haya en los
  CSV.

Sin el servidor el mapa funciona igual (`python src/mapa.py` y abrirlo), solo que
sin botón: el panel muestra una nota con el comando.

## Archivos

Código:

| Archivo | Qué hace |
| --- | --- |
| `src/main.py` | Scrapea la búsqueda con Selenium y clasifica lo nuevo |
| `src/filtros.py` | Los filtros y el motivo del descarte |
| `src/propiedades.py` | Extrae los datos de una publicación y cachea |
| `src/mapa.py` | Genera `mapa.html` |
| `src/descartar.py` | Lista negra manual |
| `src/servidor.py` | Sirve el mapa y recibe el click del botón |

Datos (versionados a propósito, para poder clonar el repo en otra máquina y
seguir donde iba en vez de scrapear todo de nuevo):

| Archivo | Qué guarda |
| --- | --- |
| `already_recommended.csv` | Un link por línea con su estado y cuándo se evaluó |
| `propiedades.csv` | Cache de los datos de cada publicación, por `MLC-id` |
| `descartados.csv` | Lista negra manual |
| `cumplen.csv`, `revisar.csv` | Reportes ordenados por $/m² |

`mapa.html` es lo único generado que no se versiona: se regenera en un segundo y
cambia en cada corrida.

El cache existe para no volver a bajar una publicación ya vista: `main.py` la
guarda al pasar, y el mapa y los reportes leen de ahí.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

Los tests de extracción usan `tests/fixtures/publicacion.html`, una publicación
real guardada que **no** se versiona porque trae los datos de contacto del
corredor. En un clon nuevo esos tests se saltean solos; para tenerlos, guardar
cualquier publicación con ese nombre.
