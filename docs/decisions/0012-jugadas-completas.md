# ADR-0012: jugadas completas a 25 fps en la vista Shot

## Contexto

La vista Shot (ADR-0011) enseñaba un solo fotograma, el de decisión, y la curva de ventaja a su lado. Óscar pidió ver la jugada entera, con el movimiento de los diez jugadores y el balón, y moverse por ella con un cursor sobre la curva. Los clips GIF del reel (`ventaja clip`) cubren una ventana corta, necesitan tracking y no se empaquetan; para que la app funcione desde un clon limpio, la jugada tenía que ir empaquetada como un artefacto más.

## Decisión

**25 fps y posesión completa, por elección de Óscar.** Se midieron los tamaños para los diez partidos: 25 fps son unos 25 MB (el real es 22,7 MB), 12,5 fps unos 13 MB y 5 fps unos 5 MB. La jugada media dura 9 s y la más larga 20 s. Se acepta el peso a cambio de reproducir cada fotograma rastreado, sin submuestrear.

**`PLAY_SCHEMA`** (`decision/frames.py`): una fila por entidad y fotograma, con `shot_id`, `frame_idx`, `t` (segundos desde el frame de suelta, negativo antes), `shot_clock` (nulo si se desconoce), `side` (`offense`, `defense` o `ball`), `player_id` (nulo en el balón), `x`, `y` y `z` (altura del balón; nulo en los jugadores). `t`, `shot_clock`, `x`, `y` y `z` son Float32. Las coordenadas van en orientación de ataque, como el resto de artefactos (ADR-0001).

**Ventana y posesión.** `build_plays` recorre cada tiro valorado (regla distinta de `excluded` y con curva) desde el primer frame de su curva hasta `release_frame + FPS` (un segundo tras la suelta) y escribe todos los frames rastreados, a 25 fps. Ruling R1: solo se conservan los frames de la posesión del propio tiro; la cola posterior a la suelta puede caer en la posesión siguiente, con la orientación invertida, y se descarta. El fichero es `artifacts/plays/{game}.parquet`, comprimido con zstd (22,7 MB en total para los diez partidos).

**Un solo comando.** `ventaja frames build` escribe los fotogramas de decisión y las jugadas; `--no-plays` omite estas últimas. Con `--out DIR`, las jugadas van a `DIR.parent/plays` si `DIR.name == "frames"` y a `DIR/plays` en otro caso. Dependen de las decisiones, las curvas y el tracking, así que se regeneran en el mismo paso que `frames/`. `load_plays` y `play_files` (`data/load.py`) las leen.

**La ruta.** `GET /api/play/{shot_id}` devuelve `{shot_id, fps, t0, t1, decision_t, release_t, frames: [{t, clock, players: [[id, x, y]], ball: [x, y, z] | null}]}`, con los frames ordenados por tiempo y los jugadores en orden ataque, defensa. `decision_t` es `(decision_frame − release_frame) / FPS`. Un tiro sin jugada (excluido, sin ventana de curva o partido sin `artifacts/plays/`) da 404 con `{"error": mensaje}`, como el resto de la API (ADR-0011). El servidor carga y particiona por tiro el parquet de un partido la primera vez que se pide.

**El reproductor** (`play.js`, módulo nuevo; `shot.js` solo lo monta). Barra con Reproducir/Pausa, un botón Decisión, un deslizador de paso 0,04 s (un frame) y las etiquetas de tiempo y reloj de posesión. La reproducción usa `requestAnimationFrame` a tiempo real, y el cursor de la curva (`curve.setCursor`) sigue el fotograma. Los cambios en `board.js` se limitan a `showFrame(frame)` (pinta un fotograma de la jugada, o con `null` vuelve al modo de arrastre), `isPlayback()` y el último fotograma mostrado. Ruling R2: `render()` vuelve a aplicar el último fotograma mostrado mientras dure la reproducción, de modo que el cambio 2D/2.5D conserva el fotograma elegido en el deslizador. El enrutado de `app.js` gana un gancho `leave()` por vista: al salir de Shot el bucle de animación se detiene.

**Regla de arrastre.** Los jugadores solo se arrastran en el fotograma de decisión. En cualquier otro fotograma de la jugada el arrastre se rechaza (`board.isPlayback()`). Al situar el deslizador a menos de medio fotograma de `decision_t`, o con el botón Decisión, se llama a `board.showFrame(null)`, que restaura el tablero de decisión y el modo de arrastre. Al cargar otro tiro o salir de la vista, `stop()` hace lo mismo. La reproducción no valora nada: los números visibles siguen saliendo de la API (ADR-0009).

## Consecuencias

El jurado ve la jugada completa sin descargar tracking. En CI, el job `pipeline` construye fotogramas y jugadas del partido 114243, y el bloque de humo de la app hace `curl --fail` a `/api/play/shot-114243-1-0`. `/static` se sirve con `no-cache`, de modo que tras un `git pull` basta recargar. `decide_snapshot` sigue siendo el único punto de valoración; no cambian las constantes ni los demás artefactos.

**Límites conocidos.**

- No se interpolan los huecos del tracking: una entidad sin dato conserva su última posición.
- No hay valoración por fotograma: la curva se muestrea cada 5 frames, y el cursor se mueve sobre ella.
- Unos 23 MB más en git (`artifacts/plays/`), que se regeneran con el tracking.
- Los tiros excluidos no tienen jugada.
- La ventana termina un segundo tras la suelta: no se ve el rebote ni la posesión siguiente.

**Alternativas descartadas.**

- *12,5 fps o 5 fps.* Ahorran 12 o 20 MB, pero un movimiento a trompicones oculta justo los pases y cortes que la curva intenta explicar; Óscar eligió los 25 fps.
- *Solo los últimos 8 segundos.* Corta el inicio de la posesión, donde la curva ya muestra ventajas; la ventana acompaña a la curva.
- *Clips GIF en el repo.* No se pueden recorrer fotograma a fotograma ni enlazar con el cursor de la curva, y el reel ya los deja fuera del repo (ADR-0011).
- *Servir el tracking en directo.* Exigiría descargar unos 380 MB y romper la regla de que la app funcione desde un clon limpio (ADR-0011).
