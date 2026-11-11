# Módulo «Partitura»: del stem al MIDI y a una partitura editable

Estado: **implementado** (2026-10-26). Guía de uso y verificación: [partitura.md](partitura.md).

### Qué cambió respecto al plan

- **Formato de render: MEI, no MusicXML.** La Fase 0 mostró que Verovio conserva el
  `xml:id` de cada nota del MEI en el SVG (100 compases en ~170 ms). Generar MEI desde Python
  da control total sobre ids, acordes con texto libre, empates y tresillos. Por eso no hizo
  falta music21: el MusicXML de exportación lo escribe `app/score/musicxml.py` desde el mismo
  grabado.
- **Basic Pitch vendorizado (solo ONNX).** El paquete exige TensorFlow, que no tiene wheels
  para Python 3.12 en Windows, y habría metido tensorflow-macos y coremltools en los builds de
  macOS. Se portó solo la inferencia ONNX y la creación de notas
  (`app/score/basic_pitch_onnx.py`, Apache-2.0, con LICENSE y NOTICE en `app/score/models/`).
- **Modo dev en Windows:** `--loop asyncio:ProactorEventLoop` y sin `--reload` (ver
  partitura.md). Con `--reload`, cualquier endpoint con ffmpeg falla; el problema ya existía en
  el proyecto.
- **Seguimiento y edición en la misma página** (Fases 3 y 4 juntas). La edición es por
  selección + teclado, no arrastrando notas; eso queda fuera de v1.

## 1. Qué resuelve

Después de separar una canción, eliges un stem (primero **piano**) y lo abres en una vista
nueva donde:

1. Se extrae el MIDI de ese stem (notas con inicio, fin, altura y velocidad).
2. Se muestra como **partitura de piano en sistema doble** (clave de sol + clave de fa).
3. Cada cabeza de nota lleva **su nombre dentro** (do, re, mi… como en la foto de referencia).
4. Arriba del pentagrama aparece el **acorde principal** (Sib, Do, Fa, La/Mi, Rem…).
5. Se muestran **BPM, compás y tonalidad**.
6. Al reproducir, la partitura **sigue el audio** (cursor + resaltado de notas + scroll).
7. La partitura es **editable** para limpiar el MIDI (borrar, mover, cambiar altura/duración,
   cambiar de mano) y exportable (MIDI / MusicXML).

## 2. Lo que el proyecto ya tiene y vamos a reutilizar (verificado en el código)

| Necesidad | Ya existe | Dónde |
|---|---|---|
| Stem de piano | Demucs `htdemucs_6s` separa `piano` | `app/core/config.py:89`, `:293` |
| BPM | `job.bpm` | `app/core/models.py:234` |
| Tonalidad | `job.key`, `job.scale` | `app/core/models.py:235-236` |
| Pulsos y compases reales | `stems/beats.json` (`beats`, `bars[].beats_per_bar`, `bpm`, `confidence`) | `app/pipeline/beatgrid.py`, `GET /api/jobs/{id}/stems/beats.json` |
| Patrón «tarea bajo demanda sobre un job terminado» | `POST /api/jobs/{id}/vocal-split` | `app/api/jobs.py:690` |
| Patrón «modelo pesado en proceso aparte con timeout/cancel» | worker de Whisper | `app/pipeline/transcribe.py`, `transcribe_worker.py` |
| Página separada del DAW | interfaz móvil | `static/mobile/` |
| Tests | pytest, `tests/js/*.test.mjs` (node), Playwright e2e con job fixture | `tests/` |

Consecuencia clave: **no hay que volver a detectar BPM**. Cuantizamos las notas contra los
pulsos reales de `beats.json`, no contra un BPM constante. Eso absorbe las variaciones de tempo
de una grabación humana, que es la causa número uno de partituras ilegibles al convertir audio a MIDI.

Restricción importante: la CSP (`app/main.py`, `_CSP`) solo permite scripts del propio origen
(`script-src 'self' 'wasm-unsafe-eval'`). Toda librería de frontend se **vendoriza** en
`static/vendor/`; no se puede usar un CDN.

## 3. Arquitectura

