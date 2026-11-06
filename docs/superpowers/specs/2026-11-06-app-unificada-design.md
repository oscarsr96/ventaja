# App unificada: una página para todo lo entregable

Fecha: 2026-11-06. Autor del diseño: Claude, a partir de la conversación con Óscar. Spec padre:
`docs/superpowers/specs/2026-11-01-ventaja-design.md`. Antecedentes: ADR-0009 (pizarra, con la
enmienda 2.5D del 2026-11-05) y ADR-0010 (servidor MCP y `AskService`).

## 1. Intención

Hoy cada superficie se abre por un sitio: la pizarra en el navegador, las fichas y rankings por
terminal, las curvas como PNG, los clips como GIF en `docs/reel/`, el MCP desde Claude. Óscar
quiere **una sola página local** que lo reúna, para que el jurado abra una cosa y para grabar el
vídeo sobre una única pantalla.

Decisión de Óscar: la página abre por **un tiro concreto, con su pizarra y su curva** (la
historia "¿era el mejor tiro que había?"), y desde ahí se sube a jugador, partido y liga.

El principio de diseño que lo sostiene: **la página, la CLI y el MCP dan la misma respuesta**,
porque los tres llaman al mismo servicio (`AskService`, capa 5) y al mismo motor (`Board`,
capa 4). La app no añade lógica de valoración: la enseña.

## 2. Objetivos, no-objetivos y anti-objetivos

### Objetivos

- `uv run ventaja app` arranca un servidor local y abre una página con cinco vistas: **Tiro**,
  **Jugadores**, **Partidos**, **Pregunta** (las herramientas del MCP) y **Acerca de**.
- Todo funciona desde un clon limpio con `uv sync`, sin tracking, sin API key, sin build de
  JavaScript, sin framework: HTML, CSS y módulos ES servidos tal cual por FastAPI.
- La vista Tiro reúne la pizarra 2.5D actual, la curva de ventaja de la posesión dibujada en
  SVG desde `artifacts/curves/`, la cabecera, el titular, la tabla de opciones y el clip si existe.
- La pizarra se conserva funcionalmente igual (arrastre, revaloración, deshacer, 2D/2.5D).
- Cierre como capa: tests, ADR-0011, comando CLI, README, CLAUDE.md, CI.

### No-objetivos

- Ningún chat ni modelo de lenguaje dentro de la página: el repo no puede exigir una API key
  (spec padre, anti-objetivo). El chat real es Claude Desktop o Claude Code con el MCP; la
  vista Pregunta ofrece las seis herramientas como formularios y explica cómo conectar el MCP.
- No se generan clips ni figuras desde la página: necesitan tracking. Se muestran si existen.
- Sin autenticación, sin estado de usuario en servidor, sin despliegue público.
- No es un frontend de producto (ADR-0009): sin framework, sin bundler, sin paquetes npm.

### Anti-objetivos

- Que la app deje de funcionar en un clon limpio o tarde más de 3 s en servir la primera vista.
- Que la pizarra pierda alguna de sus capacidades por integrarse.
- Que la página calcule algo por su cuenta (valores, rankings, frases) en vez de pedirlo al
  servicio: cualquier número visible sale de una respuesta de la API.
- Que el README pase de 1000 palabras o de 2 figuras.

## 3. Restricciones

- Las del spec padre (§3): Python ≥ 3.12, uv, ruff, mypy strict, pytest con `-W error`,
  inglés en código y README, ADRs en castellano, commits convencionales.
- Dependencias de ejecución: las actuales (fastapi, uvicorn, mcp). Ninguna nueva.
- Límite de tamaño: **ningún fichero servido supera las 600 líneas**; la regla de ADR-0009
  pasa de "la página" a "cada fichero". Un módulo por vista.
- Presupuesto del README: ≤ 1000 palabras y 2 figuras (hoy 952 y 2). La figura de la pizarra
  se recaptura dentro de la app.
- `decide_snapshot` sigue siendo el único punto de valoración; `AskService` la única fuente de
  rankings, fichas, tiros y explicaciones; `Board` la única pizarra.

## 4. Las vistas

Navegación superior fija: Shot · Players · Games · Ask · About (la interfaz en inglés). La URL
lleva el estado principal (`#shot=...`, `#player=...`, `#game=...`, `#ask=rank_players`) para
que un enlace abra una vista concreta y el vídeo se grabe por URL.

