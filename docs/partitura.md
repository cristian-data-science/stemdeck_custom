# Partitura: del stem al MIDI y a una partitura editable

<sub>[Plan y decisiones de diseño](score-module-plan.md)</sub>

## Iniciar con doble clic

- **Escritorio → «StemDeck dev (partitura)»**, o doble clic en `Iniciar StemDeck dev.cmd` en la
  carpeta del proyecto: **solo para este PC**. Abre una ventana con el servidor y el navegador
  en http://localhost:8001. Para detenerlo, cierra esa ventana o pulsa Ctrl+C.
- **Escritorio → «StemDeck dev (compartir en red)»**, o `Compartir StemDeck en la red.cmd`:
  lo mismo, y además lo comparte con el celular o la tablet en la misma Wi-Fi (ver «Desde el
  celular o la tablet»). La ventana muestra la dirección (`https://<IP-del-PC>:8443/mobile/`)
  y se abre un código QR para escanearla con la tablet.
- Si el servidor ya estaba corriendo, solo abre el navegador. Si estaba solo para este PC y abres
  «compartir», pregunta antes de reiniciarlo compartido (corta lo que esté sonando o
  procesando); si ya estaba compartido, muestra la dirección y el QR.
- No edites los `.cmd` con una ventana abierta: Windows los lee mientras corren, y el cambio
  puede relanzar el servidor.
- Lo que hace en segundo plano (configurar cookies, abrir el navegador) queda registrado en
  `.run/dev-start.log`.
- Al arrancar avisa si torch perdió la GPU (ver «GPU (NVIDIA)») y si encontró cookies de YouTube.
- La lógica está en `scripts/windows/dev-start.ps1`.

## Canciones desde YouTube

Sí: pegas el link y listo.

1. En la barra de arriba («Busca o suelta un archivo de audio…») pega el link de YouTube.
   También puedes escribir el nombre de la canción para buscarla, pegar un link de una playlist o
   soltar un archivo de audio.
2. Elige qué extraer (**Todo**, Voces, Batería…) y pulsa **Extraer stems**.
3. Cuando termine, en la fila del Piano pulsa **𝄞** para la partitura.

### Cookies de YouTube (solo si YouTube te bloquea)

Si una descarga falla con «Sign in to confirm you're not a bot» (o «HTTP Error 429»), YouTube
está pidiendo una sesión iniciada. StemDeck usa cookies **solo** en ese caso: primero intenta
sin ellas, porque con cookies yt-dlp descarta los clientes que hoy funcionan sin sesión.

1. En tu navegador, con la sesión de YouTube iniciada, exporta las cookies de `youtube.com` en
   formato **Netscape (cookies.txt)** con una extensión de exportación, por ejemplo
   «Get cookies.txt LOCALLY». Recomendación habitual de yt-dlp: hazlo desde una ventana
   privada en la que inicias sesión y que luego cierras, para que YouTube no rote esas cookies
   mientras sigues navegando.
2. Guarda el archivo como **`youtube-cookies.txt`** en la carpeta del proyecto
   (`C:\Users\patag\git_provisorio\stemDeck_custom`).
3. Abre StemDeck con el acceso directo. El lanzador lo configura solo
   («Cookies de YouTube: se usarán desde youtube-cookies.txt»). Si borras el archivo, la
   próxima vez lo desconfigura.

También puedes hacerlo a mano en **Ajustes → Cookies de YouTube**, pegando la ruta del archivo.

Ese archivo **es tu sesión de YouTube**: quien lo tenga puede usar tu cuenta. Está en
`.gitignore` (`youtube-cookies.txt` y `*cookies*.txt`), así que no se sube al repo. No lo
compartas y, si lo prefieres, usa una cuenta secundaria. Cuando caduque, vuelve a exportarlo.

## Cómo se usa

1. Separa una canción como siempre.
2. En el mezclador, en la fila del **Piano**, pulsa **𝄞**. Se abre la vista de partitura en
   otra pestaña. Bajo, guitarra, voz y otros tienen el mismo botón.
   También puedes ir directo a `http://localhost:8001/score/` y elegir la canción.
3. Pulsa **Extraer MIDI y generar partitura**. La primera vez que extraes un piano se descarga
   el modelo (~170 MB). En CPU, el piano tarda aproximadamente lo que dura la canción. Los
   demás stems tardan unos segundos.
4. Ya tienes:
   - **Sistema doble** con clave de sol y clave de fa.
   - **Nombre dentro de cada nota** (do, re, mi… o C, D, E).
   - **Acorde principal arriba** del pentagrama (Fa, Rem, La/Mi, Si♭…).
   - **BPM, compás y tonalidad** en la cabecera. Salen del beat grid que StemDeck ya calculó
     al separar.
   - **▶ Reproducir**: la nota que suena se ilumina en naranja, el cursor avanza al ritmo del
     audio y la partitura se desplaza sola.
   - Los nombres dentro de las notas vienen **ocultos**. Para verlos, cambia **Nombres** (arriba,
     en el panel de ajustes) a «do re mi» o «C D E».

### Piano con notas cayendo y saltos

- **🎹 Piano** (junto a ▶) cambia la partitura por un piano con las notas cayendo, en el mismo
  punto de la canción; **𝄞 Partitura** vuelve. Es el mismo reproductor: suena igual (Escuchar,
  Pianoteq, pedal, velocidad) y cada nota cae hasta su tecla. Cada barra dura lo que la figura
  en la partitura, no lo que sigue resonando (eso ya lo dice el sonido), y termina un instante
  antes de que se vuelva a tocar la misma tecla. Con la duración resonante, en Porz Goret el
  65 % de las notas repetidas se pegaban en una sola columna y quedaban 5–7 teclas encendidas a
  la vez en un arpegio; así quedan unas 3. Se ven 4 s de canción por delante; a menor
  velocidad, caen más lento.
- **Estilo 3D** (por defecto), al estilo See Music: las notas llegan desde lejos en perspectiva
  (pequeñas y lentas al fondo, grandes y rápidas al llegar), con volumen y brillo; al tocar
  cada nota saltan chispas y la tecla se hunde iluminada con su color. Al fondo la perspectiva
  comprime el tiempo unas 5 veces y las notas cortas quedaban como rayitas apiladas: ahora entran
  tenues (35 % en el extremo, `depthFade`) y se encienden al pasar la mitad del camino, así las
  que vas a tocar destacan. **Plano**: las barras
  simples de antes, más livianas para equipos lentos. Tocar y arrastrar notas funciona igual
  en los dos (en 3D el arrastre sigue la perspectiva).
- Opciones del piano (se guardan en este navegador): **Teclado** «Rango de la canción» (de la
  octava más grave a la más aguda que usa la pieza, completas) o «88 teclas»; cada do lleva su
  octava (C4 es el do central). **Colores** «Por mano» (por defecto: cada mano con su color) o «Un color», con la mano
  de cada nota como en la partitura; con «Por mano», clic en el cuadrado de color de «mano
  derecha» o «mano izquierda» para elegir otro (↺ vuelve a los de siempre). **Nombres** «C D E»
  (por defecto), «do re mi» o sin nombres.
- **🖌 Corregir manos** (vista piano): elige **Derecha**, **Izquierda** o **Auto** y toca o
  arrastra sobre las notas que caen; se pintan al momento y se guardan al soltar (también
  mientras suena: en este modo arrastrar no mueve la canción). Un punto blanco marca las notas
  cuya mano pusiste tú. **Auto** quita tu corrección y la mano vuelve a decidirla el programa.
  Esc o el mismo botón para terminar. En la partitura (o con notas elegidas en el piano), la
  barra flotante tiene **Mano: Derecha / Izquierda / Auto**, y **H** sigue cambiando de mano.
- **−30 −10 −5 +5 +10 +30**: saltos rápidos en segundos, en las dos vistas.
- **Cambiar «Escuchar» no vuelve al principio**: stem, MIDI, Stem + MIDI, canción completa y
  Pianoteq siguen en el mismo segundo de la canción. Antes, al llegar el audio de Pianoteq (y al
  cambiar dos veces antes de que cargara el primero, fácil por Wi-Fi) volvía a 0:00.
- **Lo borrado no suena en el MIDI.** El MIDI de la página toma cada edición al instante, sin
  esperar a que el servidor la guarde. El audio de Pianoteq es un archivo ya generado:
  - **Al borrar notas** escuchando Pianoteq, en cualquier vista, **sigue sonando la pista
    actual** (la nota borrada se oye unos segundos más, sin perder el ritmo de las siguientes) y
    un aviso flotante abajo a la derecha dice «⏳ Pianoteq: quitando 1 nota… (sigue sonando la
    pista actual)». Cuando el render nuevo está listo lo reemplaza en el mismo punto y el aviso
    dice «nota quitada ✓» (se va solo a los 6 s). Antes se cortaba Pianoteq y sonaba el MIDI.
  - **Cualquier otra edición** (subir, mover, alargar, agregar, deshacer un borrado): mientras se
    genera de nuevo, suena el MIDI con la edición aplicada y vuelve a Pianoteq en el mismo punto.
  Con «Stem» o «Canción completa» la nota sigue sonando porque es la grabación original.
- **🗑 Borradas (N)**, en la barra de reproducción (las dos vistas): las notas borradas, la más
  reciente primero, con su nombre, su momento y hace cuánto se borraron; **Restaurar** devuelve
  una y **Restaurar todas**, todas. El historial lo guarda el servidor junto con las notas
  (`notes.json`), así que sirve igual desde la tablet o el PC y después de recargar. Deshacer,
  restaurar o «Restaurar original» sacan del historial las notas que vuelven; volver a extraer
  lo vacía.
- **Borrar y correr notas, también con el dedo.** Al tocar o hacer clic en una nota (en las dos
  vistas; en la de piano, sonando o en pausa) aparece una barra flotante con **🗑 Borrar** y ✕
  (en el PC también sirven Supr y Esc). Arrastrar la nota la corre:
  - en la partitura, a los lados = en el tiempo, de a un paso de la rejilla; arriba/abajo = por
    la escala de la tonalidad, nota a nota, como sube en el pentagrama;
  - en el piano, a los lados = de tecla en tecla (semitonos); arriba/abajo = en el tiempo, de a
    un paso de la rejilla (hacia abajo, antes).

  Mientras arrastras se ve dónde quedará; al soltar se guarda, y Deshacer lo revierte. Si había
  varias seleccionadas, se mueven juntas.
- **Unir dos notas en una** (vista de piano). Cuando la transcripción partió una nota larga en
  dos seguidas en la misma tecla: pon el puntero en el **borde de abajo** de la segunda barra
  (su inicio); el cursor cambia a ↕. Arrástralo hacia abajo: mientras no llega a la nota
  anterior solo corre el inicio (de a un paso de la rejilla); al llegar se marcan las dos y el
  estado dice «Suelta para unir». Al soltar queda una sola nota, desde el inicio de la primera
  hasta el final de la segunda, en la vista de piano y en la partitura. Un clic en el borde, o
  arrastrarlo hacia arriba, nunca une. Deshacer las vuelve a separar.

  La nota unida queda marcada como **sostenida a mano** (`held` en `notes.json`): se dibuja, se
  ilumina y suena entera aunque la misma mano toque otras notas mientras tanto. Sin esa marca,
  la vista de piano la acortaba al volver la respuesta del servidor (unos 2 s después), porque la
  partitura tiene una sola voz por pentagrama y corta cada nota donde su mano toca la siguiente.
  La nota absorbida no aparece en «Borradas»: no se borró, se unió. Alargar una nota con
  Shift+→ también la marca así. En la partitura, la cabeza de la nota absorbida desaparece,
  pero la figura sigue cortada donde la mano toca la siguiente: con una sola voz no se puede
  dibujar una nota sostenida bajo otras.
