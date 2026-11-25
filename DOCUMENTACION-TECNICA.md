# StemDeck (fork con partitura y práctica): documentación técnica

Documento para retomar el proyecto (persona técnica o agente de código). La guía para usuarios
no técnicos está en [GUIA-DE-USO.md](GUIA-DE-USO.md).

## 1. Qué es este repositorio

- **Base:** fork de [stemdeckapp/stemdeck](https://github.com/stemdeckapp/stemdeck) (licencia
  Apache-2.0, ver `LICENSE`). StemDeck separa una canción en pistas (voz, batería, bajo, piano,
  guitarra, otros) con Demucs y ofrece un mezclador web para practicar.
- **Lo agregado en este fork** (rama `feat/partitura-practica`):

| Módulo | Qué hace | Código |
|---|---|---|
| Partitura | Pista → MIDI → partitura editable (gran pentagrama, acordes, nombres de notas), reproducción sincronizada, piano con notas cayendo, práctica por manos, bucle, metrónomo, teclado MIDI | `app/score/`, `app/api/score.py`, `static/score/`, `static/js/score/` |
| 🎷 Saxo | Convierte una parte de la canción en línea de saxo (muestras reales o SWAM), práctica con micrófono | `app/api/sax.py`, `app/score/swam*.py`, `static/sax/`, `static/js/sax/`, `static/audio/sax/` |
| Experimental | Partitura desde PDF (Audiveris) y digitación; separación alternativa BS-RoFormer | `app/experimental/`, `app/api/experimental.py` |
| Arranque en Windows | Lanzadores de doble clic, modo red local con HTTPS y QR | `Iniciar StemDeck dev.cmd`, `Compartir StemDeck en la red.cmd`, `scripts/windows/dev-start.ps1` |

- **Documentación detallada del módulo de partitura** (decisiones, cada ajuste, verificación):
  [`docs/partitura.md`](docs/partitura.md) y [`docs/score-module-plan.md`](docs/score-module-plan.md).
  Es la referencia principal; este archivo resume y dice por dónde empezar.

## 2. Arquitectura

```
Navegador (HTML/JS sin build)  ──HTTP/SSE──►  FastAPI (app/main.py, uvicorn)
  static/index.html  estudio/mezclador          app/api/*        rutas REST
  static/score/      partitura                  app/pipeline/*   descarga, separación, análisis
  static/sax/        saxo                       app/score/*      transcripción y partitura
  static/mobile/     celular/tablet             app/core/*       configuración, ajustes, rutas
                                                       │
                                        subprocesos: Demucs, ffmpeg, workers de transcripción,
                                        SWAM (DawDreamer), Pianoteq, Audiveris, RoFormer
```

- Backend Python (FastAPI). El frontend es estático, sin paso de build; se sirve sin caché.
- `desktop/` es la app de escritorio Tauri del proyecto original; este fork se usa en **modo
  servidor de desarrollo** (no se empaquetó la app de escritorio con los cambios).
- Datos en disco (todo fuera de git, ver `.gitignore`):

| Carpeta / archivo | Contenido |
|---|---|
| `jobs/<id>/` | Cada canción: pistas, análisis, `score/<pista>/notes.json` (ediciones), `meta.json` |
| `models/` | Modelos descargados la primera vez (Demucs, transcripción de piano, etc.) |
| `cache/`, `logs/` | Caché de descargas y registros |
| `settings.json` | Ajustes de la app (dispositivo, almacenamiento, cookies, red) |
| `.run/` | Estado local: `dev-start.log`, `certs/` (certificado autofirmado), `tools/` (SWAM, Audiveris, RoFormer) |
| `youtube-cookies.txt` | Opcional; sesión de YouTube. **Es una credencial: nunca se versiona** |

## 3. Requisitos

