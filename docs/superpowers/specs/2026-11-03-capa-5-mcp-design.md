# Capa 5: "Pregúntale a la pista", servidor MCP

Fecha: 2026-11-03, revisado el 2026-11-05 tras la comprobación del constructor. Autor del diseño: Claude, a partir de la conversación con Óscar. Spec
padre: `docs/superpowers/specs/2026-11-01-ventaja-design.md` (§2 opción D, §4, §7).

## 1. Intención

La capa 5 es la superficie D del spec: un servidor MCP local que expone `ventaja` como
herramientas para cualquier cliente de IA (Claude Desktop, Claude Code, Cursor...). La
inteligencia la pone el cliente del usuario; el repo no lleva ni pide API keys.

Lo que tiene que funcionar es una conversación de entrenador, en segundos y desde un clon limpio
con solo `uv sync`:

1. "¿Quién toma peores decisiones de tiro en el Breogán con el reloj agotándose?" → ranking
   filtrado por equipo y tramo de reloj (DeWayne Russell: 30 tiros, 7 con reloj 6-0, coste
   medio 0,37).
2. "Enséñame el peor tiro de Marco Spissu en el partido 191313 y dime qué tenía mejor." → la
   decisión con sus opciones, la mejor alternativa y el titular de la curva (coste 1,12, el
   segundo peor de los diez partidos).
3. "En esa jugada, si el base hubiera estado en la esquina, ¿cambia algo?" → la pizarra sin
   ratón: mover un jugador y revalorar sobre `decide_snapshot`.

Las preguntas se eligen sobre lo que hay: los 10 partidos con tracking no incluyen un
Barça-Madrid ni a todos los jugadores conocidos. El cliente debe saberlo por `list_games` y por
el glosario, y decirlo cuando le pregunten por alguien que no está.

Es también el tramo 50-60 s del vídeo de entrega (spec §7): el MCP contestando una pregunta en
lenguaje natural.

## 2. Objetivos, no-objetivos y anti-objetivos

### Objetivos

- Seis herramientas de lectura, pocas y gordas, que cubran las tres conversaciones de arriba
  y la ficha de jugador (§4).
- Un recurso de solo lectura con el glosario del método, para que el cliente explique bien y no
  se invente definiciones.
- Transporte stdio, arrancado con `ventaja mcp serve`. Configurable en Claude Desktop y Claude
  Code con un JSON de dos líneas que va en el README.
- Todo sale de los artefactos empaquetados (decisiones, curvas, fichas, frames, plantilla,
  priors), igual que la pizarra. Sin `data pull` ni `data build`.
- Cada herramienta tiene equivalente de CLI (`ventaja mcp call`), de modo que el servidor se
  prueba en CI sin cliente de IA.
- Probado con un cliente real (Claude Code en la máquina de Óscar) con las tres preguntas de §1
  y la transcripción guardada como evidencia.
- Cierre de capa como las anteriores: tests, ADR-0010, comando CLI, README, CLAUDE.md, CI.

### No-objetivos

- No hay herramientas de escritura ni de regeneración de artefactos: el MCP lee, no construye.
- No se expone el tracking crudo ni SQL libre. `ventaja sql` sigue existiendo en la CLI, pero
  no como herramienta MCP: necesita la build y abre la puerta a respuestas sin método.
- No se generan clips ni figuras desde el MCP (necesitan el tracking). Se devuelve el comando
  de la CLI que los produce.
- No hay transporte HTTP ni autenticación. Es un servidor local para una persona.
- No hay "prompts" MCP ni agentes dentro del servidor. El cliente decide cómo preguntar.

### Anti-objetivos (fracaso aunque funcione)

- Que el servidor exija una API key, una variable de entorno o una descarga para arrancar
  (spec §2, anti-objetivo explícito).
- Que una herramienta devuelva ids de jugador sin nombre, o números sin el titular ya redactado:
  el cliente acabaría calculando o inventando.
- Que el MCP sea un espejo de la CLI con un tool por subcomando (quince herramientas que el
  cliente no sabe combinar).
- Que la lógica viva en el servidor MCP y no en una capa de servicio probable sin él.
- Que el README pase de 1000 palabras o de 2 figuras al añadir esta sección.

## 3. Restricciones

- Las del spec padre (§3): solo datos de SkillCorner, open source, repo que arranca en limpio,
  Python ≥ 3.12, uv, ruff, mypy strict, pytest con `-W error` limpio, inglés en código y README,
  ADRs en castellano, commits convencionales.