- **Añadir notas: botón «＋ Nota»** (o la tecla N; Esc o N para terminar). Está en la barra de
  edición de la partitura y en la del piano. Mientras está activo, cada toque añade una nota:
  - en el piano, en la columna de su tecla y a la altura del momento en que suena. Si la sueltas
    sin moverla, dura un pulso; si la arrastras hacia arriba, dura hasta donde la sueltes;
  - en la partitura, en su línea o espacio y en su lugar del compás. Toma la alteración de la
    armadura (en Fa mayor, la línea del medio es Si♭) y la mano del pentagrama donde tocaste.
    Dura un pulso; se alarga con Shift+→.

  Si tocas a menos de 80 ms del inicio de otra nota (en la partitura, a menos de medio paso de la
  rejilla), la nueva empieza a la vez y queda en el mismo acorde. La nota nueva queda
  seleccionada, así que 🗑 la quita y ↑/↓ cambian su altura. Deshacer la quita. Las notas que
  añades no van a «Borradas» si las quitas, y «Restaurar original» las descarta.
- **Sincronía** (ms, se guarda en cada equipo): atrasa solo el dibujo (notas que caen, teclas,
  cursor, resaltado) respecto del audio. El navegador descuenta la latencia de salida que el
  sistema le informa, pero en una tablet, y más con parlantes o audífonos Bluetooth, parte no
  se informa y la nota se ve antes de oírse. Súbelo hasta que la tecla se encienda justo
  cuando suena (doble clic vuelve a 0). El archivo de Pianoteq no trae retraso: decodificado
  por Chrome, el MP3 calza con el WAV a 0 ms y la primera nota suena 1.6 ms después de su
  lugar en el MIDI.
- Al saltar o arrastrar la barra de tiempo por Wi-Fi, el audio se detiene un instante a cargar
  ese tramo. El dibujo y el sintetizador esperan con él. Antes seguían avanzando y quedaban
  hasta 95 ms por delante; ahora quedan a 1 ms (red lenta simulada).

### Velocidad y pedal

- **Velocidad**: cuatro botones fijos, **25 %, 50 %, 70 % y 100 %** (antes un deslizador de 25 a
  125 %). Reproduce más lento sin cambiar la afinación; el audio, el MIDI, Pianoteq y el cursor
  van juntos. Queda guardada en este navegador (una velocidad guardada antes, como 85 %, se
  abre en la más cercana). Con Pianoteq, cada botón muestra **✓** cuando esa velocidad ya está
  generada para las dos manos, la derecha y la izquierda.
- **Pedal** (de 0 % a 100 %): cuánto sostiene el pedal al reproducir el MIDI o Pianoteq. La
  partitura no cambia; solo cuánto suena cada nota. El modelo de piano oye el pedal del pianista
  aparte de las teclas, así que:
  - con 0 % cada nota suena lo que el pianista sostuvo la tecla;
  - con 100 % cada nota sigue sonando hasta que el pianista levanta el pedal;
  - con 40 % recorre el 40 % de ese camino.

  Una tecla que se vuelve a tocar corta su propia nota. Si la transcripción no trae pedal
  (Basic Pitch, otros stems), se cambia el pedal en cada acorde. Se guarda con la partitura.
  No se manda como pedal MIDI (CC64), a propósito: el medio pedal de Pianoteq no es proporcional
  (en una prueba, hasta ~30 % no hacía nada, a 50 % apagaba a medias y desde ~75 % sostenía
  todo), y así el sintetizador de la página y Pianoteq suenan igual.

### Escuchar con Pianoteq

Si Pianoteq está instalado en este equipo, **Escuchar** ofrece **Pianoteq**. La partitura, tal
como está, se renderiza con Pianoteq en el servidor (sin abrir su ventana) y suena en lugar
del stem, con el cursor sincronizado (en la calibración, los ataques caen a ~20 ms de las
notas). **Piano** elige el preset **de esa canción**: se guarda con la canción en el servidor
(`meta.json`), y al volver a abrirla suena con ese piano, aunque entretanto hayas usado otro
en otra canción (antes se usaba el último elegido en cualquier canción y se volvía a generar).
Los pianos que ya están generados para las notas actuales aparecen con **✓** y suenan al
instante. Una canción que nunca sonó con Pianoteq empieza con el último piano que elegiste.

- **Solo cuenta lo que se oye:** el archivo que recibe Pianoteq lleva las notas en segundos, sin
  el mapa de tempo de la partitura; cambiar **Compás** o las barras ya no regenera el audio.
  Los renders anteriores se reutilizan con su nombre nuevo (no se vuelven a generar).
- **Pianoteq a mi velocidad** (barra de práctica): con velocidad bajo 100 %, se genera el audio
  ya a esa velocidad y suena limpio, sin el estirado del navegador. Mientras tanto suena el
  render anterior.
- **Manos → Toco la derecha / izquierda:** Pianoteq (y el MIDI) tocan solo la otra mano.
- Un preset que guardes en la ventana de Pianoteq aparece en la lista en menos de un minuto,
  sin reiniciar; si lo vuelves a guardar con el mismo nombre, se genera de nuevo.

- **Siempre se genera, sin pedirlo:** apenas termina la extracción de la partitura, el servidor
  empieza el render con el último piano elegido para esa partitura (o el de siempre), en
  paralelo: la partitura se abre de inmediato y Pianoteq sigue detrás. Medido con «1st» (3:45):
  listo ~47 s después de aparecer la partitura (11 s en preparar las notas, 36 s de Pianoteq).
  Al abrir una partitura que aún no lo tenía, empieza en ese momento. Al elegir «Pianoteq» ya
  está listo (sale de la caché, `jobs/<id>/score/<stem>/pianoteq/`, se guardan los últimos 8).
  Para apagarlo: `STEMDECK_PIANOTEQ_AUTO=0`.
- **Cada velocidad y cada mano, también sin pedirlo:** después del render principal se
  generan en segundo plano, en este orden, las 12 variantes: a **100 %, 70 %, 50 % y 25 %**, y en
  cada velocidad las dos manos, la derecha sola y la izquierda sola. Así elegir una velocidad o
  **🔇 Silenciar** una mano suena con Pianoteq al instante, sin pasar al MIDI. Se hacen de a una
  (Pianoteq usa toda la CPU; en paralelo no terminaría antes) y con **prioridad baja** del
  sistema, para que la página, el audio y una separación sigan fluidos. El render que pide la
  página va siempre primero (el de fondo se corta y se retoma después). Tras una edición se
  vuelven a generar las 12 de las notas nuevas (las de notas viejas se descartan).
- **Toda la biblioteca:** al arrancar el servidor (15 s después) se revisan todas las
  partituras y se genera lo que falte, por velocidad: primero todas las canciones a 100 % (la
  última trabajada primero), después todas a 70 %, 50 % y 25 %. Lo ya generado se salta al
  instante. `GET /api/score/pianoteq/queue` dice qué se está generando y cuántos faltan.
- **Cuánto ocupa:** el juego completo de una canción es ~25 veces su duración en audio (las
  lentas son más largas: a 25 % dura 4 veces más). Para 31 partituras (98 min de música):
  ~2 480 min de audio, ~7,5 GB en FLAC y unas 6-7 h de Pianoteq la primera vez. Se guardan
  hasta 16 renders por partitura (un juego son 12).
- Al editar, la versión anterior sigue sonando y, un segundo después del último cambio, se
  genera una nueva que la reemplaza sin cortar la reproducción (también si estás escuchando
  otra cosa: Pianoteq queda al día). Un render de notas que ya volviste a editar se descarta
  (o se corta si ya había empezado): antes cada edición dejaba uno en cola, se generaban de a
  uno (~30 s cada uno) y el que esperabas llegaba minutos tarde, detrás de versiones viejas.
- Una canción cuyo primer pulso llega después de 16,7 s no se podía exportar a MIDI (ni a
  Pianoteq); ahora la introducción usa varias negras de entrada.
- Los instrumentos que no tengas con licencia suenan como en la demo de Pianoteq (con
  algunas notas mudas). Elige uno de los tuyos.
- Se busca en `C:\Program Files\Modartt\Pianoteq*`. Para usar otro ejecutable, define
  `STEMDECK_PIANOTEQ` con su ruta.

### Practicar: bucle, manos, metrónomo y teclado MIDI

La barra **Práctica** (debajo de la de reproducción):

| Control | Qué hace |
|---|---|
| **Bucle → A / B** | El compás que suena ahora pasa a ser el inicio (A) o el final (B) del bucle. Con notas elegidas, **🔁** (o la tecla **L**) repite sus compases. Al pasar B vuelve a A. |
| **Subir velocidad cada 1 / 2 / 3 vueltas** | Al completar esas vueltas pasa a la velocidad siguiente: 25 → 50 → 70 → 100 %. |
| **Manos** | «Toco la derecha»: el MIDI y Pianoteq tocan solo la izquierda, y en el piano la izquierda se ve tenue (al revés con «Toco la izquierda»). Con «Stem» o «Canción completa» no se puede separar una mano: lo avisa. |
| **Metrónomo** | Un clic en cada pulso de los compases de la partitura, más agudo en el primero. |
| **Cuenta** | 1 o 2 compases de clics antes de empezar al pulsar ▶ (y al volver al inicio del bucle). |
| **🎹 Teclado MIDI** | Un teclado conectado por USB (Chrome o Edge). **Libre**: tus teclas se ven en el piano, en verde si tocaste una nota de la canción a tiempo y en rojo si no; se cuentan los aciertos. **Esperarme**: la canción se detiene en cada acorde (de la mano que practicas) hasta que lo tocas. **Sonar mis teclas**, si tu teclado no suena solo. |

En el piano con notas cayendo hay una línea en cada pulso y una más marcada en cada compás,
con su número; el bucle se ve como una franja entre A y B. **Notas a la vista** (1-20 s,
deslizador en la barra del piano) es cuánto de la canción se ve antes de llegar a las teclas: a
la derecha las notas caen más lento y más juntas (ves venir más), a la izquierda más rápido y
separadas. También **Ctrl + rueda** (o pellizcar el trackpad) sobre el piano, **pellizcar con
dos dedos** en la tablet, y las teclas **+** / **−**; mientras cambia, arriba del piano dice
«Notas a la vista: 8 s». Doble clic en el deslizador: 4 s. Se recuerda en el equipo.

**Mover la canción con el dedo o el ratón (piano):** arrastra el carril hacia abajo (las notas
bajan: adelanta) o hacia arriba (retrocede); el momento que tenías bajo el dedo sigue bajo el
dedo. Sonando, cualquier arrastre mueve la canción (y sigue sonando al soltar; las notas no se
editan); en pausa, arrastrar sobre una nota la sigue editando como antes y en el espacio vacío
mueve la canción. Un toque sin arrastrar selecciona la nota, como siempre; si la canción está
sonando, además la **pausa** ahí, para editar esa nota (▶ o Espacio para seguir). **Doble clic o
doble toque en el fondo vacío** pausa la canción; otro doble clic o doble toque la reproduce.

Los avisos que van y vienen («Mano derecha: 1 nota · guardando…», «Pianoteq: generando…»)
flotan abajo a la derecha: antes, en su barra, la alargaban unos segundos, la página ganaba una
barra de desplazamiento y la vista del piano se redibujaba más chica.