| Requisito | Detalle |
|---|---|
| Sistema operativo | Windows 10/11 (donde se desarrolló y probó este fork). El original también corre en macOS y Linux, pero los lanzadores `.cmd`/`.ps1` son solo Windows |
| Python | 3.12 (el `pyproject.toml` acepta 3.10–3.13; el entorno de desarrollo usa 3.12.13) |
| [uv](https://docs.astral.sh/uv/) | Gestor de entorno y dependencias: `winget install astral-sh.uv` |
| ffmpeg | En el `PATH`: `winget install Gyan.FFmpeg` |
| Git for Windows | Para clonar, y su `openssl` se usa para el certificado del modo red local |
| Node.js | Solo para las pruebas de navegador (Playwright). No hace falta para usar la app |
| Disco | Varios GB libres: los modelos se descargan solos la primera vez (Demucs ~170 MB, piano ~170 MB, más otros modelos de análisis); cada canción ocupa decenas de MB |
| GPU NVIDIA | **Opcional.** Ver sección 4 |

## 4. GPU NVIDIA o procesador (CPU)

**La app funciona sin GPU NVIDIA.** Si no hay GPU NVIDIA (o torch no tiene CUDA), todo se procesa
con el procesador (CPU) automáticamente. El resultado es el mismo; **los tiempos de
procesamiento son bastante más largos**.

- El ajuste **Ajustes → dispositivo** viene en `auto`: usa `cuda` si existe, si no `mps` (Mac) y
  si no `cpu` (`app/core/config.py: available_torch_devices`, `app/core/settings.py: get_demucs_device`).
- Si la GPU falla durante la partitura (por ejemplo, sin memoria), se reintenta sola en CPU.
- Al arrancar con el lanzador sin CUDA aparece el aviso amarillo
  «AVISO: este entorno tiene torch SIN CUDA; todo correrá en CPU (más lento)». **En un equipo sin
  NVIDIA es lo esperado: se ignora.** No ejecutes el comando de reinstalación que sugiere.

Tiempos medidos en el equipo de desarrollo (RTX 5070 Laptop; la columna CPU es el procesador de
ese mismo portátil). En otro procesador los tiempos cambian:

| Paso | CPU | GPU NVIDIA |
|---|---|---|
| Separar pistas (Demucs), por cada 60 s de audio | ~20 s | ~1,3 s |
| Extraer MIDI del piano, canción de 9 min | ~6 min | ~20 s |
| Bajo / guitarra / voz / otros (Basic Pitch) | segundos | (corre en CPU igual) |
| Separación RoFormer (experimental), canción de 3 min | no medido; mucho más lento | ~40 s |

Regla práctica en CPU: separar una canción de 4 min tarda de ~1,5 min (procesador del equipo de
desarrollo) a varios minutos en procesadores más modestos, y el piano tarda más o menos lo que
dura la canción.

### Activar la GPU (solo si hay NVIDIA)

`uv.lock` fija torch 2.6 **de CPU**. Para CUDA se instala torch encima, dentro del venv:

- RTX 50xx (Blackwell, compute 12.x) → CUDA 12.8 (comando verificado en el equipo de desarrollo):

  ```powershell
  uv pip install --python .venv/Scripts/python.exe --no-deps torch==2.8.0+cu128 torchaudio==2.8.0+cu128 torchvision==0.23.0+cu128 --index-url https://download.pytorch.org/whl/cu128
  ```

- RTX 20/30/40 → CUDA 12.4 con torch 2.6.0 (la misma elección que hace la app de escritorio,
  `desktop/src-tauri/src/main.rs`; no probado en este fork):

  ```powershell
  uv pip install --python .venv/Scripts/python.exe --no-deps torch==2.6.0+cu124 torchaudio==2.6.0+cu124 torchvision==0.21.0+cu124 --index-url https://download.pytorch.org/whl/cu124
  ```

- Comprobar: `.venv/Scripts/python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"`
  debe mostrar `+cu…` y `True`.

**Trampa crítica:** después de instalar torch con CUDA, **no uses `uv run` ni `uv sync`**:
reinstalan en silencio el torch de CPU del lock. Usa siempre `.venv/Scripts/python.exe` y
`.venv/Scripts/uvicorn.exe` directamente. `npm run test:e2e` arranca su servidor con `uv run` y
también lo revierte (ver sección 7).

## 5. Instalación desde cero (Windows)

```powershell
git clone https://github.com/cristian-data-science/stemdeck_custom.git
```

```powershell
cd stemdeck_custom
```

```powershell
git checkout feat/partitura-practica
```

```powershell
uv sync --extra dev
```

`uv sync --extra dev` crea `.venv` con Python, torch de CPU y las herramientas de prueba. Con eso
la app ya funciona en CPU. Si hay NVIDIA, sigue la sección 4 **después** de este paso.

Opcional (pruebas de navegador): `npm install` y `npx playwright install chromium`.

## 6. Ejecutar

| Forma | Comando / acción | Dirección |
|---|---|---|
| Solo este PC | Doble clic en `Iniciar StemDeck dev.cmd` | http://localhost:8001 |
| Compartir con celular/tablet | Doble clic en `Compartir StemDeck en la red.cmd` | `https://<IP-del-PC>:8443/mobile/` (muestra QR) |
| Manual | `.venv/Scripts/uvicorn.exe app.main:app --host 127.0.0.1 --port 8001 --loop asyncio:ProactorEventLoop --timeout-graceful-shutdown 5` | http://localhost:8001 |

Detalles obligatorios en Windows:

- `--loop asyncio:ProactorEventLoop` es necesario: sin él, todo lo que usa ffmpeg devuelve 500.
- **Sin `--reload`**: con Proactor, la segunda recarga mata el servidor (`WinError 87`). Tras
  cambiar backend, reinicia el servidor. Los cambios de `static/` se ven recargando la página.
- Puerto 8001 = desarrollo. El 8000 lo usa la app StemDeck instalada (si existe).
- Modo red: certificado autofirmado en `.run/certs/` (el navegador de la tablet avisa la primera
  vez: **Avanzado → Continuar**). El firewall de Windows debe permitir Python; regla manual en
  `docs/partitura.md` → «Desde el celular o la tablet».
- Los accesos directos del Escritorio que se mencionan en `docs/partitura.md` («StemDeck dev
  (partitura)») se crearon a mano en el equipo original; en otro equipo se usan los `.cmd`.

## 7. Verificación

Comprobación de un minuto, sin canciones propias:

1. Abre http://localhost:8001/score/ → **Crear canción de calibración**.
2. **Extraer MIDI y generar partitura**.
3. El recuadro de comprobación automática debe salir ✓ (lo normal: 58 de 59 notas; detalle en
   `docs/partitura.md` → «Cómo verificar que está bien»).

Pruebas automáticas (siempre con el Python del venv):

```powershell
.venv/Scripts/python.exe -m pytest tests -q
```

```powershell
node tests/js/score-model.test.mjs
```

```powershell
npm run test:score
```

- `npm run test:score` levanta su propio servidor en el puerto 8124 con `--no-sync` (seguro).
- `npm run test:e2e` (suite del estudio original) usa `uv run` y **revierte torch CUDA**. En un
  equipo con GPU, levanta antes un servidor en 8123 con el Python del venv (ver
  `tests/e2e/serve.sh`) para que Playwright lo reutilice.
- Las pruebas desactivan SWAM (`STEMDECK_SWAM_OFF=1`).

## 8. Componentes opcionales externos

Ninguno es necesario. Si no están, la función correspondiente no aparece o usa una alternativa.

| Componente | Para qué | Licencia | Dónde se busca |
|---|---|---|---|
| Pianoteq | Escuchar la partitura con un piano realista | Comercial | `C:\Program Files\Modartt\Pianoteq*` |
| SWAM Saxophones | Sonido de saxo realista | Comercial | VST2 en `C:\Program Files\Common Files\VST2\SWAM\Saxophones`, alojado con DawDreamer en `.run/tools/swam-venv` |
| Audiveris | Leer partituras desde PDF/imagen | AGPL (programa aparte) | `.run/tools/audiveris`, Program Files o `STEMDECK_AUDIVERIS` |
| BS-RoFormer | Separador alternativo (mejor con teclados) | MIT + modelo ~700 MB | `.run/tools/roformer` o `STEMDECK_ROFORMER` |
| Cookies de YouTube | Solo si YouTube bloquea una descarga | Credencial personal | `youtube-cookies.txt` en la raíz |

Sin SWAM, el saxo usa muestras reales incluidas en el repo (University of Iowa MIS, uso libre).
Pasos de instalación de cada uno: `docs/partitura.md`.

## 9. Configuración

- Ajustes de la app en la interfaz (**Ajustes**) y persistidos en `settings.json`.
- Variables de entorno `STEMDECK_*` (rutas de datos, puertos, modelos, tiempos límite): ver
  `app/core/config.py` y `docs/configuration.md`. Las más útiles: `STEMDECK_JOBS_DIR`,
  `STEMDECK_MODELS_DIR`, `STEMDECK_DEMUCS_DEVICE` (`cuda` / `cpu`), `STEMDECK_HTTPS_PORT`.

## 10. Convenciones para seguir trabajando

- Texto de la interfaz y documentación del módulo en **español neutro (tú)**.
- Commits: `feat(score): Pn · <descripción>` / `fix(score): …` (ver `git log`).
- Ediciones del usuario en la partitura: `jobs/<id>/score/<pista>/notes.json`; `raw.json`
  (salida del modelo) nunca se edita.
- Tras tocar `app/score/` o `static/js/score/`: `tests/test_score_*.py`,
  `node tests/js/score-model.test.mjs` y `npm run test:score`.
- Antes de medir rendimiento, comprueba `torch.__version__` (sección 4).
- Nunca versionar `youtube-cookies.txt`, `settings.json`, `jobs/`, `.run/` (ya están en `.gitignore`).

## 11. Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| «No encuentro …uvicorn.exe» al abrir el `.cmd` | Falta el entorno | `uv sync --extra dev` |
| Aviso «torch SIN CUDA» | Equipo sin NVIDIA, o `uv run`/`uv sync` revirtió torch | Sin NVIDIA: ignorar. Con NVIDIA: reinstalar torch CUDA (sección 4) |
| Exportar MP3/mezclas da error 500 | Servidor sin `ProactorEventLoop` | Arrancar con el `.cmd` o el comando de la sección 6 |
| El servidor muere tras guardar un archivo | Se usó `--reload` | Arrancar sin `--reload` |
| La tablet no conecta | Firewall o red «Pública» en Windows | Regla de firewall en `docs/partitura.md` |
| «Sign in to confirm you're not a bot» | YouTube bloquea la descarga | Cookies de YouTube (`docs/partitura.md`) o usar un archivo de audio |
| La primera extracción de piano tarda | Descarga del modelo (~170 MB) | Esperar; solo pasa una vez |

Más en `docs/troubleshooting.md` (del proyecto original, en inglés).