### Tiro (vista inicial)

- **Tiro por defecto**: el de `?shot=`/`#shot=` si viene; si no, el tiro valorado de mayor
  coste con `confidence ≥ MIN_RANK_CONFIDENCE` (la misma regla del reel), que hoy es
  `shot-191313-1-31` (Marco Spissu). Un selector de partido y tiro como el actual, y además
  un selector de "destacados": las tres listas del reel (peores decisiones, mejores lecturas,
  momentos perdidos). **Vienen de un método nuevo `AskService.featured(n)`** que envuelve
  `reel.rank_tables` (las reglas de la capa 2: confianza ≥ `MIN_RANK_CONFIDENCE`, margen para
  las mejores lecturas, `held_to_decision`, ventaja y reloj mínimos para los momentos perdidos)
  sobre las tablas ya cargadas; no es una herramienta MCP (las seis no cambian). El tiro por
  defecto es el primero de "peores decisiones". `find_shots` no puede reproducir esas listas
  (no filtra por confianza ni ordena por margen), y el servicio sigue siendo la única fuente.
- **Pizarra** (izquierda): la actual, sin cambios de comportamiento.
- **Columna derecha**: cabecera (tirador, regla, periodo, reloj; valor del tiro, mejor
  alternativa, coste original → actual), titular de la curva, **curva de ventaja** y tabla de
  opciones (la actual).
- **Curva de ventaja** (SVG, sin librerías): eje x = `t_to_release` (s, negativos hasta la
  suelta), dos líneas: valor del tiro del jugador con balón (`handler_shot_value`) y mejor pase
  (`best_pass_value`), franja sombreada de la ventana del veredicto (`window_start..window_end`
  del resumen), marca vertical en el frame de decisión, cambios de jugador con balón marcados
  con el dorsal. Se lee de `GET /api/curve/{shot_id}` (filas de `artifacts/curves/{game}.parquet`
  más el resumen). Al mover jugadores en la pizarra **la curva no cambia**: valora la posesión
  real, no el frame modificado (límite de ADR-0009); la vista lo dice en una línea.
- **Clip**: si existe `docs/reel/<último>/...-{shot_id}.gif` se muestra bajo la curva; si no,
  una línea con el comando `ventaja clip {shot_id} --out ...` y por qué (necesita tracking).
- **Otros tiros de este partido**: lista compacta (coste, veredicto, tirador, reloj) que
  cambia el tiro al pulsar. Sale de `GET /api/shots?game=` (la ruta de la pizarra, todos los
  tiros del partido, 121–149), no de `find_shots`, que está limitado a `MCP_MAX_LIMIT` = 50
  (decisión mía: la lista completa importa más que pasar por la misma herramienta; la ruta
  sigue leyendo las mismas tablas por `Board`).

### Jugadores

- Ranking con filtros: equipo, tramo de reloj (`24-14`, `14-6`, `6-0`), mínimo de tiros,
  métrica (`mean_cost`, `good_read_share`, `late_held_share`), con la fila de la liga como
  referencia. Datos: `rank_players`.
- Al pulsar un jugador, su ficha: identidad, totales, coste por tramo, alternativa más
  ignorada, bloque de temporada frente a la liga, frase en inglés, aviso de cautela. Datos:
  `player_profile`. Y sus tiros valorados (`find_shots(player=)`) enlazados a la vista Tiro.

### Partidos

- Tabla de los 10 partidos (`list_games`): fecha, equipos, marcador, tiros valorados. Al pulsar,
  la lista completa de tiros del partido (`GET /api/shots?game=`) ordenada por coste, enlazada a
  la vista Tiro.

### Pregunta

- Seis formularios generados desde el esquema de entrada de cada herramienta
  (`GET /api/ask/schema`, el mismo esquema que publica el MCP) y la respuesta en JSON plegable.
  Es la demostración viva de "la página pregunta lo mismo que Claude".
- Un bloque fijo "Connect an AI client" con el `claude mcp add ...` y el JSON de Claude Desktop,
  y el enlace al glosario (`GET /api/ask/glossary`, el mismo texto del recurso MCP).

### Acerca de