**Arriba a la derecha:** **▤ Ocultar paneles** (tecla **P**) deja una sola línea sobre la vista:
▶/❚❚, la canción, el tiempo, el compás, la velocidad, el bucle y qué suena; **▤ Paneles** los
vuelve a mostrar (se recuerda en el equipo). **⛶ Pantalla completa** (tecla **F**): en el piano,
con las proporciones de un video de notas cayendo (estilo **Video**: carril plano, notas del ancho
de su tecla, una tecla blanca 5,5 veces más larga que ancha, el teclado entre el 12 % y el 22 %
de la pantalla —88 teclas en 1920×1080: teclas de 37 × 203 px—, la franja roja donde caen las
notas). Al salir vuelve el estilo que tenías. **Video** también se puede elegir en **Estilo** sin
pantalla completa. En un iPhone (sin pantalla completa del navegador) se usa la misma vista de
borde a borde dentro de la página.

**⚙ Menú rápido** (con los paneles ocultos o en pantalla completa): un engranaje arriba a la
derecha, medio transparente mientras no tocas nada y de color en cuanto mueves el mouse o tocas
la pantalla (vuelve a medio transparente a los 2,5 s). Al tocarlo se despliega hacia abajo, un
botón bajo otro, y se cierra solo a los 6 s sin tocarlo (o al tocar fuera):

| Botón | Qué hace |
|---|---|
| ✏️ Editar notas | Tocar una nota la elige y muestra la barra para cambiarla (mano, dedo, borrar), también con los paneles ocultos |
| ＋ Agregar nota | Como **＋ Nota** (N) |
| ↶ Deshacer | La última edición |
| Velocidad 25 · 50 · 70 · 100 | Con ✓ las que Pianoteq ya tiene listas |
| Silenciar Izquierda · Derecha | Como **🔇 Silenciar** |
| 🖐 Activar dedos / Ver dedos | Activa los dedos en la canción, o muestra u oculta sus números |
| Notas a la vista − · ＋ | Menos o más segundos en pantalla |
| ▤ Mostrar paneles · ⛶ Pantalla completa | Volver a los paneles, entrar o salir de pantalla completa |

## Almacenamiento (app principal → Ajustes → Almacenamiento)

Dice dónde están las canciones (la carpeta), cuánto ocupa StemDeck y cuánto queda libre en el
disco, y cuánto ocupa cada cosa, en total y canción por canción (la que más ocupa primero; al
abrir una se ve su carpeta y su detalle):

| Tipo | Qué es | ¿Se puede limpiar? |
|---|---|---|
| Stems | las pistas separadas | No (para eso, la Papelera) |
| Partituras | notas, ediciones, historial | No |
| Copias de la partitura | la canción rearmada desde los stems y copias FLAC para reproducir | Sí, se vuelven a hacer al abrirla |
| Pianoteq 100 % | ambas manos a velocidad normal | Sí («Todo Pianoteq») |
| Pianoteq cada mano | derecha sola e izquierda sola a 100 % | Sí |
| Pianoteq lentos | 70, 50 y 25 % (lo que más ocupa) | Sí |
| Pianoteq versiones anteriores | de notas que editaste después, u otro piano | Sí |
| Video, archivos subidos | el video de notas cayendo, el archivo original de una subida | No |

Los botones de limpiar (de todas las canciones o de una) dicen cuánto liberan; el primer clic
pregunta («¿Borrar 4,1 GB? Clic de nuevo») y el segundo borra. Lo de Pianoteq se vuelve a
generar cuando lo pides (al elegir esa velocidad o mano) o en segundo plano según **Pianoteq en
segundo plano**: *Todas las velocidades y cada mano* (por defecto), *100 % y cada mano*, *Solo
100 %* o *Nada*. Si borras los lentos con «Todas las velocidades» elegido, vuelven a generarse:
lo avisa. `GET /api/storage`, `POST /api/storage/clean`, `PUT /api/storage/background`.

**Cada canción recuerda en este navegador** dónde la dejaste, qué estabas escuchando, la
velocidad, el bucle y la mano que practicas. El **𝄞** del mezclador (escritorio y celular) abre
la partitura **en el momento en que iba la canción** (`?t=`) y pausa el mezclador.

El tiempo practicado, la mejor velocidad de un bucle completo y los aciertos con el teclado se
guardan con la partitura; la lista de `/score/` los muestra junto a «partitura», «editada» y
«Pianoteq ✓».

**Lista automática:** al terminar de separar una canción con piano (presencia ≥ 25 %), se
extrae su partitura en la cola y después se genera Pianoteq, sin pedirlo. Para apagarlo:
`STEMDECK_SCORE_AUTO=0`.

## Editar y limpiar (se guarda solo)

Cada cambio se guarda en el servidor al instante, en
`jobs/<id>/score/<stem>/notes.json`, y sigue ahí al recargar o reiniciar.
**Restaurar original** vuelve a lo que oyó el modelo, que se guarda aparte en `raw.json`.

**Deshacer en la tablet (o en la vista piano):** **↶** y **↷** están en la barra de reproducción
(las dos vistas; ↶ también en la línea de «Ocultar paneles»). **Toque con dos dedos** sobre el
piano: deshacer; **con tres dedos**: rehacer. Un aviso dice qué se deshizo («↶ Deshecho: Movida»).

**🕘 Historial** (barra de reproducción): cada edición guardada, la más reciente primero, con su
nombre, qué notas cambió («Do4 → Re4 en 0:12», «−Fa4 en 0:03», «Sol4 0:10 → 0:11») y hace
cuánto. Se guarda en el servidor (`history.jsonl`, las últimas 300), así que sigue ahí al
recargar o desde otro equipo, a diferencia de Ctrl+Z, que vive en la página. **↶ Volver a antes
de esta** deshace esa edición y las posteriores (pregunta antes), y queda como una edición más:
se puede volver. **Volver al original (sin ediciones)** deja la partitura como salió de la
transcripción; también queda en el historial y se puede deshacer. «🗑 Borradas» sigue listando
solo notas borradas; una nota movida sin querer se busca en el historial. Volver a extraer el
MIDI empieza un historial nuevo.

| Acción | Cómo |
|---|---|
| Seleccionar | clic · Shift/Ctrl+clic para añadir · arrastrar sobre el papel para un área · Ctrl+A todo |
| Borrar | Supr |
| Subir/bajar semitono | ↑ / ↓ |
| Subir/bajar octava | Ctrl+↑ / Ctrl+↓ |
| Mover un paso de la rejilla | ← / → |
| Alargar/acortar | Shift+→ / Shift+← |
| Cambiar de clave (mano) | H, o **Derecha / Izquierda / Auto** en la barra flotante |
| Corregir manos pintando | vista piano → **🖌 Corregir manos**, y toca o arrastra sobre las notas |
| Poner o cambiar un acorde | clic en el acorde, o A con una nota seleccionada |
| Añadir notas | **＋ Nota** o N, y toca donde va cada una (Esc o N para terminar) |
| Unir dos notas seguidas en una tecla | en el piano, arrastra hacia abajo el borde inferior de la segunda hasta la primera |
| Deshacer / rehacer | Ctrl+Z / Ctrl+Y, ↶ / ↷, o toque con dos / tres dedos sobre el piano (cada paso también se guarda) |
| Historial de ediciones | **🕘 Historial**: volver a antes de cualquier edición, o al original |
| Escuchar desde una nota | doble clic |
| Quitar notas fantasma en bloque | **Limpiar…**: velocidad mínima y duración mínima, con vista previa en rojo |
| Fusionar notas repetidas | **Limpiar…** → **Unir notas repetidas** |

### Qué decide la app sola (y cómo cambiarlo)

Todo esto es determinista y se aplica igual a cualquier canción. Se midió con una canción con
banda (9 min), una grabación de piano solo (3:45) y la canción de calibración:

- **Desde qué audio se transcribe el piano.** Si no hay voz, batería ni bajo (presencia menor a
  10), la canción es piano solo y se transcribe el **audio original**. Demucs reparte un piano
  solo entre los stems «piano» y «other», y en la grabación de prueba el stem coincidió apenas
  en F1 0.70 con el original. Con banda se usa el stem. Puedes elegirlo al extraer, o en
  «Diagnóstico → Volver a extraer desde».
- **Notas fantasma.** Al transcribir, cada nota se compara con el audio del que salió
  (`app/score/ghosts.py`): si justo en su inicio no sube la energía de sus parciales (la nota, su
  octava y su duodécima), no hubo ataque. Un **re-ataque sin ataque** de una tecla que ya sonaba
  (el modelo repite bajos y voces internas sostenidas cuando suena otra tecla) se une a la nota
  que repite; una **nota suelta y suave** (velocidad < 45) sin ataque se quita. Si se transcribió
  desde el stem, además se quita la nota suave (< 60) que suena 15 dB más fuerte en el stem de
  la **voz** que en el del piano (filtración de la voz). No se compara con la guitarra ni con
  «other», porque Demucs a veces deja ahí parte de un teclado. Todas quedan en **«Notas
  borradas»** («sin ataque en el audio» o «se oye en la voz»), así que cualquiera se restaura
  con un clic. «Diagnóstico» dice cuántas fueron. Un re-ataque real de una tecla que suena hace
  una caída (el apagador) y vuelve a subir: el pulso de Si3 en corcheas de «Cry» sube de 4,7 a
  12 dB desde esa caída y se conserva. Medido: se quitaron el 8-10 % de las notas en «Cry»
  (piano solo transcrito del original), el 1,4 % en Comptine y el 2,9 % en Valse d'Amélie (que
  son grabaciones limpias), y el 20 % en «Barbarossa - Stones» (desde el stem, con voz: 114 sin
  ataque y 156 de la voz).
- **El pulso.** Se usa el de la canción, salvo que no sea fiable: viene del detector de
  respaldo, no trae barras o salió de un stem en silencio. En ese caso se toma el que se detecta
  sobre la canción completa (aunque se transcriba un stem: un piano que toca solo en algunos
  pasajes no marca el pulso; en «Saturday Night» el stem daba un pulso irregular y las notas
  71 BPM, y la mezcla 105 BPM estables). En el piano solo, las notas lejos de la rejilla bajaron
  de 20 % a 4 %, y el compás salió 3/4. Selector **Pulso**: Auto / De la canción / Del audio.
- **La afinación.** Antes de transcribir se mide a cuántos cents de La 440 está el audio. Las
  versiones «slowed» o «sped up» cambian la velocidad de la grabación y con ella la afinación:
  «Saturday Night (slowed)» está +38 cents, cada nota casi a medio camino de dos teclas, y el
  modelo leía Sol5 como Sol♯5 o como Fa5 + Sol♯5 (encontraba el 60 % de las notas fuertes del
  stem). Si el desvío pasa de 15 cents, el audio se transcribe reproducido un poco más lento o
  más rápido (a La 440) y los tiempos se devuelven al reloj de la canción: ahí encontró el 98 %,
  con los acordes. Las piezas afinadas miden entre −2 y +6 cents y no se tocan. El valor sale en
  «Diagnóstico → Afinación del audio». Una partitura extraída antes de este cambio dice «–»:
  «Volver a extraer» la mide y la corrige. La partitura y las exportaciones quedan en La 440,
  pero al reproducir, el MIDI de la página (desafinado con `detune`) y Pianoteq (con un pitch
  bend, que respeta con rango ±2 semitonos) suenan a la afinación de la canción. En «Saturday
  Night» midieron +38.2 y +38.5 cents contra +38.1 del stem, así que «Stem + MIDI» suena afinado.
