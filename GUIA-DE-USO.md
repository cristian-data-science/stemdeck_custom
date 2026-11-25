# Guía de uso de StemDeck (versión con partitura)

Guía para usar la aplicación, sin detalles técnicos. Si algo de la instalación falla, la persona
que te ayude con eso tiene todo en [DOCUMENTACION-TECNICA.md](DOCUMENTACION-TECNICA.md).

## ¿Qué hace?

Le das una canción (un archivo de audio o un link de YouTube) y la app:

1. **La separa en instrumentos:** voz, batería, bajo, piano, guitarra y el resto, cada uno por
   separado.
2. Te deja **escucharlos como quieras:** bajar o quitar un instrumento (por ejemplo, quitar el
   piano para tocarlo tú encima), ir más lento o cambiar el tono.
3. **Escribe la partitura** de un instrumento (sobre todo el piano), con el nombre de cada nota,
   y la reproduce iluminando lo que suena, para practicar.
4. Convierte una parte de la canción (por ejemplo, la voz) en una **línea de saxofón** para
   tocarla encima.

Todo funciona en tu computador. Las canciones no se suben a ningún sitio.

## ¿Qué necesito?

- Un computador con **Windows 10 u 11**.
- Que alguien la instale la primera vez (son unos pocos pasos técnicos; ya están escritos).
- **Internet la primera vez:** la app descarga sola unos "cerebros" (modelos) que necesita para
  separar y escribir notas. Solo pasa una vez.
- Espacio libre en el disco: unos cuantos GB.

## ¿Necesito una tarjeta de video NVIDIA?

**No.** Si tu computador no tiene una tarjeta de video NVIDIA, la app usa el procesador del
computador y hace exactamente lo mismo. La diferencia es el tiempo de espera:

| Lo que hace | Con tarjeta NVIDIA | Sin tarjeta NVIDIA (procesador) |
|---|---|---|
| Separar una canción de 4 minutos | menos de 1 minuto | de 1 a varios minutos, según el computador |
| Escribir la partitura del piano | segundos | más o menos lo que dura la canción |
| Partitura de bajo, guitarra o voz | segundos | segundos |

Son tiempos aproximados: dependen de lo rápido que sea tu computador.

Al abrir la app sin tarjeta NVIDIA vas a ver un aviso en amarillo que dice que todo correrá en el
procesador. **Es normal; no tienes que hacer nada.**

## Abrir y cerrar la app

1. Abre la carpeta del proyecto.
2. Haz doble clic en **`Iniciar StemDeck dev.cmd`**.
3. Se abre una ventana negra (no la cierres: es la app funcionando) y, después de unos segundos,
   el navegador con StemDeck.
4. Para cerrar la app, cierra esa ventana negra.

Si el navegador no se abre solo, escribe en la barra de direcciones: `http://localhost:8001`

## Separar una canción

1. En la parte de arriba, en el cuadro **«Busca o suelta un archivo de audio…»**, haz una de estas
   cosas:
   - arrastra un archivo de audio (MP3, WAV…) desde tu computador, o
   - pega un link de YouTube, o
   - escribe el nombre de la canción para buscarla.
2. Elige qué quieres separar (**Todo** es lo normal).
3. Pulsa **Extraer stems** ("stems" = las pistas de cada instrumento).
4. Espera. Una barra muestra el avance. Cuando termina, la canción queda guardada en la
   **Biblioteca** y se abre el mezclador.

## El mezclador: practicar con la canción

- Cada instrumento tiene su propia fila, con su volumen. Puedes **silenciar** uno o dejar **solo**
  uno para oírlo aislado.
- **Velocidad:** más lento para estudiar un pasaje, sin que cambie el tono.
- **Tonalidad global:** sube o baja el tono de toda la canción.
- **Bucle:** repite un trozo una y otra vez.
- Barra espaciadora: reproducir o pausar.

## La partitura

1. En el mezclador, en la fila del **Piano**, pulsa el botón **𝄞**. Se abre la partitura en otra
   pestaña. (Bajo, guitarra, voz y otros tienen el mismo botón).
2. Pulsa **Extraer MIDI y generar partitura**. La primera vez tarda más porque descarga lo que
   necesita.
3. Ya tienes la partitura. Con **▶ Reproducir**, la nota que suena se ilumina y la hoja avanza
   sola.
4. Puedes ver el **nombre de cada nota** (do, re, mi…) desde el panel de ajustes de arriba,
   opción **Nombres**.
5. Hay una vista de **piano con notas cayendo**, para practicar **mano por mano**, más lento, y
   repetir un trozo.
6. Si una nota quedó mal, puedes corregirla: los cambios se guardan solos.

**Para comprobar que todo funciona** sin usar una canción tuya: abre `http://localhost:8001/score/`,
pulsa **Crear canción de calibración** y luego **Extraer MIDI y generar partitura**. Arriba
aparece una comprobación con ✓ si todo está bien.

La partitura sale de "escuchar" la grabación, así que no siempre es perfecta: con piano solo
suele quedar muy bien; con muchos instrumentos mezclados puede tener errores.

## El saxo 🎷

En el mezclador, el botón **🎷** (arriba, al lado de «Mezclador») abre la vista de saxo. Eliges qué
parte de la canción toca el saxo (por ejemplo, la voz) y la app la convierte en una línea de saxo
que puedes escuchar, ver como notas y practicar encima.

## Usarla desde el celular o la tablet

1. Celular/tablet y computador tienen que estar en la **misma red Wi-Fi**.
2. En el computador, haz doble clic en **`Compartir StemDeck en la red.cmd`** (en vez del otro).
3. La ventana muestra una dirección que empieza con `https://` y se abre un **código QR**.
4. Escanea el código QR con el celular o la tablet.
5. La primera vez, el navegador del celular avisa que la conexión "no es de confianza". Es normal
   (es tu propio computador): pulsa **Avanzado** y luego **Continuar**.
6. Si Windows pregunta si permites el acceso a la red, pulsa **Permitir**.

## Si algo no funciona

| Qué pasa | Qué hacer |
|---|---|
| La ventana negra se cierra sola o dice «No encuentro…» | La app no está instalada en ese computador. Pide ayuda con la documentación técnica |
| Aviso amarillo sobre el procesador | Normal si no tienes tarjeta NVIDIA. Sigue usando la app |
| Separar o escribir la partitura tarda mucho | Normal sin tarjeta NVIDIA. Deja la ventana abierta y espera |
| Un link de YouTube no se descarga | YouTube a veces bloquea las descargas. Usa un archivo de audio de la canción |
| El celular no se conecta | Revisa que estén en la misma Wi-Fi y que hayas abierto **Compartir StemDeck en la red.cmd** |
| La partitura tiene notas raras | Prueba con otra canción donde el instrumento se oiga más claro |

## Dos cuidados

- Usa la app con canciones para tu práctica personal; los derechos de las canciones son de sus
  autores.
- Si alguna vez aparece un archivo llamado `youtube-cookies.txt`, **no lo compartas con nadie**:
  da acceso a una cuenta de YouTube.