- Qué mide `ventaja` en diez líneas (del README), las cuatro superficies, enlaces a los ADRs
  (ficheros del repo, servidos en `/docs/...` como texto) y la versión del modelo
  (`model_trained_at`, `built_at`), que da `GET /api/about` leyendo las marcas de la tabla de
  fichas que `AskService` ya tiene cargada (`service.players`); no es un campo del MCP.

## 5. Arquitectura

```
src/ventaja/web/
    __init__.py
    app.py            # create_app(settings, *, model=None, priors=None) -> FastAPI: monta static/, rutas API
    static/
        index.html    # cáscara: nav, cinco <section>, <script type="module" src="app.js">
        app.css
        app.js        # enrutado por hash, carga de vistas, fetch común, formato
        board.js      # la pizarra actual, extraída de board/static/index.html (misma lógica)
        curve.js      # la curva de ventaja en SVG
        shot.js       # cabecera, titular, tabla de opciones, clip, otros tiros
        players.js, games.js, ask.js, about.js
src/ventaja/board/engine.py   # sin cambios
src/ventaja/board/app.py      # desaparece: sus rutas pasan a web/app.py (mismo contrato)
src/ventaja/cli/app.py        # `ventaja app`; `ventaja board` queda como alias
```

Rutas (todas JSON salvo las estáticas):

- Las de la pizarra tal cual: `GET /api/court`, `GET /api/shots?game=`, `GET /api/shot/{id}`,
  `POST /api/shot/{id}/evaluate`.
- `GET /api/ask/schema` → nombre, descripción y esquema de entrada de las seis herramientas,
  obtenidos **una vez al arrancar** del propio `MCPServer` (`create_server(settings,
  service=...)` acepta ahora el servicio ya construido y `list_tools()` se evalúa con
  `asyncio.run` antes de servir), de modo que la página publica exactamente lo que publica el
  MCP sin cargar los datos dos veces.
- `POST /api/ask/{tool}` con el JSON de argumentos → `call_tool(service, tool, args)`; errores:
  `DataNotFoundError` → 404, cualquier otro `VentajaError` (ambigüedad incluida), `ValueError`
  o `ValidationError` → 400, siempre `{"error": mensaje}` (nunca traza); tool desconocida 404.
  Las rutas de la pizarra conservan sus códigos actuales.
- `GET /api/ask/glossary` → `render_glossary()` como `text/markdown`.
- `GET /api/curve/{shot_id}` → `{"rows": [...], "summary": {...}, "decision_t": s,
  "window": [t0, t1] | null, "handlers": {player_id: jersey}}`: las filas de
  `artifacts/curves/{game}.parquet`, el resumen, y lo que la curva sola no trae: el frame de
  decisión y el de suelta vienen de `artifacts/decisions/` (cruce por `shot_id`), la ventana se
  convierte de frames a segundos con `(frame − release_frame) / FPS` (sus extremos no caen
  necesariamente en una fila muestreada; puede ser nula), y los dorsales de los jugadores con
  balón salen del directorio de personas (`load_people`, con el sustituto de la pizarra si falta
  el dorsal). 404 si el tiro no tiene curva.
- `GET /api/reel` → `{"dir": ..., "clips": {shot_id: url}}` leyendo el último
  `docs/reel/*/index.md` y los GIF presentes; `{"clips": {}}` si no hay. Los GIF se sirven en
  `/reel/...`.
- `GET /api/featured` → el tiro por defecto y las tres listas del reel (vía `find_shots`), para
  que la vista Tiro arranque con una llamada.
- `GET /docs/decisions/{name}.md` → texto del ADR (solo ficheros existentes de ese directorio).
  Los ADRs y los GIF del reel se leen desde la raíz del repo (`ARTIFACTS_DIR.parent`, la misma
  suposición de clon que ya hacen los artefactos empaquetados); en un paquete instalado sin
  `docs/` esas dos rutas devuelven 404 y la app lo dice. Límite conocido en el ADR.

El servidor construye **un** `AskService` al arrancar y usa su `Board` (`AskService.board`
pasa a ser una propiedad pública, perezosa como hoy) para las rutas de la pizarra. Tiempo de
arranque hoy: < 1 s de servicio más el import de polars. `--game` (y el alias `ventaja board
--game`) sigue filtrando solo la lista de tiros de la pizarra, como hoy; las demás vistas ven
los diez partidos.

