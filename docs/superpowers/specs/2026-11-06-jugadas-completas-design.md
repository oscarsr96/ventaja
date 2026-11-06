# Jugadas completas en la app

Fecha: 2026-11-06. Autor: Claude, a partir de la conversación con Óscar. Antecedentes: ADR-0009
(frames de decisión empaquetados), ADR-0011 (app unificada).

## 1. Intención

Óscar: "¿Por qué las jugadas no son una secuencia? Solo aparece el frame de la decisión; yo
quiero que se vean las jugadas completas." Hoy la app solo lleva el frame de decisión (11 filas
por tiro) porque el tracking (≈ 380 MB en LFS) no se empaqueta, y los clips del reel exigen
tenerlo descargado. La curva de ventaja ya cubre la posesión entera; falta el movimiento.

Decisiones de Óscar: **25 fps** y **la posesión entera** (desde que entra en pista delantera,
el mismo inicio que la curva, hasta un segundo después de la suelta). Coste medido: ≈ 25 MB en
el repo para los 1 351 tiros valorados (media de 9 s por jugada, máximo 20 s).

## 2. Objetivos, no-objetivos, anti-objetivos

- **Objetivos**: un artefacto `artifacts/plays/{game}.parquet` con las jugadas; una ruta
  `GET /api/play/{shot_id}`; en la vista Tiro, una línea de tiempo bajo la pizarra (play,
  pausa, arrastre, saltar a la decisión) que mueve las figuras en la 2.5D (y en 2D), lleva el
  balón donde está en el tracking y sincroniza un cursor sobre la curva de ventaja. El frame de
  decisión queda marcado y es el único en el que se puede arrastrar para el "y si". Todo desde
  un clon limpio con `uv sync`.
- **No-objetivos**: no se recalculan valores por frame (la curva ya los tiene, muestreados cada
  5 frames); no se interpola entre frames ausentes (se mantiene la última posición conocida);
  no se empaquetan jugadas de tiros excluidos; no se tocan los clips del reel (siguen siendo
  opcionales).
- **Anti-objetivos**: superar 30 MB de artefacto; que el arrastre deje de funcionar en el frame
  de decisión; que la pizarra pierda alguna capacidad; que el reproductor pida red o librerías.

## 3. Decisiones de diseño

- **Artefacto** `plays/{game}.parquet` (`PLAY_SCHEMA`): `shot_id String, frame_idx Int64,
  t Float32` (segundos respecto a la suelta: `(frame_idx − release_frame) / FPS`, negativos
  antes), `shot_clock Float32` (nulo si desconocido), `side String` (`offense | defense |
  ball`), `player_id Int64` (nulo en el balón), `x Float32, y Float32, z Float32` (balón;
  nulo en jugadores). Una fila por entidad y frame, en orientación de ataque como los frames;
  frames sin tracking ausentes. Ventana: del primer frame de la curva del tiro
  (`min(frame_idx)` en `artifacts/curves/{game}.parquet`) a `release_frame + FPS`. Lo escribe
  `ventaja frames build` junto a los frames (necesita decisiones, curvas y tracking), con
  `--no-plays` para saltarlo. Compresión zstd. Cargadores `load_plays`, `play_files`,
  `ArtifactKind "plays"`, mismo `artifact_dir` que el resto.
- **Ruta** `GET /api/play/{shot_id}` → `{"shot_id", "fps": 25, "t0", "t1", "decision_t",
  "release_t": 0.0, "frames": [{"t", "clock", "players": [[player_id, x, y], ...],
  "ball": [x, y, z] | null}, ...]}` ordenado por `t`; 404 `{"error"}` si el tiro no tiene
  jugada. Tamaño típico ≈ 60–150 KB por tiro.
- **Reproductor** (`play.js`, ≤ 600 líneas): barra bajo la pizarra con Play/Pause, "Decision"
  (salta al frame de decisión y vuelve al modo de arrastre), un `<input type=range>` sobre
  `[t0, t1]`, etiqueta de tiempo (`−3.2 s`) y reloj de posesión. Reproduce a tiempo real con
  `requestAnimationFrame`, eligiendo el frame más cercano a `t`. Al cargar un tiro: parado en el
  frame de decisión, modo de arrastre.
- **Pizarra**: `board.js` gana `showFrame(frame | null)`: con un frame, coloca las figuras por
  `player_id` (las ausentes mantienen su posición), el balón en su posición real (radio
  ligeramente mayor con la altura `z`), oculta los anillos de movidos y bloquea el arrastre;
  con `null`, restaura las posiciones de la decisión con los movimientos del usuario y vuelve a
  permitir arrastrar. Nada más cambia en la pizarra.
- **Curva**: `curve.js` gana `setCursor(t | null)`: línea vertical que sigue la reproducción.
- **Sin jugada** (clon con frames pero sin `plays/`, o tiro sin ventana de curva): la barra
  muestra "No play data: run `ventaja frames build` with the tracking" y la pizarra queda
  como hoy.
- **CI**: el paso `frames build --game 114243` ya produce las jugadas; el bloque de la app
  comprueba `/api/play/shot-114243-1-0`.
- **Documentación**: ADR-0012 (castellano); README dentro de 1000 palabras y 2 figuras;
  CLAUDE.md (orden de regeneración, tamaño del artefacto).

## 4. Lo que queda al constructor

La forma del bucle de reproducción, el aspecto de la barra, cómo escalar el balón con `z`, y
cómo iterar los snapshots orientados por frame (reutilizando lo que ya hace el renderizado de
clips en `viz/animate.py`).