- SDK oficial `mcp` para Python (PyPI `mcp`, versión 2.3.0 a 2026-11-05; en 2.x `FastMCP` se
  llama `MCPServer`, en `mcp.server.mcpserver`, y el cliente en memoria es `mcp.client.Client`).
  Dependencia de ejecución nueva, `mcp>=2.3`. Comprobado: depende de `httpx2`, que ya es dev dep,
  y `uv lock` resuelve sin conflicto.
- Presupuesto del README: hoy 987 palabras y 2 figuras. La sección nueva entra recortando otras;
  sin figura nueva.
- `decide_snapshot` (ADR-0009) es el único punto de entrada de valoración. El `what_if` reutiliza
  `Board` de `board/engine.py`; no se duplica geometría.
- Constantes nuevas en `value/params.py` y cambian con ADR.

## 4. Las herramientas

Nombres, descripciones y campos de salida en inglés (el cliente y el jurado leen inglés). Los
ids de jugador y equipo se devuelven siempre acompañados de su nombre. Los flotantes se redondean
a 3 decimales. Toda salida es JSON estructurado (modelos pydantic con `model_dump`), no texto
libre: el cliente redacta, el servidor no.

Convenciones de entrada compartidas:

- `player` y `team` aceptan un id numérico o un trozo del nombre, sin distinguir mayúsculas ni
  acentos (misma regla que `find_player` y `player team` en la CLI). Si la búsqueda es ambigua o
  vacía, la herramienta falla con un mensaje que lista los candidatos (`id — name — team`), nunca
  elige por el usuario.
- `game` acepta el id del partido.
- `clock` es un tramo del reloj de posesión: `"24-14"`, `"14-6"` o `"6-0"`, los mismos de las
  fichas (capa 3). Omitido: toda la posesión.
- `limit` por defecto `MCP_DEFAULT_LIMIT = 10`, máximo `MCP_MAX_LIMIT = 50`.
- `min_shots` por defecto 1, como `player rank` en la CLI, y cuenta tiros valorados (`n_shots`;
  con `clock`, los del tramo). Cada fila lleva su `n`, y el glosario le dice al cliente que
  cualquier afirmación con menos de `PROFILE_MIN_SHOTS` = 8 tiros legibles va con cautela.
  Coherente con la capa 3 (ficha desde 1 tiro, afirmaciones solo con ≥ 8 legibles).

| Herramienta | Entrada | Salida | CLI equivalente |
|---|---|---|---|
| `list_games` | — | los partidos con tracking: `game_id`, `date`, `home` y `away` (id, nombre, puntos), `valued_shots` | solo `mcp call list_games` |
| `rank_players` | `team?`, `clock?`, `min_shots?`, `by?` (`mean_cost` \| `good_read_share` \| `late_held_share`, defecto `mean_cost`), `limit?` | lista ordenada con `rank`, jugador, equipo, `n_shots`, `n_readable`, las tres métricas globales y, con `clock`, `clock_n` y `clock_cost` del tramo; más la fila `league` como referencia | `player rank` |
| `player_profile` | `player` | la ficha: identidad, partidos, totales (valor del tiro, mejor alternativa, coste, lectura), coste por tramo de reloj, alternativa más ignorada, retrasos, bloque de temporada frente a la liga, y `phrase` (inglés) | `player show --lang en` |
| `find_shots` | `player?`, `team?`, `opponent?`, `game?`, `clock?`, `verdict?` (`late` \| `during` \| `none` \| `no_window`), `good_read?`, `min_cost?`, `limit?` | tiros ordenados por coste descendente: `shot_id`, partido, periodo, reloj, tirador, `shot_value`, mejor alternativa (jugador, tipo, valor), `cost`, `good_read`, `verdict`, `headline` (inglés) | `decisions show` / `reel rankings` |
| `explain_shot` | `shot_id` | una decisión completa: cabecera (partido, periodo, reloj, regla del frame, confianza), el tiro tomado (zona, puntos, valor), las cinco opciones con nombre, tipo, zona, probabilidad, valor, viabilidad y valor ajustado, marcando `is_shot` e `is_best_alternative`; `cost`, `good_read`; la curva resumida (`verdict`, `advantage_seconds`, `release_lag_seconds`, quién tuvo la ventaja, `headline`); y `clip_command`, el comando de la CLI que renderiza el clip | `decisions show` + `curves show` |
| `what_if` | `shot_id`, `moves`: lista de hasta `BOARD_MAX_MOVES` = 10 de `{player, x, y}` (pies, orientación de ataque, aro en (−40.7, 0)) | `before` y `after` con la misma forma (`shot_value`, `best_alternative`, `cost`, `good_read`, opciones), `delta_cost`, y la lista de jugadores con posición final y `moved` | `board` (API `POST /api/shot/{id}/evaluate`) |