JavaScript: módulos ES nativos (`import`), sin transpilar; cada vista exporta `mount(root, state)`
y `update(state)`. Estado global mínimo (`shot`, `player`, `game`, `view`) en el hash de la URL.
El código de la pizarra se mueve a `board.js` sin cambiar su comportamiento: lo prueban los
tests de la API y la comprobación en navegador del controlador, igual que en la capa 4.

## 6. Pruebas y comprobaciones

- Tests de API con `TestClient` sobre los artefactos empaquetados: cada ruta nueva (schema con
  seis herramientas, `ask/rank_players` igual a `AskService.rank_players(...).model_dump()`,
  `ask` con error → 400 con mensaje, `curve` de un tiro con y sin resumen, `reel` con y sin
  directorio, `featured` devuelve como primero el primer "peor" de `reel.rank_tables`, la `curve` sin
  resumen sobre un fixture de la build (los 1 351 tiros empaquetados tienen resumen), ADR existente
  200 e inexistente 404, sin salto de directorio). Los tests actuales de la pizarra se mueven al
  nuevo módulo y siguen verdes.
- Test de estructura: `index.html` referencia cada módulo, ningún fichero de `static/` pasa de
  600 líneas, el servidor sirve cada uno con el `Content-Type` correcto.
- Comprobación en navegador (controlador, Chrome): abrir sin parámetros → Spissu con pizarra y
  curva; arrastrar; cambiar de vista por el nav y por URL; ranking con filtro de equipo y tramo;
  ficha; partido → tiro; formulario de `what_if`; consola limpia; ancho de 1100 px y de 390 px.
- Clon limpio: `git clone`, `uv sync`, `uv run ventaja app --no-open`, `curl` a `/`,
  `/api/featured`, `/api/ask/schema`, `/api/curve/shot-191313-1-31`.
- CI: en `pipeline`, con `VENTAJA_BUILD_DIR` vacío, arrancar `ventaja app --no-open` en segundo
  plano y `curl --fail` a las cuatro rutas de arriba; en `quality`, los tests.

## 7. Documentación y cierre

- ADR-0011 (castellano): por qué una app y no varias páginas; FastAPI + módulos ES sin build;
  "página, CLI y MCP responden igual"; el tiro de arranque; qué pasa con los clips; límites
  (curva no reactiva, sin chat, sin estado).
- README: la sección "Whiteboard" pasa a "App" (comando `uv run ventaja app`, qué se ve, el
  MCP sigue en "Ask the court"); figura 2 recapturada dentro de la app; ≤ 1000 palabras.
- CLAUDE.md: comandos, reglas de tamaño por fichero, estructura `web/`.
- Etiqueta `app-unificada` tras el merge (no es una capa del plan original: no se numera).

## 8. Lo que queda al constructor

- La maquetación concreta (CSS, anchos, tipografía): sobria, como la pizarra actual.
- La forma de los módulos JS y del enrutado por hash.
- Cómo leer `docs/reel/*/index.md` (basta con listar los GIF por nombre de tiro).
- Los nombres de los campos de `/api/featured` y `/api/curve`.
- La estrategia para mover `board/static/index.html` a `board.js` + `index.html` sin cambiar su
  comportamiento (extraer, no reescribir).

## 9. Decisiones mías, para que Óscar las revise

- Las respuestas a la comprobación del constructor (2026-11-06) están incorporadas arriba:
  `featured()` en el servicio sobre las reglas del reel; listas por partido completas por la
  ruta de la pizarra; `--game` solo para la pizarra; `/api/about` para las marcas del modelo;
  404/400 según el error; esquema de las herramientas del propio `MCPServer` una vez al
  arrancar; `/api/curve` cruza con decisiones y convierte la ventana a segundos; ADRs y GIF
  desde la raíz del repo.
- Nombre del comando `ventaja app`; `ventaja board` se mantiene como alias del mismo servidor
  para no romper el README ni la memoria de quien lo usó.
- Tiro de arranque por regla (mayor coste con confianza ≥ umbral), no fijado a mano: así sigue
  siendo correcto si se reentrena el modelo.
- Interfaz en inglés (jurado internacional), como la pizarra y el README.
- Los ADRs se sirven dentro de la app en vez de enlazar a GitHub, para que funcione sin red.
- Los clips no se empaquetan (siguen gitignorados, ~ 30 GIF): la app los enseña si están.