- **Las manos.** «Manos: Auto» (lo normal en el piano) usa una red neuronal pequeña
  (`app/score/hands.py`, GRU bidireccional, el método de Hadjakos et al. 2019) entrenada con
  **hannds**: 122 piezas que pianistas tocaron con cada mano en un teclado distinto, así que se
  sabe qué mano tocó cada nota. Lee el pasaje completo hacia adelante y hacia atrás (altura,
  distancia a la nota anterior y siguiente, duración, fuerza y lugar en el acorde). Dentro de un
  acorde la izquierda siempre toma las notas de abajo. Medido con
  `scripts/score/hands_benchmark.py` en las canciones cuyas manos se conocen (videos con cada
  mano en su color y el nocturno de Chopin desde su partitura): **96,0 %** de notas en la mano
  correcta, contra 88,7 % de las reglas anteriores y 87,0 % de un corte fijo en Do4. En 12
  piezas de hannds que no vio al entrenar, 97,0 % (el corte fijo, 78,1 %). Además, una mano no
  puede sostener teclas separadas más de una novena: una nota dudosa va a la mano que la
  alcanza. Ningún método llega al 100 % solo con altura y tiempo: una nota intermedia (un Re♯4
  entre Sol♯3 y una melodía en Fa4) puede ser de cualquiera de las dos manos; la literatura
  publica 92-95 %.
  **Corregir:** cada mano que pones (barra flotante, H o 🖌 Corregir manos) manda siempre, y
  además el programa la usa de pista: vuelve a decidir las notas que no tocaste y lleva con ella
  la **misma tecla** en ±4 s. Simulando a alguien que corrige la primera nota equivocada hasta
  que no queda ninguna: 267 errores se arreglaron con 201 correcciones (sin la propagación,
  unas 250). Con el pincel, una sola pasada corrige varias notas a la vez. Tras guardar, el aviso dice cuántas notas de alrededor cambió el programa. **Auto** en
  la barra o en el pincel devuelve la nota al programa. En las canciones de video, todas las
  notas vienen con la mano del video y no se recalculan. «Corte fijo» manda todo lo que está
  desde «Mano derecha desde» hacia arriba a clave de sol; en Auto ese punto solo desempata las
  notas que la red deja dudosas (una melodía sola alrededor del Do central va a la derecha).
  Cambio de criterio: en figuras ambiguas la red puede repartir distinto que las reglas de
  antes; por ejemplo, en Comptine pasa a la derecha unos 60 Re4/Mi4 de la parte alta del
  arpegio que antes quedaban en la izquierda. Ahí se corrige una nota por tecla y las vecinas la
  siguen. Reentrenar: `scripts/score/train_hands.py --hannds <carpeta data-hannds>`.
- **El pulso desde las notas.** Cuando el pulso de la canción no es fiable, se calcula otro
  sobre los ataques de las notas transcritas y gana el más regular. En La Valse d'Amélie, las
  notas fuera de la rejilla bajaron de 13 % a 1 %.
- **El compás desde el bajo.** En un vals, la nota más grave cae en el «1» de cada compás.
  Si eso es claro (1.5 semitonos o más de diferencia entre 3 y 2/4 tiempos), decide el compás:
  La Valse d'Amélie sale en 3/4. Si no, deciden las barras del detector.
- **YouTube y piano solo.** Las descargas de YouTube no guardan el audio original. Para
  transcribir un piano solo «desde el original» se usa la suma de los stems, que en una
  grabación de prueba coincidió con el original real con correlación 0.99.
- **El cursor fluye.** Avanza de nota en nota, entra a cada compás por su barra (leída de las
  líneas del pentagrama, no de la caja del compás, que crece con los nombres de acordes) y nunca
  retrocede dentro de un sistema. Entre las actualizaciones del audio, el reloj del navegador lo
  hace avanzar en cada cuadro. En las cinco piezas reales se pasó de hasta 33 retrocesos y 40
  saltos bruscos por pieza a 0 retrocesos y, como mucho, 1 salto. El cursor es una capa propia
  sobre la partitura (`render.js placeCursor`: una caja HTML movida con `transform`), no un
  rectángulo dentro del SVG: moverlo en cada cuadro repintaba todo el grabado (38 000 elementos en
  una canción de 3304 notas). Medido ahí mientras suena: el 5 % de los cuadros más lentos pasó de
  33 ms (un cuadro perdido) a 16,8 ms (ninguno).
- **Zoom.** Mientras se arrastra el control, lo dibujado se escala al instante (una vista
  previa: los renglones se cortan donde estaban); al soltarlo la partitura se graba de nuevo a ese
  tamaño (~0,5 s de Verovio en una canción de 3304 notas, 0,75 s en total) y la página vuelve al
  renglón donde va la canción. Antes no se veía nada hasta soltar.
- **Saltar en la canción.** Los FLAC que sirve la app (el audio de la partitura, el
  acompañamiento del saxo, Pianoteq y SWAM) llevan un índice de búsqueda (SEEKTABLE, un punto por
  segundo; `app/score/flacseek.py`), que ni ffmpeg ni libsndfile ni Pianoteq escriben. Sin él el
  navegador buscaba a tientas: para saltar a 0:30 de una canción de 6 minutos pedía seis veces la
  misma zona del archivo. Medido abriendo y saltando tres veces: de 15 peticiones y 22,6 MB a 4
  peticiones y 17,6 MB. El índice se lee de los encabezados de los propios bloques del archivo y
  el audio queda idéntico; los archivos que ya existían lo reciben la primera vez que se sirven.
- **Cuánto suena cada nota.** Al reproducir (MIDI y Pianoteq), cada nota suena hasta donde el
  pianista soltó la tecla, según lo oyó el modelo. No hasta donde está dibujada: cada pentagrama
  se dibuja a una sola voz, así que una nota sostenida se dibuja solo hasta la siguiente nota de
  esa mano. Reproducir lo dibujado dejaba picadas las notas de arpegios y voces interiores (en
  las tres piezas de Tiersen, entre 590 y 770 notas sonaban menos de la mitad de lo que se
  tocaron). La excepción son las notas cuyo final el modelo no oyó: las deja en 6 s, y esas se
  cortan donde están dibujadas, para que no queden sonando varios compases. Una tecla que se
  vuelve a tocar corta su propia nota. El resaltado, los acordes y el MIDI exportado cuantizado
  siguen la duración dibujada. El «MIDI crudo» conserva lo que oyó el modelo.

Tonalidad y compás, también persistentes:

- **Tonalidad**: *Auto* la estima con tres criterios sobre las notas transcritas: el perfil
  de alturas (Krumhansl-Schmuckler), cuánto del peso de las notas cae dentro de la escala (es lo
  que decide la armadura) y qué acordes suenan, con un extra para el acorde de tónica. *De la
  canción* usa el análisis de la separación; o puedes elegir cualquiera de las 24 a mano. Si el
  margen es bajo, «Diagnóstico» lo marca en amarillo: es una tonalidad ambigua. Lo habitual es
  dudar entre una tonalidad menor y su relativa mayor, que comparten armadura. Define la armadura y cómo se escriben las notas (Si♭ o La♯). En «Diagnóstico»
  se ven las dos estimaciones lado a lado.
- **Compás**: *Auto* usa un solo compás para toda la canción. Toma el más común del detector de
  pulsos y lo ubica donde coinciden la mayoría de sus barras. *Detectado* respeta las barras
  tal como las halló el detector, aunque cambien a mitad de canción. 2/4, 3/4, 4/4 o 6/4 lo
  fuerzan.
- **Barras ◀ ▶**: mueven las barras de compás un tiempo, si el «1» cae en el lugar equivocado.
- Los tramos donde el detector marcó un pulso sí y otro no (intros sin batería) se completan
  solos. En «Diagnóstico» aparecen como «Pulsos insertados».

**Controles ▴/▾** (junto a ▶): contrae todo menos la línea de reproducción (▶, saltos, Partitura/Piano,
tiempo y Escuchar); vuelve a expandirlo con el mismo botón. Se recuerda en cada equipo.

Las barras de arriba (título, reproducción y la fila de edición) quedan fijas al bajar por la
partitura, una debajo de otra; sus alturas se miden en vivo porque en la tablet ocupan más filas.
Orden: (1) reproducir, saltar, velocidad, qué se escucha, Seguir, Zoom y **Nombres** (cómo se ve la
partitura); (2) práctica (bucle, silenciar una mano, metrónomo, cuenta, teclado MIDI); (3) la fila
de edición (↶ ↷, ＋ Nota, Limpiar, Restaurar, ?) junto a la línea de estado. **🎼 Ajustes** despliega
los de la transcripción, que se tocan una vez por canción (plegados de entrada; se recuerda), y
**⬇ Exportar** junta las cuatro descargas. En escritorio la partitura empieza 80 px más arriba.
Cada vista muestra lo suyo: Zoom, Seguir, Nombres, 🎼 Ajustes y la fila de edición solo en la
partitura; estilo, teclado, colores, ＋ Nota y 🖌 Corregir manos solo en el piano. ↶ ↷ de la barra
de reproducción aparecen solo en el piano (y con «Controles ▾»): en la partitura estaban dos veces.
**En tablet** (hasta 1100 px de ancho), mientras suena la vista de piano las barras se apartan solas
y queda la línea de «Ocultar paneles» (con ▶ y ▤ Paneles); al pausar vuelven. A 1024×768 la pista
pasa de 390 a 756 px. «▤ Paneles» las trae de vuelta por lo que queda de esa reproducción. No se
guarda: es solo mientras suena.

Ajustes de la partitura (en **🎼 Ajustes**), también persistentes: **Rejilla** (1/8, 1/16, 1/16 + tresillos),
**Mano derecha desde** (punto de división entre claves), **Tempo** (×½ / ×2 si el tempo
detectado salió a la mitad o al doble), **Acordes** (cada pulso / medio compás / compás /
ocultos) y **Nombres** (sin nombres, por defecto / do re mi / C D E: el nombre de cada nota
dentro de su cabeza, con su alteración: «si♭», «fa♯»; la elección queda guardada en este
navegador). La alteración va en la etiqueta porque las de la armadura no se dibujan junto a la
nota: en Mi♭ menor, sin ella un si♭ decía «si». Las escrituras que nombran otra tecla que la que
suena (do♭, fa♭, mi♯, si♯) se nombran por la tecla, en las notas y en los acordes: el do♭ de Mi♭
menor (la tecla si) dice «si», y su acorde «Simaj7», no «Do♭maj7».

**⬇ Exportar**: **MIDI** (cuantizado, con el mapa de tempo real: en un DAW queda alineado con el
audio desde el segundo 0), **MIDI crudo** (tal como se tocó), **MusicXML** (MuseScore,
Sibelius, Finale) y **PDF** (imprimir).

## Cómo verificar que está bien (1 minuto)

### Opción A: la canción de calibración

1. Abre `http://localhost:8001/score/` y pulsa **Crear canción de calibración**.
2. Pulsa **Extraer MIDI y generar partitura**.
3. Arriba aparece un recuadro con lo que **debes ver** y una **comprobación automática** (✓/✗):

   - 90 BPM, 4/4, Fa mayor (un bemol en la armadura).
   - Clave de sol arriba, clave de fa abajo, unidas con llave.
   - 8 compases y 59 notas, cada una con su nombre adentro.
   - Acordes: **Fa | Do | Fa | Si♭ Do | Rem | La/Mi | Do7 | Fa**.
   - Compás 5 con ocho corcheas unidas por barras; compás 6 con dos tresillos y un do♯.
   - Al reproducir, la nota que suena se ilumina y el cursor avanza al ritmo.

   Lo normal es **58 de 59 notas**. El modelo de piano no oye el Fa3 que dobla al Fa2 a la
   octava en el último acorde: con dos notas a la octava, la de arriba queda tapada.

