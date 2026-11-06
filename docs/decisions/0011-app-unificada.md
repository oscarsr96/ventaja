# ADR-0011: una app local que reúne tiro, pizarra, curva, jugadores, partidos y MCP

## Contexto

Cada superficie de `ventaja` se abría por un sitio distinto: la pizarra en el navegador (ADR-0009), las fichas y rankings por terminal, las curvas como PNG, los clips como GIF en `docs/reel/` y el MCP desde Claude (ADR-0010). Para que el jurado abra una sola cosa, y para grabar el vídeo sobre una única pantalla, hacía falta un único punto de entrada que funcione desde un clon limpio, sin tracking, sin API key y sin build de JavaScript.

## Decisión

**Una app, no varias páginas.** `ventaja app [--host] [--port 8765] [--game ID ...] [--no-open]` sirve una página con cinco vistas: Shot, Players, Games, Ask y About, con un enrutado por hash (`#shot=...`, `#player=...`, `#game=...`, `#ask=...`) para que una URL abra una vista concreta. `ventaja board` queda como alias del mismo servidor, para no romper el README ni a quien ya lo usaba. `--game` filtra solo la lista de tiros de la pizarra; las demás vistas ven los diez partidos.

**FastAPI y módulos ES, sin build.** `web/app.py` (`create_app`) monta `web/static/` en `/static`: `index.html` (cáscara con el nav y una `<section data-view>` por vista), `app.css`, `app.js` (enrutado y `fetch` común) y un módulo por vista (`shot.js`, `players.js`, `games.js`, `ask.js`, `about.js`) más `board.js` y `curve.js`. Sin framework, sin bundler, sin paquetes npm y sin dependencias de ejecución nuevas. La regla de ADR-0009 de 600 líneas pasa de "la página" a **cada fichero servido**, y un test de estructura la comprueba. La regla CSS `section[data-view][hidden]{display:none !important}` existe porque los módulos de vista fijan estilos `display` en línea, que de otro modo ganarían al atributo `hidden`.

**Página, CLI y MCP responden igual.** Los tres llaman al mismo `AskService` (capa 5) y, para la pizarra, a su `Board` (`AskService.board`, propiedad pública y perezosa). `create_app` construye un solo `AskService` y lo comparte. `POST /api/ask/{tool}` pasa por `call_tool`, el mismo despachador que `ventaja mcp call`. El esquema de entrada de las seis herramientas (`GET /api/ask/schema`) se toma una sola vez, al arrancar, del propio `MCPServer` (`create_server(settings, service=...)` acepta el servicio ya construido y `tool_schemas(server)` evalúa `list_tools()`), de modo que la página publica exactamente lo que publica el MCP y los datos no se cargan dos veces. La vista Ask genera sus formularios de ese esquema. `GET /api/ask/glossary` devuelve `render_glossary()`, el texto del recurso MCP. Cualquier número visible sale de una respuesta de la API: la página no calcula valores, rankings ni frases.

**Tiro de arranque por la regla del reel.** La vista Shot abre con `?shot=`/`#shot=` si viene; si no, con el primero de "peores decisiones" de `AskService.featured(n)`, que envuelve `reel.rank_tables` (confianza ≥ `MIN_RANK_CONFIDENCE`, y las demás reglas de la capa 2) sobre las tablas ya cargadas. Hoy es `shot-191313-1-31`. Al ser una regla y no un id fijado, sigue siendo correcto si se reentrena el modelo.

**`featured()` no es una herramienta MCP.** Las seis herramientas no cambian. `find_shots` no puede reproducir las listas del reel (no filtra por confianza ni ordena por margen), y `featured` es una vista de presentación de la app, no una pregunta que un cliente de IA necesite. `GET /api/featured` la expone; el servicio sigue siendo la única fuente.

