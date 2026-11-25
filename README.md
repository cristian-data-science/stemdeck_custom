<div align="center">

<img src="imgs/stemdeck-svg-assets/stemdeck-logo-stacked.svg" alt="StemDeck" width="420" />

**StemDeck con partitura, piano y saxo para practicar**

Versión modificada de [StemDeck](https://github.com/stemdeckapp/stemdeck): separa una canción
por instrumentos, **escribe su partitura** y te deja **practicarla** en piano o saxo.
Todo corre en tu computador: no se sube ninguna canción.

[Guía de uso](GUIA-DE-USO.md) · [Documentación técnica](DOCUMENTACION-TECNICA.md) ·
[Detalle del módulo de partitura](docs/partitura.md) · [README del proyecto original](docs/README-original.md)

</div>

<p align="center">
  <img src="imgs/screenshot/stemdeck.png" alt="El estudio de StemDeck: una canción separada en voz, batería, bajo, guitarra, piano y otros" width="100%">
</p>

## Qué es

[StemDeck](https://github.com/stemdeckapp/stemdeck) es una aplicación de código abierto que
separa una canción en hasta seis pistas (voz, batería, bajo, guitarra, piano y otros) y las abre
en un estudio para practicar: silenciar o dejar sola una pista, bajar la velocidad, repetir un
trozo, cambiar el tono y tocar con metrónomo.

Este repositorio parte de StemDeck y le agrega lo necesario para **aprender a tocar la canción**:
pasar de la grabación a una partitura que se puede leer, corregir y practicar.

## Lo que agrega esta versión

### 𝄞 Partitura de cualquier instrumento

- De la pista de piano (o bajo, guitarra, voz y otros) a **MIDI y partitura editable**:
  pentagrama doble con clave de sol y de fa, tonalidad, compás y tempo de la canción.
- **Acordes** sobre el pentagrama y **nombre dentro de cada nota** (do re mi o C D E), si lo quieres.
- **Reproducción sincronizada:** la nota que suena se ilumina y la partitura avanza sola.
  Puedes escuchar la pista, el MIDI extraído, los dos juntos o la canción completa.
- **Corregir a mano:** agregar, mover o borrar notas, con historial para deshacer. Se guarda solo.
- **Exportar** a MIDI, MusicXML (para abrir en MuseScore u otro editor) y PDF para imprimir.
- **Comprobación en un minuto** con una canción de calibración que trae su resultado esperado.

### 🎹 Piano para practicar

- **Piano con notas cayendo**, en el mismo punto que la partitura (un botón cambia entre las dos vistas).
- **Mano por mano:** silencia una mano y tócala tú, mientras suena la otra.
- **Bucle por compases**, velocidad (25 %, 50 %, 70 %, 100 %), metrónomo y cuenta de entrada.
- **Teclado MIDI:** conecta un teclado y usa el modo **Esperarme**, que detiene la canción en cada
  nota hasta que la tocas.
- Opcional: escuchar la partitura con **Pianoteq** (piano virtual de pago), si está instalado.

### 🎷 Saxo

- Convierte una parte de la canción (voz, piano, otros…) en una **línea de saxo** alto, soprano,
  tenor o barítono, con la nota escrita para el instrumento y su **digitación**.
- Suena con grabaciones reales de saxo incluidas o, si está instalado, con **SWAM** (saxo virtual
  de pago) para un sonido más realista.
- **Micrófono (🎤 Practicar):** toca tu saxo y la vista te dice si estás en la nota y cuántos
  cents arriba o abajo.
- Se abre desde el 🎷 del mezclador o desde el botón **🎷 Saxo** de la partitura, con el
  instrumento que estás viendo.

### Más

- **Celular y tablet:** se comparte por la red Wi-Fi de la casa con un código QR (partitura y
  mezclador en la tablet, sobre el piano).
- **Partitura desde PDF** y lectura de digitaciones (experimental, con Audiveris).
- **Segundo separador, BS-RoFormer** (experimental), que reconoce mejor los teclados.
- **Arranque con doble clic en Windows:** `Iniciar StemDeck dev.cmd` y
  `Compartir StemDeck en la red.cmd`.
- Interfaz y documentación de lo nuevo en **español**.

## Cómo empezar

Esta versión se usa en **Windows** como servidor local (no hay instalador). La instalación completa
está en la [documentación técnica](DOCUMENTACION-TECNICA.md#5-instalación-desde-cero-windows). En resumen:

1. Instalar [uv](https://docs.astral.sh/uv/), [ffmpeg](https://ffmpeg.org/) y [Git](https://git-scm.com/).
2. Clonar el repositorio y ejecutar `uv sync --extra dev` en su carpeta.
3. Doble clic en **`Iniciar StemDeck dev.cmd`**: se abre http://localhost:8001.

Para usarla sin conocimientos técnicos: [Guía de uso](GUIA-DE-USO.md).

### ¿Hace falta una tarjeta NVIDIA?

**No.** Sin tarjeta de video NVIDIA todo se procesa con el procesador (CPU), con el mismo
resultado, pero **más lento**:

| Paso | Con procesador (CPU) | Con GPU NVIDIA |
|---|---|---|
| Separar 60 s de audio | ~20 s | ~1,3 s |
| Partitura del piano de una canción de 9 min | ~6 min | ~20 s |

Medido en un portátil con RTX 5070. Con otro procesador los tiempos cambian. Para activar la GPU:
[documentación técnica, sección 4](DOCUMENTACION-TECNICA.md#4-gpu-nvidia-o-procesador-cpu).

### Descargas de YouTube

Se puede pegar un link de YouTube. Si YouTube bloquea la descarga («Sign in to confirm you're not
a bot»), la app puede usar las cookies de tu sesión: paso a paso en la
[guía de uso](GUIA-DE-USO.md#si-youtube-no-deja-descargar-las-cookies). Ese archivo es personal:
nunca se sube al repositorio.

## Documentación

| Documento | Para quién |
|---|---|
| [GUIA-DE-USO.md](GUIA-DE-USO.md) | Quien usa la app, sin detalles técnicos |
| [DOCUMENTACION-TECNICA.md](DOCUMENTACION-TECNICA.md) | Quien la instala o sigue programándola (persona o agente) |
| [docs/partitura.md](docs/partitura.md) | Referencia completa de partitura, piano y saxo: cada ajuste y cómo verificarlo |
| [docs/README-original.md](docs/README-original.md) | README del proyecto original (en inglés), con todas sus funciones |

## Aviso

Herramienta para estudio y práctica personal. Usa solo audio que tengas derecho a procesar y
respeta los términos de los sitios desde donde descargas. La descarga desde YouTube usa
[yt-dlp](https://github.com/yt-dlp/yt-dlp) y puede ir contra los términos de servicio de YouTube.
Más detalle en el [aviso del proyecto original](docs/README-original.md#disclaimer).

## Licencia y créditos

- Basado en [StemDeck](https://github.com/stemdeckapp/stemdeck), licencia [Apache-2.0](LICENSE).
  Los cambios de este repositorio se publican con la misma licencia.
- Transcripción de piano: [piano_transcription_inference](https://github.com/qiuqiangkong/piano_transcription_inference).
  Bajo, guitarra y voz: Basic Pitch de Spotify (Apache-2.0). Partitura dibujada con
  [Verovio](https://www.verovio.org/).
- Grabaciones de saxo: University of Iowa Electronic Music Studios (uso libre). Foto del saxo:
  Wikimedia Commons, CC BY-SA 4.0. Modelo de manos entrenado con el conjunto de datos
  [hannds](https://github.com/cemfi/hannds) (MIT).
- Avisos de cada componente junto a sus archivos (`app/score/models/`, `static/img/sax/NOTICE.txt`,
  `static/vendor/verovio/`).