### Opción B: con una canción tuya

- **¿El MIDI es correcto?** Pon **Escuchar: MIDI extraído** y luego **Stem**, en el mismo
  punto. Si suenan igual, la transcripción está bien, aunque la partitura se vea rara.
- **¿Se ve raro aunque suena bien?** Abre **Diagnóstico**. Si «Notas movidas > 40 ms» es
  alto, el problema es el tempo: prueba **Tempo × ½ / × 2** o una rejilla más fina.
- **¿Otra opinión?** Descarga el **MusicXML** y ábrelo en MuseScore. Es otro motor de
  partituras, independiente de este.

## Pruebas automáticas

```bash
.venv/Scripts/python.exe -m pytest tests/test_score_engrave.py tests/test_score_api.py tests/test_score_basic_pitch.py tests/test_score_render_verovio.py tests/test_score_transcribe_model.py
```

```bash
node tests/js/score-model.test.mjs
```

```bash
npm run test:score
```

| Prueba | Qué garantiza |
|---|---|
| `test_score_engrave.py` | La calibración se graba **exactamente** igual que la referencia. Además: imprecisión humana de ±30 ms, aceleración de tempo, Si♭ y no La#, alteraciones que persisten en el compás, empates entre compases, acordes, notas duplicadas, MEI, MusicXML y MIDI sincronizado con el audio. |
| `test_score_api.py` | Ciclo de transcripción, **ediciones que persisten**, restaurar, validaciones (422/409/404), ajustes, acordes y exportaciones. |
| `test_score_transcribe_model.py` | El modelo de piano real sobre la calibración sintetizada: **F1 ≥ 0.90** (sale ~0.97). |
| `test_score_basic_pitch.py` | Bajo y melodía con Basic Pitch: F1 ≥ 0.90. |
| `test_score_render_verovio.py` | El MEI del servidor, dibujado con el mismo Verovio de la página: cada id de nota llega al SVG. |
| `score-model.test.mjs` | Funciones del editor: etiquetas, qué suena en cada instante, cursor y cada edición. |
| `score-e2e/score.spec.mjs` | En Chromium real: claves, una etiqueta por nota, acordes, seguimiento con audio, cada edición persistiendo tras recargar, selección de área, limpieza, ajustes y exportaciones. |

## GPU (NVIDIA)

Con una GPU NVIDIA, la separación y la extracción del piano pasan de minutos a segundos.
Medido en una RTX 5070 Laptop con una canción de 9 minutos:

| Paso | CPU | GPU |
|---|---|---|
| Separar (Demucs, 60 s de audio) | ~20 s | 1.3 s |
| Extraer MIDI del piano (9 min de audio) | ~6 min | **20 s** (mismas notas, F1 0.999) |
| Bajo / guitarra / voz / otros (Basic Pitch) | segundos | corre en CPU, no hace falta |

El `uv.lock` del proyecto fija torch 2.6 de CPU. Las GPU Blackwell (RTX 50xx, compute 12.x)
necesitan torch 2.8.0 con CUDA 12.8, igual que instala la app de escritorio (`wheel_candidates`
en `desktop/src-tauri/src/main.rs`). En el venv de desarrollo:

```bash
uv pip install --python .venv/Scripts/python.exe --no-deps torch==2.8.0+cu128 torchaudio==2.8.0+cu128 torchvision==0.23.0+cu128 --index-url https://download.pytorch.org/whl/cu128
```

Después, **no uses `uv run` ni `uv sync`**: vuelven a instalar el torch de CPU del lock. Usa
directamente el Python y el uvicorn del venv (`.venv/Scripts/python.exe`,
`.venv/Scripts/uvicorn.exe`). Ojo: `npm run test:e2e` (el e2e del estudio) arranca su servidor
con `uv run` y revierte torch; `npm run test:score` ya usa `--no-sync`. Si se revierte, repite
el comando de arriba (`python -c "import torch; print(torch.__version__)"` lo muestra). Las GPU
anteriores (RTX 20/30/40) usan `cu124` con torch 2.6.0.

El dispositivo sigue el ajuste de la app (Ajustes → dispositivo; «auto» usa la GPU si existe),
tanto para la separación como para la partitura. Si la GPU falla (por ejemplo, por falta de
memoria), la partitura se reintenta sola en CPU. «Diagnóstico» muestra en qué dispositivo se
extrajo.

## Partitura desde PDF y digitación (experimental)

En la portada de partituras (`/score/`, sin canción), **Importar partitura**: un PDF o una
imagen de una partitura de piano. Crea una canción nueva en la biblioteca:

- **Lectura:** con [Audiveris](https://github.com/Audiveris/audiveris) (reconocimiento óptico
  de partituras, AGPL, se usa como programa aparte, no va dentro de la app). En modo dev está
  desempaquetado en `.run/tools/audiveris` (git lo ignora); también lo busca en Program Files o en
  `STEMDECK_AUDIVERIS`. La lectura de digitaciones viene apagada en Audiveris y se enciende aquí.
- **Sonido:** el audio se genera desde las notas con Pianoteq (o el sintetizador de la
  calibración si no está), al tempo que pongas (o el de la partitura, o 60). Los compases y pulsos
  son los de la partitura, exactos, y cada nota va en la mano de su pentagrama.
- **Dedos:** en la barra del piano con notas cayendo, **«En las notas»** elige qué va dentro de
  cada nota: **Nombre (C D E)** (por defecto) o **(do re mi)**, **Número de dedo**, **Nombre y
  dedo** o **Nada**; en esas canciones reemplaza a «Nombres». El nombre va también sobre la tecla
  que suena (en 3D las notas lejanas son finas para escribirlo). Los números: en **blanco** los impresos en la partitura, con **borde dorado**
  los que pongas tú, en **gris** los sugeridos. Para cambiarlos: elige notas y pulsa **1–5**
  (**0** vuelve al sugerido), o los botones **Dedo** de la barra flotante en la tablet. Se guarda
  en el servidor. El selector solo aparece en canciones con digitación; las demás no cambian.
- **Dedos en cualquier canción (solo si los pides):** en una canción que no viene de una
  partitura (YouTube, un audio), la barra del piano muestra **«Activar dedos»**: cada nota recibe
  un dedo sugerido (en gris, con las manos que dibuja la partitura) y los corriges igual, con
  **1–5**. Solo en esa canción. **«Quitar dedos»** lo deshace (pide confirmación si pusiste
  dedos a mano). Las canciones importadas desde una partitura no se pueden quitar: sus dedos
  impresos se conservan.
- **Coherencia (2026-11-11):** la misma figura lleva los mismos dedos. Además de las distancias de
  Parncutt se aplican sus demás reglas (dedos débiles 4 y 5, 3 seguido de 4, 4 en negra junto a 3
  en blanca, pulgar o meñique en negra entre blancas), cruzar el 2 sobre el pulgar cuesta más,
  tras una pausa de 0,5 s la mano se reubica en vez de cruzar, y nunca el mismo dedo en dos teclas
  seguidas de un pasaje rápido. Después, un consenso: una segunda pasada prefiere, para cada
  figura repetida (mismas notas alrededor), los dedos que esa figura usa la mayoría de las veces.
  Medido en 17 canciones: la misma tecla en el mismo patrón rápido con el mismo dedo, 88,8 % →
  92,0 %; contra los 161 dedos impresos del Nocturno, 57,8 % → 84,5 %; el mismo dedo en dos teclas
  seguidas, 0,8 % → 0,3 %. En «BAILE INOLVIDABLE», la figura Re-Do-Si-La va siempre 4-3-2-1.
- **Sugerencias:** cada mano por separado, con programación dinámica sobre la comodidad de cada
  par de dedos (tabla de Parncutt et al., 1997); respeta los dedos fijos. Un dedo que sostiene una
  tecla no se usa para otra (hasta 1,2 s: después el sonido lo sostiene el pedal); un acorde
  tocado algo desparejo (hasta 60 ms) sigue siendo un acorde, con los dedos en orden; cruzar
  dedos cuesta (el pulgar pasa por debajo, nunca 3 sobre 4) y el pulgar evita las teclas negras.
  Medido en canciones transcritas: el mismo dedo en dos teclas a la vez bajó de 190 a 19 en
  Comptine y de 160 a 104 en Barbarossa (lo que queda es casi todo pedal: notas que la
  transcripción alarga). En escalas da 1-2-3-1-2-3-4-5
  y en el acorde mi-sol♯-do♯ del Nocturno 1-2-5, como la edición. Es una sugerencia: no sabe de
  fraseo ni de pedal.

- **Más dedos impresos:** Audiveris lee pocos números de digitación, así que después se buscan
  en la propia imagen de la página que dejó Audiveris (`digits.py`): manchas del tamaño de un
  número que no sean nada ya reconocido, comparadas con 0–9 dibujados en fuentes serif negritas y
  con dígitos en cursiva (los «3» de tresillo son cursivos y no son dedos). Una primera pasada toma
  los números más seguros como plantillas de la fuente de esa edición para la segunda. Cada número
  va a la nota que tiene justo debajo (o encima, bajo el pentagrama); apilados sobre un acorde, de
  arriba abajo; un par lado a lado («2 3», cambio de dedo) se queda con el primero.

Medido con el Nocturno en do♯ menor de Chopin (1 página escaneada, edición Alfred, 18 compases),
contra una referencia hecha a mano de los **59 números impresos**:
- Audiveris leyó los 18 compases y las notas revisadas coincidían, salvo el compás 13 (8va con
  semicorcheas), que no pudo leer y queda en silencio (se avisa al importar). Tampoco exporta las
  notas de adorno. Así, 46 dedos tienen nota donde ir.
- Audiveris solo leyó **10**. Con el detector, **41** (85 % de los 46), en la nota correcta: por
  ejemplo, el arpegio del compás 3 queda 5-3-1-2 | 5-1-2-3 como en la edición. Hubo 3 números mal
  leídos. Del compás 13 el detector leyó bien los 9 dedos, pero esas notas no existen.
- Faltan sobre todo los números pegados a una plica o a otro número (la pila 5-2-1 del primer
  acorde) y los de las notas de adorno. Los demás se sugieren y se pueden corregir. Código: `app/experimental/sheet/`, `app/api/experimental.py`,
`static/js/score/sheet-fingering.js`; pruebas en `tests/test_experimental_sheet.py`.

- **Trinos:** un «tr» ya no es una nota larga: se toca como trino (`ornaments.py`), unas 8
  notas por segundo entre la nota y su vecina de arriba en la tonalidad, empezando en la nota
  principal (o con las notillas impresas antes) y terminando con las notillas de después. Los
  dedos impresos sobre el trino («2 3») van en cada nota.

### El Nocturno completo (64 compases)

La página Alfred solo trae 18 compases, y Audiveris perdió en ella el compás 13, las notillas y
los trinos: de ahí que «faltaran notas de la mano derecha». La canción **«Nocturno en do# menor,
op. póstumo (Chopin) — completo»** se arma con `scripts/experimental/nocturno_chopin.py`:

- **Notas:** de la edición tipográfica de Pierre Gouin (IMSLP, Les Éditions Outremontaises 2006,
  vectorial), leída por Audiveris y **corregida a mano compás por compás** contra la página
  ampliada (tabla `FIXES` del script): tresillos, quintillos y seisillos de las escalas, las 8va
  de los compases 15, 48, 58 y 64, el cambio de clave del 44 que Audiveris no vio (44-47 salían
  una sexta abajo), las notillas de 24 y 28, los compases 56 y 61-62 vacíos, y las escalas libres
  57-60. Donde Gouin y Alfred difieren (notillas antes de los trinos de 5, 13 y 46; el do♯ del
  compás 7 ligado o repetido) se sigue a Alfred, que es también lo que toca la grabación.