Reglas de `what_if`: las de la pizarra (ADR-0009), sin excepción: jugador movido con velocidad 0,
el balón sigue al tirador, tirador movido valorado por geometría, recorte a la media pista de
ataque, máximo 10 movimientos. `player` en cada movimiento admite id o nombre, resuelto entre los
diez del frame. Las coordenadas fuera de rango se recortan y la respuesta devuelve la posición
efectiva, para que el cliente vea el recorte.

Reglas de `find_shots`: filtra sobre los tiros valorados (`rule != "excluded"`); `verdict` y
`headline` salen del resumen de curvas; un tiro sin resumen devuelve `verdict = null`. `player`
filtra por tirador; `team` es el equipo del tirador y `opponent` el rival en ese partido (los dos
equipos de un partido salen de `games.parquet`). `clock` usa los mismos cortes que las fichas; un
tiro con reloj desconocido no entra en ningún tramo.

Reglas de `rank_players`: excluye la fila LIGA; con `clock` ordena por el coste del tramo
(`clock_{tramo}_cost` de la ficha) y exige `min_shots` en ese tramo (`clock_{tramo}_n`); las
fichas no guardan lectura ni retraso por tramo, así que `clock` combinado con `by` distinto de
`mean_cost` es un error con ese mensaje, y el servidor no reagrega decisiones (decisión mía). Con
`team` ordena solo la plantilla; devuelve siempre la fila de la liga aparte, con la misma
métrica, para que el cliente pueda decir "frente a 0,16 de la liga".

Resolución de nombres (decisión mía): cuando un `team` no casa con ningún equipo, el error lista
los equipos con su id (son 17), y el cliente reintenta; así "Barça" (que `fold_name` convierte en
"barca", no subcadena de "BC Barcelona") no deja al cliente sin salida. Un `player` que no está
entre los diez del frame en `what_if` es un `VentajaError` que lista los diez, no el `KeyError`
de `Board.move`.

### El recurso

`ventaja://glossary`, Markdown en inglés, una plantilla en el paquete (`mcp/glossary.md`) que se
rellena al servirla con los valores de `value/params.py` (decisión mía): qué es
el frame de decisión, el valor de una opción, la viabilidad, el coste de decisión, `good_read`,
los veredictos de la curva, los tramos de reloj, `confidence`, los umbrales de la ficha
(`PROFILE_MIN_SHOTS`, `LATE_MIN_CLOCK`...) y los límites conocidos (defensa que no reacciona,
10 partidos, modelo de 2026-11). Enlaza a los ADRs por nombre. Cualquier número que cite sale de
`value/params.py`, importado, no copiado.

## 5. Arquitectura

```
src/ventaja/mcp/
    __init__.py
    service.py      # funciones puras: list_games(), rank_players(...), ... -> modelos pydantic
    models.py       # los modelos de salida (GameInfo, RankedPlayer, ShotSummary, ShotExplanation, WhatIf...)
    server.py       # FastMCP: registra las 6 tools y el recurso; traduce VentajaError -> error de tool
    glossary.md
src/ventaja/cli/mcp.py   # `ventaja mcp serve`, `ventaja mcp call TOOL [JSON]`, `ventaja mcp tools`
```

- `service.py` no importa `mcp`. Es lo que prueban los tests y lo que llama la CLI. Carga los
  artefactos una vez por proceso (`AskService(settings)` con un `Board` dentro para `what_if`,
  y las tablas de decisiones, resúmenes, fichas y plantilla en memoria: todo suma menos de 2 MB).
- `server.py` es fino: una función por tool que valida la entrada con pydantic, llama al
  servicio y devuelve `model_dump()`. Los `VentajaError` (no encontrado, ambiguo, excluido) se
  reportan como error de la herramienta con el mensaje tal cual, nunca como traza.
- Los nombres de jugador y equipo se resuelven con la misma cadena que la pizarra (plantilla →
  `meta/` → fichas), reutilizando lo que `Board._load_meta` ya hace; si hay que extraerlo a
  `data/load.py` para compartirlo, se extrae.