**La pizarra, extraída sin tocar.** `board.js` sale de `board/static/index.html` moviendo el código, no reescribiéndolo, y las rutas de la pizarra (`/api/court`, `/api/shots`, `/api/shot/{id}`, `POST /api/shot/{id}/evaluate`) pasan tal cual a `web/app.py`, con sus códigos. `board/app.py` desaparece; `board/engine.py` no cambia. La curva de ventaja (`curve.js`, SVG sin librerías) se lee de `GET /api/curve/{shot_id}`: las filas de `artifacts/curves/`, el resumen, el frame de decisión (cruce con las decisiones), la ventana convertida de frames a segundos con `(frame − release_frame) / FPS` y los dorsales de los jugadores con balón. Al mover jugadores la curva no cambia, porque valora la posesión real y no el frame modificado.

**Clips solo si existen.** Los GIF del reel no se empaquetan (están en `.gitignore`, hacen falta datos de tracking para generarlos). `GET /api/reel` lista los GIF del último directorio de `docs/reel/` que los tenga y la vista Shot los muestra bajo la curva; si no, indica el comando `ventaja clip`. Los GIF se sirven en `/reel/`.

**ADRs y GIF desde la raíz del repo.** `GET /docs/decisions/{name}` y `/reel` leen de `REPO_ROOT = ARTIFACTS_DIR.parent`, la misma suposición de clon que ya hacen los artefactos empaquetados. El nombre del ADR se valida con una expresión regular y se comprueba que su carpeta padre es `docs/decisions/`, de modo que no hay salto de directorio. Con el paquete instalado sin `docs/`, esas dos rutas devuelven 404 y la app lo dice.

**Códigos de error.** `POST /api/ask/{tool}`: herramienta desconocida y `DataNotFoundError` dan 404; cualquier otro `VentajaError` (ambigüedad incluida), `ValueError` o `ValidationError` da 400; siempre `{"error": mensaje}`, nunca una traza. `GET /api/curve/{id}` sin curva da 404 y `GET /api/featured` con `n` fuera de rango da 400. Las rutas de la pizarra conservan los suyos (404 y 422). `GET /api/about` da la versión, el número de partidos, tiros valorados y jugadores con ficha, y las marcas `model_trained_at` y `built_at`, leídas de la tabla de fichas ya cargada.

## Consecuencias

`uv run ventaja app` funciona desde un clon limpio con `uv sync`, igual que la pizarra y el MCP. En CI, el job `pipeline` arranca la app con `VENTAJA_BUILD_DIR` vacío y hace `curl --fail` a `/`, `/api/featured`, `/api/ask/schema` y `/api/curve/shot-191313-1-31`; los tests de la API corren en `quality`. No cambian las constantes, los artefactos ni su orden de regeneración. `decide_snapshot` sigue siendo el único punto de valoración.

**Límites conocidos.**

- La curva no es reactiva: al arrastrar jugadores no cambia (la vista lo dice en una línea).
- No hay chat ni modelo de lenguaje en la página. El chat es Claude Desktop o Claude Code con el MCP; la vista Ask ofrece las seis herramientas como formularios y explica cómo conectar un cliente.
- No hay estado de usuario en servidor, ni autenticación, ni despliegue público: es una app local.
- Los clips no se generan desde la página (necesitan tracking) y no se empaquetan.
- Los ADRs y los GIF requieren que `docs/` esté junto a `artifacts/`; en un paquete instalado sin él devuelven 404.
- `/static` se sirve sin cabeceras de caché: tras una actualización, el navegador puede conservar JavaScript antiguo y hace falta una recarga forzada.

**Alternativas descartadas.**

- *Una página por superficie.* Es lo que había: el jurado tendría que abrir cinco cosas y el vídeo no se grabaría sobre una pantalla.
- *Un escaparate estático publicado.* Un HTML con resultados precalculados no permite arrastrar jugadores ni preguntar, y los números dejarían de salir de la API.
- *Un framework de JavaScript (React, Vite).* Añade un build y dependencias a una herramienta de inspección; ADR-0009 y el spec lo excluyen.
- *Un modelo de lenguaje dentro de la página.* Exigiría una API key, que el repo no puede pedir.