- **Dedos:** los 65 números impresos de la página Alfred, leídos a 300 ppp y puestos en su nota
  (tabla `ALFRED`), más los de los trinos; la escala del compás 13 de Alfred (15 de Gouin) lleva
  los 9 que lee el detector. Se repiten donde Gouin repite compases (la introducción, 46-48).
  Lo leído automáticamente (Audiveris + detector) coincide en los 30 que tienen nota en común.
- **Tempo:** el de una interpretación real, compás a compás: Stefano Ligoratti (IMSLP #72479),
  transcrita con el modelo de piano y alineada con la partitura (DTW de croma y luego un
  seguidor nota a nota). Dura 3:47 como la grabación.
- **Comparación con la grabación:** de las 711 notas de la partitura (sin contar trinos ni
  escalas libres), el pianista toca **670 (94 %)** en su sitio. Lo que no coincide es sobre todo
  la mano izquierda tapada por los trinos (compás 11) y repeticiones de notas ligadas. El informe
  por compás queda en `jobs/<id>/sheet/comparison.txt`.

## Sincronía al cambiar de fuente (Stem, Canción completa, Pianoteq, MIDI)

La página toca un solo audio como reloj y lo cambia de archivo al elegir otra fuente, en el
mismo momento de la canción. Con MP3 (VBR) Chrome caía entre 40 y 170 ms antes o después del
momento pedido **sin avisarlo**, y desde ahí la partitura, el MIDI y el sonido iban corridos.
Regla: **todo lo que suena en la página es FLAC** (sin pérdida, salta a la muestra exacta):
el stem y la canción completa (`/api/jobs/<id>/score/audio/<stem|mix>.flac`, generados una vez
y guardados en `score/audio/`) y Pianoteq (renderiza directo a FLAC). Medido en Comptine: cada
salto cae a 0–5 ms del punto exacto (antes ±170 ms). Pesa unas 3 veces un MP3 (~10 MB por 3 min).

## Notas con ataque débil (transcripciones de audio)

Además de las notas sin ataque en el audio, se quitan (y quedan en «Notas borradas») las que el
propio modelo casi no oyó: su confianza de ataque es menor que 0,6 y el audio sube menos de 4 dB
en sus parciales. En «Cry», desde 1:02, la mano derecha se llenaba de golpes sueltos de sol, re
y fa♯ entre las notas reales (el pedal y la reverberación del piano); medido en canciones
completas, marca el 19 % de las notas de Cry, el 1,7 % de Comptine y el 0,3 % de la Valse
d'Amélie. Solo cuenta en canciones extraídas desde esta versión (la confianza la guarda la
transcripción): para una anterior, «Volver a extraer».

## Videos de notas cayendo: las notas salen del video

Si la canción viene de un video con un teclado cuyas teclas se iluminan (Synthesia, tutoriales
de piano), al **Extraer MIDI** la app lee las teclas del video en vez de adivinarlas del audio:
la nota exacta, su octava y su tiempo. **Es automático**: no hay que elegir nada. Si el video no
muestra un teclado (un video musical, una persona tocando), o lo que muestra no coincide con el
audio, se usa el audio como siempre.

- **Cómo:** se busca en el video una franja con teclas negras en grupos de 2 y 3 (eso da el
  nombre de cada tecla); una tecla está iluminada mientras su color se aleja del de reposo y es
  un color vivo (un fundido a negro o un brillo azul oscuro no cuentan). La octava y el ataque
  exacto se toman del audio transcrito; el video se usa si el audio confirma al menos el 45 % de
  sus notas.
- **Manos:** si el video pinta las manos de dos colores (verde y azul en Synthesia), se usan
  esos; si es de un solo color, se separan por registro (acordes abajo, melodía arriba).
- **Medido:** «Y dime – Intro con notas y acordes» (teclado de 3 octavas, un color): el audio
  ponía 70 de las 75 notas de la melodía una octava abajo, entre los acordes; desde el video, 180
  notas, acordes en la izquierda y melodía en la derecha, 75 % confirmadas por el audio.
  «TURiSTA (Piano Tutorial)» (88 teclas, verde/azul): 1346 notas, 91 % confirmadas, manos por
  color. Detectar el teclado tarda menos de 1 s; leer un video de 3 minutos, ~30 s.
- **Elegirlo a mano:** «Extraer desde» y «Volver a extraer desde» tienen **las notas del video**
  (en canciones con video); **el stem de piano** o **el audio original** fuerzan el audio. En
  Diagnóstico, «Audio transcrito» dice de dónde salieron. Código: `app/score/video_notes.py`.

## Dos modelos de separación: Demucs y RoFormer (experimental)

Demucs, el separador de la app, a veces no reconoce un teclado: en «Y Dime» (Agrupación Marilyn)
el punteo de teclado quedaba en el stem de guitarra al principio, después en «otros», y unos
acordes en piano (presencia de piano 2/100). **BS-RoFormer SW** (jarredou; seis pistas como
Demucs) lo deja todo en **piano**, parejo de principio a fin; escuchado y confirmado.

- **Al importar:** en el compositor, junto a «Extraer», **Modelo: Demucs / RoFormer (teclado y
  guitarra)**. Se recuerda en el dispositivo. Por defecto Demucs; si RoFormer no está instalado,
  el selector no aparece.
- **Una canción ya separada, con el otro modelo:** en la página de la partitura (bajo «Extraer
  MIDI», o en «Diagnóstico»), **Separar con el otro modelo → Crear copia con RoFormer** (o **con
  Demucs**, si se separó con RoFormer). Crea una **copia** en la biblioteca («… — separador
  RoFormer/Demucs») con las seis pistas nuevas y los mismos compases, letra y datos; la canción
  original no cambia. Con GPU, RoFormer tarda ~40 s en una canción de 3 minutos. Con una canción
  abierta, «Extraer stems» la vuelve a separar con el modelo elegido (una versión nueva, sin
  reemplazarla), aunque no se haya guardado su audio original: se rearma sumando sus pistas.
- **Instalación (aislada, no toca las dependencias de la app):** el paquete `bs-roformer-infer`
  (MIT) desempaquetado en `.run/tools/roformer/lib` y su modelo `BS-Rofo-SW-Fixed.ckpt`
  (~700 MB, SHA-256 verificado) en `.run/tools/roformer/models`; corre en un proceso aparte con el
  torch de la app. Otra carpeta: `STEMDECK_ROFORMER`. Código: `app/experimental/separation.py`,
  `app/pipeline/separate.py` (`Job.separator`), `static/js/job.js`, `static/js/score/separation.js`.
- **Ojo:** RoFormer dejó la guitarra vacía en esa canción; si una canción tiene guitarra real,
  conviene escuchar la copia antes de quedarse con ella. Cancelar una separación con RoFormer
  espera a que termine el modelo.

## 🎷 Saxo: una parte de la canción como línea de saxo

En el estudio, el **🎷** de la cabecera del mezclador (al lado de «Mezclador») abre `/sax/` con la
canción en el punto donde iba (el estudio se pausa). Arriba eliges **qué toca el saxo**: Voz,
Piano, Guitarra, Otros, Bajo, uno o varios. El primero que eliges es la melodía (**1**); los
demás (**2**, **3**…) solo rellenan donde el primero calla (por ejemplo Voz + Piano: la voz, y
el piano en los puentes sin voz). Cada stem se transcribe la primera vez (como su partitura; la
voz de una canción de 3:40 tardó ~30 s) y queda guardado.

**Cómo se arma la línea:** el saxo toca una nota a la vez, así que de cada acorde queda la nota
de arriba (la melodía), y cada nota termina donde empieza la siguiente. Después se lleva al
registro del saxo **por frase** (una frase entera sube o baja de octava, así conserva su forma;
lo marca «8va ↑» donde empieza) y se escribe **transpuesta** para el saxo elegido: **Alto (Mi♭)**,
Tenor (Si♭), Soprano (Si♭) o Barítono (Mi♭). Lo que lees es lo que tocas; debajo dice cómo suena
(«suena La4»).

**Qué se ve:**

| Dónde | Qué |
|---|---|
| Carril | las notas llegan de derecha a izquierda sobre un pentagrama en clave de sol, a su altura, cada nota de un color (el mismo color siempre para la misma nota), con su nombre y líneas adicionales; chispas al sonar; «’» donde hay que respirar |
| Arriba | las próximas notas, grandes y de color; la que suena, resaltada; «’ respira» en los silencios |
| Saxo (izquierda) | **las llaves de la digitación de la nota que suena**, encendidas en su color; las de la nota siguiente, con un anillo punteado (para preparar los dedos); debajo, la nota en grande |

Las digitaciones son las estándar de Si♭3 a Fa6 (escritas), con la llave de octava, bis, palmas
y meñiques; hay alternativas (Si♭ lateral, Fa♯ de horquilla…) que no se muestran.

**RMVPE** (la voz, desde 2026-11-16): si están sus pesos en `.run/tools/rmvpe/rmvpe.pt` (181 MB,
de huggingface.co/lj1995/VoiceConversionWebUI; MIT vía el proyecto RVC, original Dream-High/RMVPE
Apache-2.0; se verifica su SHA-256 al cargar), el tono de la voz lo lee RMVPE, un modelo hecho para
voz cantada dentro de una mezcla, en la GPU: una canción de 3:16 en ~1,3 s (4 s la primera vez,
con la carga). La línea son sus propias notas: en voces de notas conocidas (vibrato, deslizamientos,
sala, el resto de la banda colado) acierta 94 / 97 / 90 %, contra 85 / 88 / 78 % mezclado con la
transcripción de Basic Pitch y 80 / 79 / 66 % con Basic Pitch solo. Sin los pesos, se usa lo de
abajo (pYIN). Para instalarlo: descargar `rmvpe.pt` a esa carpeta (o `STEMDECK_RMVPE=<ruta>`).

**Sonido: Expresivo (como canta)** (por defecto) — el saxo toca la voz como fue cantada: cada
nota con la grabación sin vibrato de esa altura (Iowa, `-novib`), y encima la curva real de la voz
cada 20 ms (sus deslizamientos, su vibrato, sus matices de volumen), acotada a ±2 semitonos de la
nota. Verificado midiendo el audio que sale: una nota con vibrato y un deslizamiento de Mi4 a Sol4
sale en 63,95 y 67,05. *Notas exactas*: cada nota fija, con la grabación con vibrato. El piano y los
demás stems siempre suenan como notas exactas (no tienen curva de voz).

**🎤 Practicar**: tocas tu saxo y el micrófono lo escucha (YIN, sin cancelación de eco ni
supresión de ruido, que deforman el tono). En el carril, un círculo «tú» a tu altura (verde: en la
nota; ámbar: a menos de un semitono; rojo: más lejos) con su estela; bajo el saxo, un medidor de
±100 cents y «↑ sube / ↓ baja», o «una octava arriba» si es la nota correcta en otra octava. Cada
nota cuenta como acierto si estuviste en ella el 40 % de lo que dura («Aciertos 34/50 (68 %)»).
**⏸ Esperarme**: la canción se detiene en cada nota hasta que la tocas afinado un momento. El
micrófono escucha la nota real (de concierto): tocas lo escrito para tu saxo y él compara lo que
suena.