```
                 ┌─────────────── backend (Python) ────────────────┐
piano.wav ──►  [A] Transcripción  ──► raw_notes.json   (inmutable)
                       │
beats.json ──► [B] Notación (pura, sin ML, determinista)
job.key   ──►        cuantizar · separar manos · deletrear notas · detectar acordes
                       │
               notes.json (editable) ──► score.musicxml / score.mid
                 └──────────────────────────────────────────────────┘
                                       │
                 ┌──────────── frontend /score/ ─────────────────────┐
                 [C] Render (Verovio u OSMD, a decidir en la Fase 0)
                 [D] Etiquetas en cabezas de nota + acordes arriba
                 [E] Reproducción y seguimiento (audio.currentTime → nota)
                 [F] Edición → PATCH notes.json → re-render
                 └────────────────────────────────────────────────────┘
```

**Fuente única de verdad: `notes.json`** (lista de notas con `id` estable). La partitura es
siempre una *vista derivada*. Esto es lo que hace todo verificable: cualquier cosa que veas en
pantalla se puede contrastar con un JSON legible, y cada transformación es una función pura
con entrada y salida comparables.

### Archivos por job y stem

```
jobs/<job_id>/score/<stem>/
  meta.json         motor, versión del modelo, bpm, compás, tonalidad, parámetros de cuantización
  raw_notes.json    salida cruda del modelo (nunca se edita; sirve para «Restaurar»)
  notes.json        notas cuantizadas + ediciones del usuario
  chords.json       acordes detectados (o editados)
```

### Formato de nota (contrato entre todas las piezas)

```json
{ "id": "n0042", "midi": 65, "start": 12.480, "end": 12.960,
  "velocity": 74, "hand": "R",
  "q": { "bar": 23, "beat": 1, "sub": 0, "dur": "8", "tuplet": null },
  "spelling": "F" }
```

`start/end` en segundos (para seguir el audio). `q` es la posición cuantizada (para dibujar).
`hand` decide el pentagrama: `R` = clave de sol, `L` = clave de fa.