- `ventaja mcp serve` arranca stdio con importaciones perezosas (como `board`). `ventaja mcp
  call rank_players '{"team": "Barcelona", "clock": "6-0"}'` imprime el JSON de la misma
  función de servicio, y `ventaja mcp tools` lista las herramientas con su esquema de entrada.
  Esa es la equivalencia de CLI que pide el spec, de una vez para las seis.

### Lista de partidos desde un clon limpio (decisión mía)

Hoy la fecha, los equipos y el marcador de un partido solo están en `matches.json` y en
`meta/games`, que no se empaquetan. `ventaja player build` (que ya lee `meta/` y no necesita
tracking) escribirá además `artifacts/games.parquet`, junto a `players.parquet` y
`teams.parquet`: un partido por fila con `game_id`, `date`, `home_team_id`, `home_team`,
`away_team_id`, `away_team`, `home_score`, `away_score`. Unos cientos de bytes. `list_games` lo
lee, `find_shots` saca de él el rival, y `data/load.py` lo expone con `load_games`. No hay plan B
sin el fichero: va versionado, como las fichas. El orden de regeneración de CLAUDE.md lo recoge.

### Qué artefactos lee el servicio (decisión mía)

Las mismas reglas que la pizarra: cada tabla se resuelve con `artifact_dir` (la build si tiene
esa tabla, si no la copia empaquetada). Una build parcial mezcla fuentes (por ejemplo, decisiones
de un partido con fichas de diez); el ADR lo documenta como límite y los pasos de CI que llaman
al MCP corren con `VENTAJA_BUILD_DIR` apuntando a un directorio vacío, para leer siempre lo
empaquetado.

## 6. Pruebas y prueba con cliente real

- Unitarias sobre `service.py` con los artefactos empaquetados (sin build): cada herramienta con
  sus filtros, la ambigüedad de nombres, el error de tiro excluido, el recorte de coordenadas, y
  que `what_if` sin movimientos reproduce `before == after` y la fila de `decisions` (a 1e-6,
  como el test de la pizarra).
- Un test de servidor con cliente MCP en memoria del propio SDK (sesión conectada
  servidor-cliente sin subproceso): `list_tools` devuelve las seis con esquema, `read_resource`
  del glosario, y una llamada a cada tool por el protocolo. Si el SDK 2.x no trae ese helper, el
  test arranca `ventaja mcp serve` como subproceso stdio con el cliente del SDK.
- CI: `uv run ventaja mcp call list_games` y `uv run ventaja mcp call explain_shot
  '{"shot_id": "shot-114243-1-0"}'` en el job `pipeline`, con `VENTAJA_BUILD_DIR` vacío (ver
  §5); el job `quality` ejecuta los tests.
- Prueba con cliente real, hecha por el controlador antes de cerrar la capa: registrar el
  servidor en Claude Code de esta máquina (`claude mcp add ventaja -- uv run --directory
  <repo> ventaja mcp serve`), hacer las tres preguntas de §1 y guardar la transcripción (pregunta,
  herramientas llamadas con sus argumentos, respuesta) en `docs/review/2026-11-mcp/transcript.md`.
  Se comprueba que el cliente no inventa cifras: cada número de la respuesta tiene que estar en
  la salida de una herramienta.

## 7. Documentación y cierre

- ADR-0010 (castellano): por qué seis herramientas y no quince, stdio, artefactos empaquetados,
  `games.parquet`, mínimo de tiros, límites (build parcial, defensa que no reacciona).
- README: sección "Ask the court" con el snippet de configuración de Claude Desktop / Claude
  Code y una pregunta de ejemplo con su respuesta corta. Recortar donde haga falta para quedarse
  en ≤ 1000 palabras; nada de figura nueva.
- CLAUDE.md: comandos `mcp serve|call|tools`, el módulo `mcp/`, las constantes nuevas
  (`MCP_DEFAULT_LIMIT`, `MCP_MAX_LIMIT`), `player build` escribe también `games.parquet`.
- Etiqueta `capa-5-cerrada` tras el merge.

## 8. Lo que queda al constructor

- La forma exacta de los modelos pydantic de salida (nombres de campo en inglés, estables,
  documentados en el esquema de la tool).
- Cómo compartir la resolución de nombres entre `Board` y el servicio sin duplicar.
- La versión concreta de `mcp` y cómo se cuadra con `httpx`/`httpx2`.
- El helper de cliente en memoria del SDK para el test de protocolo.
- Las descripciones de cada tool (una o dos frases, en inglés, que digan cuándo usarla y qué
  no hace), que son lo que el cliente de IA lee para elegir.