**Un saxo (o vientos) en «Otros»** (2026-11-16): el separador no tiene stem de saxo; el saxo,
los vientos, las cuerdas y los sintetizadores quedan en *Otros*. Con RMVPE, la línea de *Otros*
se sigue nota a nota como una voz (`GET /sax/line/other`, `voice_line.analyse(wav, "instrument")`:
mediana de 70 ms en vez del promedio de vibrato de la voz, que borroneaba los pasajes rápidos) y
se frasea como voz; una nota corta pegada a dos vecinas va a la más cercana en altura (un *scoop*
es el inicio de la nota a la que entra). Medido en una línea de saxo conocida (grabaciones reales
de Iowa con scoops, sobre colchones, cuerdas, bajo y sala): notas correctas 66 / 75 / 80 % contra
46 / 45 / 39 % de Basic Pitch (que tomaba las notas de arriba de los colchones y octavas falsas).
En «Careless Whisper» (cover instrumental) el rango pasó de Mi1–Re7 a La3–Re6. Si la voz casi no
suena (`stem_presence` < 20) la página empieza en *Otros* y lo dice; el 🎷 del estudio ya no fija
la Voz.

**✏️ Editar**: toca una nota (la canción se pausa y la nota suena) y bórrala (🗑 / Supr), súbela o
bájala un semitono (▲▼ / ↑↓, o arrástrala arriba/abajo), una octava (8↑ 8↓ / Mayús+↑↓) o muévela en
el tiempo (◀ ▶ / ←→, o arrástrala a los lados). ↶ ↷ (Ctrl+Z / Ctrl+Y) deshacen y rehacen; «Volver
al original» quita todos los cambios de esa línea (también se deshace). Se guardan por línea
(stems + fraseo) en `score/sax_edits.json` (`GET/PUT /sax/edits`; no lo borra «Limpiar caché»),
cada nota nombrada por su stem, su inicio y su altura de concierto: sobreviven a cambiar de saxo.
Al borrar, queda elegida la siguiente: una racha de notas basura sale tecla por tecla. La duración: ⇤ Corta / Larga ⇥ (Alt+← / Alt+→, de a 0,1 s) o arrastrando el borde derecho de la nota; una nota alargada tapa el inicio de la siguiente (y la quita si no queda nada de ella).

**＋ Nota**: agrega una nota donde está la canción, a la altura de la nota elegida o de la más cercana (botón o tecla N), o con doble clic en un lugar vacío del pentagrama (en ese momento y a esa altura). Queda elegida y se mueve, se alarga y se borra como las demás; se guarda como `add|inicio|altura` con su largo (`len`).

**Varias notas**: Mayús o Ctrl + clic suma una nota a las elegidas (o la saca); con **☑ Varias** activo, cada toque suma (para tablet) y arrastrar sobre el pentagrama vacío elige las que quedan dentro del recuadro; Ctrl+A las elige todas. Lo que se haga (▲▼, 8↑↓, ◀▶, Corta/Larga, arrastrar, 🗑) se aplica a todas juntas y se deshace de una vez. **⧓ Unir** (U) junta las elegidas en una sola nota, desde el inicio de la primera hasta el final de la última, a la altura de la primera: para una nota sostenida que el detector cortó en pedazos.

La barra de edición es una fila propia sobre el pentagrama (antes flotaba encima y tapaba las notas agudas; en tablet, un tercio del pentagrama). El texto de la nota elegida y el contador de cambios tienen ancho fijo: elegir o editar una nota no cambia el alto de la barra ni mueve el pentagrama bajo el puntero.

**La barra de abajo**, en filas según para qué sirven: (1) tocar la canción (▶, tiempo, posición, velocidad) y los modos (✏️ Editar, 🎤 Practicar); (2) estudiarla (Bucle, Metrónomo, Cuenta, Vista) y lo que se oye (Escuchar, los dos volúmenes y **🎚 Sonido**, un menú con lo que se ajusta una vez: el saxo, la sala, el tono y la expresión); (3) qué está pasando (el saxo que suena, las notas, los avisos).

**En tablet** (pantalla de hasta 1100 px de ancho): Notas, Fraseo y Nombres se pliegan en el menú «⚙ Notas» (la cabecera queda en una fila) y el nombre de la nota comparte fila con el botón de la foto, así el diagrama de digitación gana alto: a 1024×768 pasa de 304 a 409 px (los números de los dedos, de 14 a 19 px). El botón «‹» del panel oculta la digitación y deja todo el ancho al pentagrama; la pestaña «🎷 ›» la trae de vuelta (se recuerda).

**La parte en papel** (arriba, «🖨 PDF» y «⬇ MusicXML»; en tablet, dentro de «⚙ Notas»): la línea como suena en la página, con lo que editaste, grabada en un solo pentagrama en clave de sol y en los compases de la canción, escrita para tu saxo (`POST /api/jobs/<id>/sax/export.{musicxml|mei}`, `app/api/sax.py sax_part`): las notas y la armadura transpuestas (Careless Whisper suena en Re menor; para el alto queda en Si menor). El MusicXML lleva la transposición (`<transpose>`), así MuseScore, Sibelius o Finale la tocan como suena. «🖨 PDF» arma páginas A4 con Verovio (`static/js/sax/print.js`, cargado solo al pedirlo) y abre el diálogo de impresión del navegador (ahí se elige «Guardar como PDF»). Careless Whisper: 79 compases en 2 páginas, lista en 1,3 s.

**Colores del pentagrama**: las notas que vienen en un solo color (azul) y la que suena en dorado, como la franja de arriba y el diagrama de digitación (antes, un color por altura: un arcoíris que había que descifrar). Qué nota es lo dicen su altura en el pentagrama y su nombre.

**El ritmo en el pentagrama**: una línea tenue en cada pulso y una más clara donde empieza cada compás, con su número (de la rejilla de pulsos del estudio, `GET /api/jobs/<id>/beats`; `static/js/sax/beats.js`). Sin rejilla, las marcas de segundos de antes.

**Bucle** (abajo): **A** marca el inicio en el compás que está sonando y **B** el final (B sin A repite ese compás); al pasar B la canción vuelve a A. 🔁 lo apaga sin perderlo y ✕ lo quita. La parte repetida se ve iluminada en el pentagrama, con A y B. Se guarda por canción en el navegador. Sin rejilla de pulsos, A y B son el momento exacto.

**Metrónomo** y **Cuenta** (abajo; solo si la canción tiene rejilla de pulsos): el metrónomo da un clic en cada pulso de la canción, más agudo en el primero de cada compás, a la velocidad de práctica. «Cuenta: 1 compás / 2 compases» hace sonar esos clics al pulsar ▶, al tempo de ese punto, y después empieza la canción; ▶ otra vez durante la cuenta la cancela.

**Arrastrar la pista** (como las notas cayendo del piano): con el clic (o el dedo) sobre la pista, la canción se mueve con el puntero; si sonaba, se pausa mientras arrastras y sigue al soltar. En «Editar», arrastrar sobre el espacio vacío hace lo mismo.

**La franja de arriba** muestra la frase que se toca (hasta la próxima respiración; máximo 10 notas, cortada en su pausa más larga), toda de una vez y de un solo color: la que suena en dorado, las ya tocadas atenuadas, cada una un poco más arriba o abajo según la melodía; después de «luego», el inicio de la frase siguiente. Cambia solo al pasar de frase (antes: nueve notas de colores distintos que se corrían en cada nota).

**Digitación**: *Diagrama grande* (por defecto, `static/js/sax/chart.js`; el botón «🖼 Ver foto» bajo el nombre de la nota cambia a la foto y «▦ Ver diagrama» vuelve): las llaves por manos (izquierda arriba, derecha abajo), los dedos 1-2-3, el pulgar con la octava, la palma, los meñiques y la lateral, cada una con su nombre; las que se aprietan en dorado y las de la nota siguiente con un anillo celeste punteado. *Foto del saxo (anterior)*: la vista de antes (`horn.js`), para volver a ella.

**Saxo: SWAM (modelado físico)** (por defecto si está instalado; abajo, «Saxo»): la línea la toca
*SWAM Saxophones* de Audio Modeling (de pago, instalado aparte), como Pianoteq toca la partitura.
La página manda la línea tal como suena (fraseada, en el rango, con las ediciones y, en
«Expresivo», la curva de cada nota); `app/score/swam.py` la graba en segundo plano (~15 s una
canción de 4 min) y la página la toca en un `<audio>` propio, atado al reloj de la canción (con su
velocidad; desfase medido ≤ 23 ms al 100 % y al 50 %). Mientras graba suena el saxo grabado
(Iowa); tras una edición sigue la grabación anterior hasta que llega la nueva. Cómo toca
(`app/score/swam_render.py`): las notas ligadas se solapan (SWAM hace la transición); el soplido
(Expression, CC11) es **parejo**: un nivel por nota, con solo el 20 % de su volumen grabado frente
al centro de la línea, y la misma forma en todas (entra en 60 ms, salvo ligada, y se asienta un
poco). Antes seguía el volumen de la pista «Otros» cada 20 ms, que sube y baja con los pads y la
reverberación: el soplido temblaba dentro de la nota y la misma nota salía con más o menos aire
cada vez (Careless Whisper: CC11 saltando 12-32 pasos en 20 ms; una nota entre 67 y 127). El
ataque (velocity) se empareja igual. La afinación de la canción y la curva (deslizamientos,
vibrato) van por el pitch bend (±2 semitonos), limpia de los saltos del detector (un cuadro a más
de un semitono pasado el ataque se descarta, mediana de 3 y suavizado; ±½ semitono pasado el
ataque). Medido en Careless Whisper, misma nota repetida: el aire varía 5,2 dB (antes 9,7) y el
brillo 42 % (antes 55 %); con el soplido del todo plano no mejora más: lo que queda es SWAM según
el contexto (ataque o ligada, largo de la nota). «Exacto» (sin curva) es lo más parejo. Una nota
**alargada** con ✏️ se sostiene en lo agregado (su altura asentándose en la nota y su último nivel,
`curveOf` en `static/js/sax/main.js`): antes leía lo que la grabación hacía después (silencios y las
notas siguientes) y sonaba como la misma nota pegada varias veces (Careless Whisper: el soplido
127 → 51 → 127 y la altura un tono abajo). El aire se corta entre dos notas solo si hay un silencio
de más de 60 ms, y nunca dentro de la nota siguiente. Medido: notas a la altura pedida en el 92 % del tiempo (dentro de un
semitono el 98 %; lo demás son las curvas); el tenor y el barítono de SWAM suenan una octava bajo
la nota MIDI y se mandan una octava arriba. Se aloja con DawDreamer (carga el VST2 `.dll` que
instala el Software Center en `C:\Program Files\Common Files\VST2\SWAM\Saxophones`) en un entorno
aparte, `.run/tools/swam-venv` (`uv venv` + `uv pip install dawdreamer numpy soundfile mido`), y
en un proceso aparte: si el plugin se cae no se lleva el servidor. Grabaciones en
`score/audio/swam-<clave>.flac` (las 12 más nuevas por canción; «Limpiar caché» las borra). La
clave es un hash de lo que SWAM toca (los eventos MIDI de `swam_render.events()`, el saxo, el
largo), no de lo que manda la página: al cerrar y abrir la app, o con cualquier cambio que no cambie
cómo suena, se usa la grabación ya hecha.
Los ajustes del plugin (`swam.plugin_params`) son parte de la clave. El azar propio de SWAM va
apagado: «Random Dynamic» (9 → 3, su mínimo) y «Dynamic Pitch» (30 → 0), que sobre la dinámica y
la altura del intérprete hacían sonar distinta la misma nota. Medido en los 2 primeros minutos de
Careless Whisper, misma nota repetida (desviación estándar): aire 1,51 → 1,23 dB, brillo 12,5 →
11,8 %. Dos grabaciones de la misma línea son idénticas muestra a muestra.
**Sala** (abajo, solo con SWAM): la sala del propio SWAM, un modelo de sala (`swam.ROOMS`: tamaño,
materiales, distancia del saxo). «Reverb Mix» y «Reverb Time» no hacen nada en SWAM 3 salvo con
«Legacy Reverb» (medido: la grabación sale idéntica). Cola 0,35-0,65 s después de una nota,
respecto de la nota: *Seca* −41 dB (MEDIUM 1, absorción alta, 1,2 m), *Media* −28 dB (el plugin
como viene), *Amplia* −20 dB (LARGE 2, absorción baja). Cambiarla es otra grabación; mientras se
hace sigue sonando la anterior.
**Tono** (abajo, solo con SWAM; `swam.TONES`): *Limpio*, como venía. *Suave, con aire*: soplado al
70 % (SWAM oscurece y airea el tono al soplar más suave: 8 dB menos sobre 5 kHz, medido) y su
ruido de aire al máximo. *Rasgado*: el «Growl» de SWAM al 35 % (el volumen tiembla a 20-90 Hz:
+3 dB, medido). El parámetro «Breath Noise» solo casi no cambia el sonido a soplido normal (medido).
**Volumen**: la grabación se deja al nivel que la parte tiene en la canción (`swam.stem_level_db`:
la potencia del stem mientras suenan las notas; `swam_render.gain`), no a un pico fijo, y nunca
sobre un pico de 0,97. Los controles 🎷 y 🎶 parten en 80 % y 70 %: con ellos ahí, el balance es el
de la canción. Careless Whisper: «Otros» suena a −18,5 dB; antes el saxo salía a −14,1 dB (4,4 dB
más fuerte que el original), ahora a −18,5 dB.
**Velocidad de práctica**: al 25, 50 o 70 % SWAM toca la línea a esa velocidad él mismo
(`swam._at_speed`: las notas y sus curvas más largas), en vez de que el navegador estire la
grabación: el ataque de cada nota, la entrada del aire (60 ms) y las transiciones duran lo suyo.
Es otra grabación por velocidad (la del 50 % dura y pesa el doble); mientras se hace suena la que
hay, estirada («⟳ grabando al 50 %…»). Medido con Careless Whisper: lista en 28 s, el saxo a
velocidad 1 con la canción a 0,5, desfase máximo 48 ms; de vuelta al 100 %, la grabación ya hecha
en 0,7 s.
Variables: `STEMDECK_SWAM_DIR`, `STEMDECK_SWAM_PYTHON`, `STEMDECK_SWAM_OFF=1`.

