# ADR-0009: pizarra interactiva sobre frames de decisión empaquetados

## Contexto

El spec (§2, opción B) pide una pizarra: arrastrar a los jugadores en el frame de decisión de un tiro y ver al instante cómo cambia su valoración. El objetivo es que se pueda probar desde un clon limpio, sin descargar el tracking.

El problema es que las tablas de opciones (`artifacts/decisions/`) guardan el valor de cada pase, pero no los defensores ni las velocidades. Con ellas no se puede reconstruir un `Snapshot`, y sin `Snapshot` no se puede volver a valorar nada. El tracking sí lo tiene todo, pero pesa unos 380 MB y es justo lo que la pizarra no debe exigir.

## Decisión

**Un artefacto de frames.** `ventaja frames build [--game ID ... | --all] [--out PATH]` escribe `artifacts/frames/{game}.parquet`: el frame de decisión de cada tiro valorado, con los 10 jugadores y el balón (posición, velocidad y contexto de posesión: reloj, equipo en ataque, lado). Son 1 351 tiros × 11 filas = 14 861 filas, ≈ 640 KB para los diez partidos. `snapshot_from_frame` reconstruye el `Snapshot` sin tracking y falla si el frame no tiene 5 + 5 jugadores y un balón. Se regenera después de las decisiones y necesita el tracking.

**Plantilla.** `artifacts/frames/roster.parquet` (205 jugadores: id, nombre, dorsal, equipo, 5 KB) sale del mismo `frames build` a partir de `meta/`. Así la pizarra muestra nombres y dorsales reales desde un clon limpio (ruling R5). El orden de nombres es plantilla, luego `meta/` y luego fichas de jugador, y cada fuente solo rellena lo que falta.

**Priors empaquetados.** El valor de un pase usa los priors por jugador, que salen de la tabla de tiros agregada, y esa tabla no se versiona. `ventaja model train` escribe ahora `models/priors.parquet` junto al modelo (el agregado de tiros por jugador, 310 805 bytes) y `Priors.default()` lo lee (ruling R4). Los priors son una entrada del modelo versionado y viajan con él. Si hay agregados en la build, estos mandan.

**El motor reutiliza la capa 1.** `decide` se parte en dos: `decide_snapshot(snapshot, shot, priors, model, ...)` valora un `Snapshot` y devuelve una `Decision`, y `decide` solo lo construye desde el tracking. `board/engine.py` (`Board`: `shots`, `load`, `move`, `evaluate`, `payload`) llama a esa función y a nada más. Con cero movimientos reproduce la fila de `decisions` exactamente (test a 1e-6). `decide_snapshot` es además el punto de entrada único que reutilizará el servidor MCP de la capa 5.

**Reglas de la pizarra.**

- Un jugador arrastrado está colocado, no corriendo: `vx = vy = BOARD_MOVED_VELOCITY = 0` y velocidad 0.
- El balón sigue al tirador si este se mueve.
- Un tirador movido se valora desde su nueva posición: zona y puntos por geometría. Si no se mueve, se usan la zona y los puntos reales del tiro.
- Las posiciones se recortan a la media pista de ataque (`x ∈ [−HALF_LENGTH, 0]`, `|y| ≤ COURT_WIDTH/2`). La franja de campo propio se dibuja, pero no se modela: lo que se suelta ahí se queda en la línea de medio campo.
- Máximo `BOARD_MAX_MOVES = 10` movimientos por petición.

**Servidor y página.** FastAPI con una sola página HTML (`board/static/index.html`, SVG y JavaScript sin dependencias, 402 líneas). Rutas: `GET /`, `/api/court`, `/api/shots?game=`, `/api/shot/{id}` y `POST /api/shot/{id}/evaluate`. `ventaja board [--host] [--port 8765] [--game ...] [--no-open]` lo arranca en local (`BOARD_PORT = 8765`). Dependencias nuevas: `fastapi` y `uvicorn` (ejecución) y `httpx2` (desarrollo, cliente de test de starlette). El servidor se prueba con pytest en el job `quality`.

**No es un frontend de producto.** Es una herramienta para mirar y discutir un tiro. No hay build de JavaScript, ni framework, ni estado de usuario, y la página no debe pasar de 600 líneas.

## Consecuencias

El repositorio crece unos 0,65 MB (frames y plantilla) más 0,3 MB (priors). A cambio, `uv run ventaja board` funciona desde un clon limpio, sin `data pull` ni `data build`.

Orden de regeneración: `model train` (modelo y priors), `decisions build`, `curves build`, `player build` y `frames build`, que depende de las decisiones y del tracking. Nunca se editan a mano. Las constantes nuevas (`BOARD_MAX_MOVES`, `BOARD_MOVED_VELOCITY`, `BOARD_PORT`) viven en `value/params.py` y cambian solo con un ADR.

**Límites conocidos.**

- La curva de ventaja y el frame de decisión no se recalculan al mover: la pizarra valora el frame fijado, no la posesión.
- La defensa no reacciona. Mover a un atacante no mueve a su marcador.
- El balón del frame suele ser ruido de tracking sin detectar, así que se dibuja en el tirador.
- Un jugador colocado tiene velocidad 0, lo que no equivale a la carrera que llevaba. Un pase desde un jugador parado se valora distinto que desde uno lanzado.
- La tabla de opciones se calcula con un modelo entrenado con 10 partidos (ADR-0004), y los movimientos lejos de las posiciones vistas extrapolan.

**Alternativas descartadas.**

- *Leer el tracking en cada petición.* Obliga a descargar unos 380 MB y vuelve lento cada arrastre.
- *Ampliar las tablas de opciones con defensores y velocidades.* Mezcla dos artefactos con ciclos distintos y no sirve para reconstruir el `Snapshot` completo.
- *Un frontend con framework (React, Vite).* Añade un build y dependencias a una herramienta de inspección; el spec lo excluye como no-objetivo.
- *Derivar los priors en cada arranque.* Necesita los agregados de temporada, que no se empaquetan.

## Enmienda 2026-11-05: vista 2.5D

La pizarra dibuja por defecto una vista 2.5D del medio campo, con un selector 2D / 2.5D (se recuerda en `localStorage`).

- **Proyección isométrica paralela, no perspectiva.** Las distancias y el arrastre siguen siendo exactos: una matriz afín fija convierte pies en pantalla y su inversa devuelve el puntero a pies.
- **Dos grupos SVG.** `#ground` contiene todo lo que está en el suelo (pista, flecha, sombra y anillo de movido), siempre en pies y con una sola matriz (`matrix(0.25 -0.55 -1 0 ...)` en 2.5D, identidad en 2D). `#figures` contiene las siluetas y el balón en espacio de pantalla, colocados con la misma proyección y ordenados por profundidad. El arrastre usa `ground.getScreenCTM().inverse()`, así que la geometría enviada a la API no cambia.
- **Las siluetas son una convención visual.** La altura no es un dato: el tracking es 2D, y la leyenda lo dice.
- **Sin dependencias.** La página sigue siendo un único HTML con SVG y JS sin build, de 600 líneas o menos.