### Endpoints nuevos (`app/api/score.py`)

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/api/jobs/{id}/score/{stem}` | Lanza la transcripción (202). Idempotente si ya existe. |
| GET | `/api/jobs/{id}/score/{stem}` | Estado + `meta` + `notes` + `chords`. |
| PATCH | `/api/jobs/{id}/score/{stem}/notes` | Guarda ediciones (validado con Pydantic, con límite de tamaño). |
| POST | `/api/jobs/{id}/score/{stem}/requantize` | Re-cuantiza con otros parámetros (rejilla, punto de división de manos). |
| DELETE | `/api/jobs/{id}/score/{stem}/notes` | Restaurar a la transcripción original. |
| GET | `/api/jobs/{id}/score/{stem}.mid` / `.musicxml` | Descargas. |

### Página nueva

`static/score/index.html` + `static/js/score/*.js`, abierta en `/score/?job=<id>&stem=piano`.
Se accede desde un botón nuevo «Partitura» en la fila del stem en el mezclador
(`static/js/mixer.js`, junto al botón de descarga). En el navegador abre una pestaña nueva;
en la app de escritorio (Tauri) se navega en la misma ventana con botón «Volver» (riesgo
anotado en §8).

## 4. Decisiones técnicas

### [A] Motor de transcripción

| Opción | Para qué | Licencia | Comentario |
|---|---|---|---|
| **ByteDance `piano_transcription_inference`** (Kong et al.) | **Piano** (primera fase) | Apache-2.0 | Específico de piano, detecta onset/offset/velocidad y pedal. Usa torch, que ya está instalado. Pesos ~170 MB, descarga en el primer uso. |
| Spotify **basic-pitch** | Resto de instrumentos (bajo, guitarra, voz) | Apache-2.0 | Genérico y polifónico, puede correr con ONNX (onnxruntime ya está en el proyecto). |

Se encapsula detrás de una interfaz `transcribe(stem_path) -> list[RawNote]`, para poder cambiar
de motor sin tocar nada más. Corre en un **proceso aparte** con el mismo esquema de timeout,
cancelación y liberación de GPU que `transcribe_worker.py`.

> Licencias y tamaño de pesos de esta tabla son de memoria: se confirman en la Fase 0 leyendo
> el repositorio de cada paquete.
>
> Supuesto a verificar en la Fase 0: que ambos paquetes instalan en Windows con Python 3.12 y las
> fijaciones actuales (`torch<2.7`, `numpy`, `librosa<1`). `uv add --dry-run` y una
> inferencia de 10 s lo resuelven.

### [B] Notación (Python puro, el corazón testeable)

1. **Cuantización contra el beat grid real**: cada pulso de `beats.json` se divide en 4
   (semicorcheas) o en 3 (tresillos); por pulso se elige la subdivisión con menor error, con
   penalización para tresillos (evita tresillos falsos). Rejilla configurable: 1/8, 1/16,
   1/16 + tresillos.
2. **Compás** desde `bars[].beats_per_bar` (4/4, 3/4, cambios de compás).
3. **Separación de manos**: punto de división configurable (por defecto Do4 = MIDI 60) más
   una heurística de continuidad; luego cada nota se puede cambiar de mano a mano.
4. **Deletreo según tonalidad**: en Fa mayor/Re menor se escribe Sib, no La#. Sale de `job.key`.
5. **Acordes**: por cada pulso (o medio compás), vector de 12 clases de altura ponderado por
   duración y velocidad → comparación con plantillas (mayor, menor, 7, maj7, m7, dim, aug,
   sus2, sus4) → nota más grave = bajo → acorde con barra si el bajo no es la fundamental
   (`La/Mi`). Se fusionan acordes iguales consecutivos. Nombres en solfeo (Do, Rem, Sib, La/Mi)
   o en cifrado americano (C, Dm, Bb, A/E), configurable.
6. **Simplificación de voces** (v1): dentro de cada pentagrama, notas con el mismo inicio
   forman un acorde; la duración se recorta hasta el siguiente inicio. Limitación conocida: no
   hay dos voces independientes por pentagrama en v1.
7. **Exportación** a MusicXML (con `music21`, BSD) y a MIDI (`mido`, MIT).

### [C] Render de partitura — se decide en la Fase 0 con criterios medibles

| Criterio (pasa/no pasa) | Verovio (LGPL-3, WASM) | OpenSheetMusicDisplay (BSD-3) |
|---|---|---|
| Sistema doble sol + fa con llave | sí (esperado) | sí (esperado) |
| **El `id` de cada nota llega hasta el SVG** (necesario para editar y seguir) | conserva `xml:id` (esperado) | dudoso |
| Texto libre de acorde arriba («La/Mi», «Rem») | `<harm>` con texto libre | via `<words>` |
| Etiqueta dentro de la cabeza de nota | post-proceso del SVG | post-proceso del SVG |
| Tiempo de render de 100 compases | < 1.5 s | < 1.5 s |

Candidato inicial: **Verovio**, porque conserva los ids y entrega el SVG con clases por
elemento (`.note`, `.notehead`), lo que simplifica edición y seguimiento. Las dos opciones
aceptan `'wasm-unsafe-eval'` o JS puro, así que caben en la CSP actual. Si Verovio falla el
criterio del id, se pasa a OSMD.

### [D] Nombre dentro de la nota (estilo de la foto)

Después de cada render: para cada `.notehead`, se calcula su caja, se oculta el glifo y se
dibuja un rectángulo redondeado negro con el texto blanco (`do`, `re`, `mi`…). Las alteraciones
quedan fuera de la cabeza, como en la foto (`♯do`, `♮do`). Interruptor: solfeo / letras / sin
nombres. Las notas de color: no en v1.

### [E] Seguimiento al reproducir

- Audio: `<audio>` con el MP3 del stem (`/api/jobs/{id}/stems/piano.mp3`, ya existe), más un
  interruptor para escuchar la **mezcla completa**.
- Un bucle `requestAnimationFrame` lee `audio.currentTime` y busca (búsqueda binaria sobre las
  notas ordenadas por `start`) qué notas suenan → les pone la clase `.playing`, mueve una línea
  vertical por el compás actual y hace scroll al sistema actual.
- Velocidad 0.5× / 0.75× / 1× con `preservesPitch` (útil para practicar).
- Clic en una nota → salta el audio a esa nota.

### [F] Edición y limpieza

- **Selección**: clic, Shift+clic, arrastre de rectángulo.
- **Teclado**: `Supr` borrar · `↑/↓` semitono · `Ctrl+↑/↓` octava · `←/→` mover un paso de
  rejilla · `Shift+←/→` duración · `H` cambiar de mano · `Ctrl+Z / Ctrl+Y` deshacer/rehacer.
- **Limpieza masiva** (con vista previa del número de notas afectadas):
  quitar notas con velocidad < X, quitar notas más cortas que Y ms, quitar notas fuera de rango,
  fusionar notas repetidas pegadas.
- **Re-cuantizar** con otra rejilla o punto de división de manos sin perder las ediciones de
  altura/borrado (las ediciones se guardan como operaciones sobre ids).
- **Editar acorde**: clic en el nombre del acorde → campo de texto.
- **Guardar** automático (PATCH con debounce) y **Restaurar** a la transcripción original.

## 5. Fases, cada una con su verificación

Cada fase termina con: (1) una **prueba automática** que corro yo y (2) una **prueba manual de
menos de 1 minuto** para ti. No se avanza a la siguiente fase sin ambas en verde.

### Fase 0 — Spike de factibilidad (decisiones, nada para producción)

| Pregunta | Prueba que la responde |
|---|---|
| ¿Instalan los motores en Windows / Py 3.12? | `uv add --dry-run …` + inferencia sobre 10 s de un stem real |
| ¿Verovio conserva el id de nota hasta el SVG? | HTML de prueba: MusicXML con 3 notas con id → buscar esos ids en el SVG |
| ¿Se puede dibujar la etiqueta dentro de la cabeza? | Captura del HTML de prueba con «do re mi» visibles |
| ¿Cuánto tarda el render de 100 compases? | `performance.now()` alrededor del render |

**Tú verificas:** miras una captura con 3 notas etiquetadas y un acorde arriba. Si se parece a la foto, seguimos.

### Fase 1 — Transcripción (backend)

Entregable: `POST/GET /api/jobs/{id}/score/piano`, `raw_notes.json`, descarga `.mid`.

- **Yo (automático):** fixture sintético generado en el test: una escala de Do + acordes
  Do–Fa–Sol–Do a 90 BPM sintetizados con un timbre tipo piano (numpy) → transcripción →
  `mir_eval` F1 de notas (solo onset, tolerancia 50 ms) **≥ 0.90**. Test de API: 202 → done →
  el JSON cumple el contrato; 404 para un stem que no existe; 409 si ya está corriendo.
- **Tú (manual):** descargas el `.mid` del piano de una canción que conozcas y lo abres en
  cualquier reproductor MIDI (o en MuseScore). Si «suena a la canción», la fase está bien.

### Fase 2 — Notación (Python puro)

Entregable: cuantización, manos, deletreo, acordes, MusicXML.

- **Yo (automático):** tests «golden» de entrada → salida exacta, por ejemplo:
  - Do-Mi-Sol sostenido un compás a 120 BPM → 1 compás 4/4, redondas, acorde «Do».
  - Las mismas notas con ±30 ms de desfase humano → misma salida (prueba la cuantización).
  - Fa mayor → aparece Sib (nunca La#).
  - La-Do#-Mi con Mi en el bajo → «La/Mi».
  - Pulsos con tempo que acelera 90 → 100 BPM → las corcheas siguen cayendo en su lugar.
  - El MusicXML resultante valida contra el XSD de MusicXML 4.0.
- **Tú (manual):** abres el `.musicxml` en MuseScore (gratis) y lo comparas con lo que escuchas.

### Fase 3 — Vista de partitura de solo lectura + seguimiento

Entregable: página `/score/`, botón «Partitura» en la fila del piano, render con claves de sol y
fa, nombres en las notas, acordes arriba, cabecera con BPM / compás / tonalidad, reproducción
con seguimiento.

- **Yo (automático):**
  - `tests/js/score-*.test.mjs` (node): búsqueda tiempo→nota, nombres de notas en solfeo,
    deletreo de acordes.
  - Playwright con el job fixture (sin ML): hay 2 pentagramas por sistema con clave de sol y de
    fa; **número de etiquetas dentro de notas == número de notas del JSON**; los acordes del
    JSON aparecen arriba; al avanzar el tiempo simulado del audio, la nota resaltada es la que
    corresponde.
- **Tú (manual):** abres la **canción de calibración** (ver §6) y compruebas una lista de 5
  cosas que ya sabes de antemano.

### Fase 4 — Edición

Entregable: selección, atajos, limpieza masiva, deshacer/rehacer, guardar/restaurar, edición de acordes.

- **Yo (automático):** un test Playwright por acción: borrar una nota → el JSON tiene una
  menos y la partitura una etiqueta menos → recargar la página → sigue borrada. Igual para
  subir semitono, cambiar de mano, deshacer y restaurar. Tests de API para validaciones
  (notas fuera de rango, ids duplicados, payload enorme → 413).
- **Tú (manual):** borras 3 notas, cambias una de mano, recargas: los cambios siguen ahí;
  pulsas «Restaurar»: vuelve el original.

### Fase 5 — Pulido y otros instrumentos

Exportar PDF (impresión del SVG), basic-pitch para bajo/guitarra/voz (una sola clave según
el rango), opción de dos voces por pentagrama, colores por nota.

## 6. Herramientas para que verificar sea fácil

1. **Canción de calibración.** Un script `scripts/make_score_demo.py` sintetiza un piano con
   contenido conocido (escala de Do, acordes Do–Fa–Sol–Do, una melodía con Sib y un tresillo,
   90 BPM, 4/4) y lo registra como un job más de la biblioteca. Tú sabes exactamente qué debe
   salir, así que la revisión visual es comparar contra una lista escrita, no «a ojo».
2. **Comparación A/B de oído.** En la vista hay un botón «Escuchar MIDI» que reproduce las
   notas extraídas con un sintetizador simple y permite alternar con el stem original en el
   mismo punto. Es la forma más rápida de que una persona detecte una transcripción mala.
3. **Panel de diagnóstico** (plegable): nº de notas, BPM, compás, tonalidad, confianza del
   beat grid, % de notas que se movieron más de 40 ms al cuantizar (si es alto, el beat grid
   está mal, no la transcripción), y avisos en rojo cuando algo sale de rango.
4. **Exportar MusicXML** para contrastar en MuseScore: un segundo motor de partituras
   independiente que sirve de árbitro si la partitura se ve rara.

## 7. Qué queda fuera de la v1

Dos voces independientes por pentagrama, pedal de sustain dibujado, dinámicas (p, f),
articulaciones, edición por arrastre de notas en el pentagrama (en v1 se edita con selección +
teclado), y transcripción de batería.

## 8. Riesgos

| Riesgo | Señal | Qué hacemos |
|---|---|---|
| El stem de piano de Demucs trae ruido de otros instrumentos → notas fantasma | Muchas notas con velocidad baja; el A/B suena «sucio» | Filtro de velocidad mínima por defecto + herramienta de limpieza masiva |
| El beat grid está a medio o doble tempo | El panel de diagnóstico muestra muchas notas desplazadas > 40 ms o BPM al doble | Botones «×2 / ÷2 tempo» que reescriben la cuadrícula para la partitura |
| Conflicto de dependencias (torch / numpy) en Windows | Falla la Fase 0 | Elegir otro motor antes de escribir código de producción |
| `window.open` en la app de escritorio (Tauri) | La pestaña no abre en el escritorio | Navegar en la misma ventana con «Volver» |
| Verovio es LGPL-3 en un proyecto Apache-2.0 | — | Se vendoriza sin modificar como archivo separado; si se prefiere evitar LGPL, OSMD (BSD) |
| Partituras de canciones largas (≥ 300 compases) lentas | Render > 3 s | Render por páginas/sistemas visibles |

## 9. Orden de trabajo propuesto

Fase 0 → (decisión de motor y render) → Fase 1 → Fase 2 → Fase 3 → Fase 4 → Fase 5.
Las Fases 1 y 2 se pueden desarrollar en paralelo, porque se tocan solo a través del formato de
nota de §3.