**Las notas de la voz** (sin RMVPE) no salen solo del modelo de transcripción (Basic Pitch, hecho para
instrumentos): se revisan contra un seguidor de tono (pYIN) que lee la voz nota por nota
(`app/score/voice_line.py`, `GET /api/jobs/{id}/sax/line/vocals`, se guarda en
`score/vocals/sax_line.json`; la primera vez tarda ~1-2 min en una canción de 3-4 min). Donde
discrepan por 1 a 5 semitonos manda el seguidor (salvo una octava exacta: ahí el seguidor suele
engancharse al bajo que queda en el stem), y donde el modelo no vio nada se agregan las notas del
seguidor. Medido en la voz de «Esta noche» (90 s): con el modelo solo, el 71 % del canto tenía
nota y el 85 % de eso estaba en el tono que mide el seguidor; ahora el 87 % tiene nota y coincide
el 85-95 %. En voces sintéticas con vibrato, deslizamientos, sala y el resto de la banda colado
(notas conocidas): 80/79/66 % de notas acertadas antes, 81/84/79 % ahora.

**Fraseo** (arriba): *Ligado* (por defecto) toca la línea como un saxofonista: una nota sostenida
en vez de sus pedazos (la transcripción corta una nota cantada en cada sílaba o bajón de volumen),
sin adornos de menos de ~0,1 s ni notas sueltas que saltan lejos de lo que suena alrededor (lo que
queda de la banda en el stem; un salto de octava se devuelve a su octava), y los silencios
mínimos ligados; las notas ligadas suenan sin un nuevo ataque. El piano (y la guitarra, otros) se
liga con márgenes más amplios que la voz: su acompañamiento son golpes cortos. *Todas las notas*:
tal como salieron, para comparar. Medido en «Y dime» (Agrupación Marilyn): voz de 407 a 255 notas
(130 eran una nota partida, 22 sueltas; notas de menos de 0,15 s del 18 al 8 %), piano de 568 a
420 (cortas del 30 al 8 %, sueltas de 48 a 15), sin perder tiempo con nota (99 → 104 s y
115 → 124 s).

**Rapidez:** la línea de una voz ya no espera la partitura completa (pulso, notas fantasma y
grabado eran ~35 s que el saxo no usa): el servidor transcribe y sigue el tono a la vez, el
seguimiento repartido en 8 procesos a 16 kHz. «Y dime» (3:16): de más de 100 s a 10 s la primera
vez, y al instante después. Además se calcula sola en segundo plano después de cada separación y,
al arrancar el servidor, la de todas las canciones con voz (`STEMDECK_SAX_AUTO=0` lo apaga).

**El piano toca su mano derecha** (la del modelo de manos): con las dos manos se colaban el bajo y
los acordes (intrusas en «Y dime» de 48 a 10, en «Barbarossa» de 27 a 10). Si la parte elegida
salta mucho (más del 35 % de saltos de 7 semitonos o más), avisa: es acompañamiento, no melodía
(el piano de «Esta noche», 49 %), y la melodía suele estar en la voz.

**Ninguna nota muda:** dos tercios de las notas grabadas empezaban en crescendo (hasta 1 s hasta
sonar) y las suaves (pp) estaban ~35 dB abajo: una nota corta de una canción terminaba antes de
oírse. Ahora cada nota grabada empieza donde suena (la mitad de su volumen en 17 ms de mediana,
0,11 s como máximo) y la grabación suave solo se usa para notas muy suaves. Comprobado tocando
las 384 combinaciones (cada nota de los dos saxos, 3 intensidades, 0,1 y 0,25 s): ninguna muda.

**Afinación:** se mide la afinación de la voz (o la del stem en la partitura) y el saxo toca en
ella: una grabación unos cents corrida sonaba desafinada contra un saxo en La 440.

**Notas: Para el saxo / Como suenan.** «Para el saxo» muestra lo que lee un saxofonista (un Alto
lee una sexta mayor más arriba de lo que suena: un Do de la canción es un La en el Alto), con
«suena …» debajo. «Como suenan» muestra las notas reales de la canción (las de un piano), con «en
tu saxo: …» debajo. La digitación siempre es la de tu saxo.

**El saxo**: una foto real de un Yamaha YAS-62 (Wikimedia Commons, CC BY-SA 4.0; créditos en
`static/img/sax/NOTICE.txt`), con las llaves que se pisan encendidas encima, en su lugar exacto, y
las de la nota siguiente con un anillo.

**Qué se oye** (abajo, «Escuchar»): *Saxo + resto de la canción* (los demás stems, sin los que toca
el saxo: `GET /api/jobs/{id}/sax/backing.flac?without=vocals,piano`), *Solo saxo* o *Canción
original* (para comparar). Volumen del saxo 🎷 y del resto 🎶 por separado. **El saxo es
grabado**: cada nota de un saxofón alto y uno soprano reales (University of Iowa, Musical Instrument
Samples, intérprete Michael Giles; «libres para cualquier proyecto, sin restricciones»), con
vibrato y en tres intensidades (pp, mf, ff) según la fuerza de cada nota, en una sala suave; las
notas más largas que la grabación siguen con su parte sostenida. El Tenor y el Barítono usan las
notas del Alto llevadas a su altura (no hay grabaciones de esos dos). Las muestras se regeneran
con `scripts/sax/build_samples.py` (`static/audio/sax/`, 8,5 MB). Mientras cargan, suena un saxo
sintetizado. Velocidad 25 / 50 / 70 / 100 % sin cambiar la afinación; − / ＋ cuántos segundos de
notas se ven; un clic en el carril salta a ese momento (sobre una nota, a su comienzo); Espacio
reproduce o pausa; ← / → 5 s. Cambiar los stems o «Escuchar» mientras suena sigue sonando desde
el mismo punto (antes se quedaba pegado hasta recargar).

## Desde el celular o la tablet

En el mezclador del celular:

- **Letra:** si la canción tiene letra guardada (la que encontró el servidor, o la que
  sincronizaste en el escritorio), una franja bajo los botones muestra la línea que se canta y
  la siguiente; la pestaña **Letra** muestra toda, con la línea actual iluminada y centrada.
  Tocar una línea va a ese momento. Sin letra, **Buscar la letra** la pide al servidor. La letra
  elegida solo en el navegador del escritorio (sin guardarla en el servidor) no llega al celular.
- **🔒 (al lado de «siguiente»):** un toque bloquea todo menos **▶/❚❚** y **siguiente** (y el
  cambio de pestaña Stems / Letra / Analysis, que no altera la canción): volumen, mute/solo,
  velocidad, tono, barra de tiempo, biblioteca y 𝄞 no responden. Para desbloquear, **mantén
  pulsado** el candado ~1 s (un toque suelto no lo quita).
- **𝄞** abre la partitura en el momento en que va la canción y pausa el mezclador.

StemDeck no atiende por `http://` a otros equipos: el cambio de tono (transpose) necesita un
origen seguro, y en vez de servir una app a medias responde «StemDeck needs an https://
address». Por eso el acceso «compartir en red» hace lo mismo que la app de escritorio:

- Este PC usa `http://localhost:8001`, como siempre.
- Para la red levanta un segundo puerto con `https` (el primero libre desde 8443: un día un
  mitmproxy ocupaba el 8443 y quedó en 8444) y muestra la dirección en su ventana, por ejemplo
  `https://192.168.1.43:8443/mobile/`, y abre un código QR con ella para la tablet.
- El certificado es autofirmado, para las IP de este PC. Se crea con el `openssl` de Git en
  `.run/certs/` (git lo ignora) y se rehace solo si cambia la IP. La primera vez el navegador de
  la tablet avisa que no es de confianza: **Avanzado → Continuar**.

El firewall de Windows decide quién entra. La primera vez que el servidor escucha en la red,
Windows pregunta si permite el acceso a Python: acepta, y queda una regla para ese programa que
sirve para cualquier puerto. Si no apareció o la rechazaste, crea la regla en un PowerShell
abierto **como administrador** (sin eso da «Acceso denegado»):

```powershell
New-NetFirewallRule -DisplayName "StemDeck dev (red local)" -Direction Inbound -Protocol TCP -LocalPort 8443-8450 -RemoteAddress LocalSubnet -Action Allow
```

## Modo dev en Windows

En Windows, uvicorn con `--reload` usa un event loop sin soporte de subprocesos, así que todo
lo que pasa por ffmpeg (MP3 de stems, mezclas) devuelve 500. Con `--loop
asyncio:ProactorEventLoop` los subprocesos funcionan, pero entonces `--reload` falla desde la
segunda recarga (`WinError 87`: el socket heredado ya está asociado a otro IOCP). Arráncalo
sin `--reload`, como hace `run.sh` por defecto. El frontend (`static/`) se sirve sin caché,
así que sus cambios se ven al recargar la página; los cambios de backend requieren reiniciar.

```bash
.venv/Scripts/uvicorn.exe app.main:app --host 127.0.0.1 --port 8001 --loop asyncio:ProactorEventLoop
```
