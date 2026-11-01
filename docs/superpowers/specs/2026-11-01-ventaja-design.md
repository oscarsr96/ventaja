# ventaja — diseño del proyecto

Fecha: 2026-11-01. Autor del diseño: Claude, a partir de la conversación con Óscar Sánchez Rueda.
Estado: borrador para aprobación.

Entrada a la **SkillCorner x PySport Analytics Cup 2.0**, competición Europa (final en París,
17 feb 2027), dataset de baloncesto (Liga Endesa ACB 2025-26), participación individual.
Fecha límite de entrega: **18 de diciembre de 2026**. Hoy quedan siete semanas.

---

## 1. Intención y por qué

### La pregunta
El tema oficial sugerido es *Shot Quality*: "¿qué hace que un tiro sea mejor que otro?".
La respuesta mayoritaria será un modelo xFG: medir el tiro. **ventaja** responde midiendo
la **decisión**: un tiro es bueno o malo en relación a las alternativas que el jugador tenía en
ese instante. En el frame exacto del lanzamiento, el tracking dice dónde estaban los otros
cuatro atacantes y sus defensores; cada uno era una opción con un valor. La calidad de la
decisión es la diferencia entre el valor de lo que hizo y el valor de lo mejor que tenía.

Óscar lo formuló así desde el banquillo: "igual había un compañero abierto solo, o el pívot
estaba cayendo al aro, y eran mejores decisiones". El reloj de posesión es contexto de la
decisión, no una columna más: con 2 segundos no hay alternativas y el sistema debe saberlo.

### Por qué este proyecto y no otro
- **Para el jurado**: responde al tema oficial desde un ángulo que no es el saturado, usa lo
  que hace único al dato de SkillCorner (contexto de tracking en cada evento) y cruza las dos
  capas del dataset (10 partidos de tracking + agregados de 293 partidos), puente que el propio
  brief señala como poco construido.
- **Para Óscar**: es una pieza de CV. Es ingeniero de datos, no analista, y quiere que quien
  abra el repo piense dos cosas a la vez: "sabe construir sistemas de datos serios" y "entiende
  de baloncesto". Y que el repo demuestre dominio de **herramientas de IA** en dos sentidos:
  el producto lleva IA dentro (servidor MCP) y el repo se construyó con un flujo de trabajo
  de IA visible y documentado.

### Qué es el éxito
Por este orden, según lo dicho por Óscar:
1. Una pieza que pueda poner en el CV y que aguante que un CTO de club o un reclutador la abra.
2. Que la entrega sea completa y funcione out of the box el 18 de diciembre.
3. Quedar entre los seis finalistas sería la guinda, no el objetivo.

---

## 2. Objetivos, no-objetivos, anti-objetivos

### Objetivos
- **Librería Python instalable** (`pip install ventaja`) que carga los datos de SkillCorner,
  alinea eventos con frames de tracking, valora las opciones de cada tiro y devuelve tablas
  limpias. Es el esqueleto; todo lo demás la consume.
- **Métrica de coste de decisión** por tiro, agregable por jugador, equipo, tramo de reloj y
  tipo de alternativa ignorada.
- **Cuatro superficies** sobre la librería, acordadas con Óscar ("hacemos todas"):
  - **A. El momento perdido**: curva del valor de la mejor opción frame a frame durante la
    posesión, con el pico de ventaja y el instante del tiro. Titular tipo "la ventaja duró 1,6 s;
    el tiro llegó 1,2 s tarde".
  - **C. El reel**: clips animados autogenerados de cualquier tiro (los 3 s previos, valores en
    pantalla) y rankings de peores decisiones y mejores lecturas en los 10 partidos.
  - **B. La pizarra que responde**: app web donde se arrastra a un jugador del frame y los
    valores se recalculan al instante.
  - **D. Pregúntale a la pista**: servidor MCP que expone la librería como herramientas para
    cualquier cliente de IA (Claude Desktop, Cursor...), sin API keys en el repo.
- **Ficha de jugador**: valor de sus tiros vs. valor de la mejor opción, coste de decisión por
  reloj, alternativa que más ignora, frase de perfil. Cruza el frame del tracking con el perfil
  de temporada del jugador desde los agregados.
- **Entrega conforme a las bases**: repo público MIT, README ≤ 1000 palabras con ≤ 2 figuras o
  tablas, vídeo de ≤ 1 minuto narrado por Óscar, reproducible en entorno limpio solo con
  herramientas open source y solo con los datos de SkillCorner.

### No-objetivos
- No es un modelo xFG competitivo con el estado del arte. El modelo de valor es un medio,
  debe ser simple e interpretable, y su mérito es cómo se usa, no su AUC.
- No se modela defensa (los agregados son solo ofensivos y no hay contexto para hacerlo bien).
- No se intenta reconstruir el pase real (si la bola llegaría): se estima viabilidad con
  geometría simple, no con física de trayectorias.
- No hay frontend "de producto": la pizarra es una herramienta funcional, no una app pulida.

### Anti-objetivos (fracaso aunque técnicamente funcione)
- Que el repo no arranque en un entorno limpio el día de la entrega. Descalificación.
- Que se use cualquier dato que no sea el de SkillCorner para esta competición. Descalificación.
- Que la pieza D exija una API key de un proveedor de LLM para que el repo funcione.
- Que la entrega llegue con la capa D a medias y la A sin validar: cada capa se cierra antes de
  abrir la siguiente, para que una entrega sin las últimas capas siga siendo completa.
- Que el modelo sea una caja negra que un entrenador no pueda discutir. Transparencia puntúa.
- Que el README parezca un informe de análisis y no la presentación de una herramienta.

---

## 3. Restricciones

### De la competición (fuente: pysport.org/analytics-cup/rules, leído 2026-11-01)
- Solo el dataset de SkillCorner provisto (y/o de Analytics Cups previas). Nada externo.
- Trabajo nuevo y sustancial creado para esta edición. Librerías de terceros permitidas si se
  declaran y están bien licenciadas. El trabajo analítico central debe ser propio.
- Reproducible sin software propietario (nada de Excel, Tableau, Power BI).
- Entrega: vídeo YouTube ≤ 1 min narrado por el participante; repo público con LICENSE.md
  (MIT) que funcione out of the box; README.md ≤ 1000 palabras con ≤ 2 figuras o tablas en
  total, con instrucciones de reproducción en entorno limpio.
- Criterios (20 % cada uno): relevancia, metodología, originalidad, comunicación, potencial
  open source. El ganador regional recibe 1 500 € para convertir el proyecto en paquete Python.
- Finalistas presentan en persona en París el 17 de febrero de 2027.

### De los datos (fuente: docs del repo opendata-basketball)
- 10 partidos con tracking (25 fps, pies, origen en el centro de la pista, aro ofensivo en x
  negativa) y eventos dinámicos; 293 partidos en agregados de temporada (solo ofensivos).
- Los eventos y el tracking comparten índice de frame y `wallClock`; en `shots` el frame de
  suelta es `startFrame`, que coincide con el `frameIdx` del tracking.
- **Las coordenadas del tracking no están normalizadas al aro ofensivo**: van en orientación de
  cámara. Los eventos sí (aro ofensivo en x negativa). Comprobado por el revisor en el partido
  114086: el `location` del evento es el `xyz` del tracking rotado 180° cuando
  `possessions.leftHoop = false`. La capa 0 debe rotar el tracking por posesión usando
  `leftHoop` antes de cualquier geometría.
- El marcador oficial de los 10 partidos está en `data/matches.json` (`home_score`,
  `away_score`): la validación del marcador no necesita nada externo.
- Los 191 tiradores de los 10 partidos tienen fila en `acb_shotsaggregates`; el cruce de la
  ficha no tiene huecos. Los agregados dan zona y nivel de presión como marginales, no
  cruzados, y con zonas más gruesas que `region`.
- Un 17-24 % de posiciones son extrapoladas, con error medio ~1,5-1,9 ft (p95 ~5-6 ft).
  Las extrapoladas solas tienen ~4,4-5,2 ft. Los jugadores van siempre a z = 0.
- La tabla `shots` incluye fallos con falta (no son intentos de box score). El marcador se
  reconstruye desde `shots` y `free_throws`, no desde `chances.ptsScored`.
- Hay duplicados de `player_id` que se resuelven con `player_id_aliases.csv`.
- Los agregados de picks solo cuentan picks `direct = true`.
- Los ficheros de tracking son Git LFS en el repo de SkillCorner (~30-43 MB cada uno).

### De Óscar
- Trabaja solo. Siete semanas, con dedicación "más que suficiente" en sus palabras.
- Idioma de la entrega: inglés (jurado internacional). Este diseño y las conversaciones, en
  castellano.
- El repo es pieza de CV: calidad de código, arquitectura y documentación cuentan tanto como
  el resultado.

---

## 4. Decisiones ya tomadas

### Por Óscar
- Medir la **decisión**, no el tiro: valor de lo elegido frente al valor de la mejor alternativa
  disponible en el instante del lanzamiento. El reloj de posesión como contexto de la decisión.
- Las cuatro superficies (A, B, C, D), todas.
- Competición Europa, individual.
- Stack: lo que mejor transmita dominio de herramientas de IA, en producto y en proceso.

### Por Claude (marcadas como propias; cambiables)
- **Nombre**: `ventaja`. Es el término que usan los entrenadores españoles para lo que se mide,
  es pronunciable en inglés y está libre en PyPI a fecha de hoy (comprobar antes de publicar).
- **Repo nuevo** en `~/Repos/ventaja`, hermano del clon de SkillCorner. Los datos no se
  redistribuyen: un comando (`ventaja data pull`) descarga lo necesario del repo público de
  SkillCorner (CSVs y JSON por `raw.githubusercontent.com`, tracking LFS por
  `media.githubusercontent.com`), sin requerir `git lfs` instalado. Los datos se cachean en
  `~/.cache/ventaja` o en la ruta que indique `VENTAJA_DATA_DIR`. Se permite apuntar al clon
  local ya existente.
- **Artefactos derivados sí se versionan en el repo** (decisión de Claude tras la revisión).
  Los datos brutos de SkillCorner no se redistribuyen, pero sí los resultados de la librería:
  el modelo de valor entrenado, la tabla de decisiones por tiro de los 10 partidos y las fichas,
  en parquet, unos pocos MB. Motivo: el jurado debe poder abrir la pizarra, el reel, la ficha
  y el MCP sin esperar una descarga de ~350 MB de LFS cuya cuota de ancho de banda no
  controlamos. Recomputar todo desde cero sigue siendo un comando (`ventaja rebuild`), y la CI
  lo ejecuta con un partido para probar el pipeline y, semanalmente, con los 10. El dataset es
  MIT, así que no hay problema de licencia; las bases excluyen "los datos" del repo, y un modelo
  entrenado y una tabla de resultados no lo son. Si hubiera duda, se consulta en el Discord de
  la competición durante la semana 1.
- **Stack base**: Python 3.12; `uv` para entorno y lockfile; Polars y DuckDB para carga y
  transformación (DuckDB lee JSONL.gz y CSV directamente y permite mostrar SQL legible);
  pydantic para los modelos de dominio; pytest con fixtures de un partido; typer para la CLI;
  matplotlib para figuras y clips (con `ffmpeg` o Pillow para GIF/MP4); FastAPI + una página
  HTML sin framework para la pizarra; el SDK oficial de MCP para Python para la capa D; ruff y
  mypy en CI con GitHub Actions. Todo open source.
- **Modelo de valor simple e interpretable**: regresión logística (o GBM con restricciones de
  monotonía y SHAP si la logística no calibra) sobre un puñado de features documentadas. Se
  publica la curva de calibración y la importancia de features en la documentación. Se prohíben
  redes neuronales en esta entrega.
- **Orden de construcción por capas cerradas** (ver sección 6). Cada capa termina con tests,
  documentación y un comando de CLI que la ejercita.
- **Flujo de IA visible en el repo**: `CLAUDE.md` con las convenciones, carpeta `.claude/` con
  skills del proyecto (p. ej. "validar una posesión", "regenerar figuras"), registros de
  decisiones (ADRs cortos en `docs/decisions/`), y una sección del README de entrega
  ("How this was built") que declara el uso de IA en el desarrollo. Las bases prohíben plagio,
  no construir con IA; declararlo refuerza metodología y el mensaje de CV.
- **La capa D no depende de ninguna API key**: es un servidor MCP local. La inteligencia la pone
  el cliente del usuario. Además, cada herramienta MCP tiene equivalente de CLI, de modo que el
  repo se evalúa íntegro sin ningún LLM.

---

## 5. El método (guardarraíles para el constructor)

Esta sección fija lo que el constructor no debe cambiar sin volver a Óscar y deja explícito
lo que sí decide él.

### 5.1 Unidad de análisis
Cada registro de `shots` de los 10 partidos. Para cada tiro, el **frame de decisión** es el
último instante en que el tirador aún podía pasar, no el de la suelta (`startFrame`). Decisión
de Óscar tras la revisión: el 44 % de los tiros de los 10 partidos son bandejas, mates,
ganchos, palmeos y lobs, y en su frame de suelta el jugador ya está en el aire. Regla:
- Tiros en salto (triples, tiros de media distancia): frame de decisión = inicio del gesto de
  tiro, aproximado como `startFrame` menos un tiempo de armado (del campo de tiempo de suelta
  del evento si existe; si no, una constante documentada del orden de 0,3-0,5 s).
- Finalizaciones cerca del aro tras bote (bandeja, mate, gancho, lob): frame de decisión = fin
  del último bote del `touch` del tirador (de `dribbles`), o el inicio del `touch` si no botó.
- Palmeos y tiros sin control previo (recepción y tiro inmediato con `touch` de duración
  mínima): se excluyen del coste de decisión y se marcan como tales; siguen valiendo como
  opciones para otros.
El constructor fija los umbrales y los documenta en un ADR; la validación de cara con Óscar
(5.5) comprueba expresamente que el frame elegido "parece el momento de decidir".
Opcionalmente, A extiende la valoración a todos los frames de la posesión desde la recepción
del tirador (o desde el inicio del `chance`).

### 5.2 Opciones en un frame
En el frame de decisión, las opciones son: (a) el propio tiro; (b) cada uno de los cuatro
compañeros, valorado como "si recibiera ahora y tirara desde donde está". Se construye para
cada opción un vector de features **solo con geometría del frame y perfil de temporada**:
- distancia al aro y ángulo; zona de pista (reutilizar las regiones de SkillCorner);
- distancia al defensor más cercano y si ese defensor está entre el jugador y el aro;
- velocidad y dirección del jugador. Para las opciones de pase, la posición que se valora es la
  **proyectada**: posición actual más velocidad por un tiempo de vuelo estimado del pase
  (función simple de la distancia, con tope), no la posición en el frame de suelta. Sin esto, el
  "pívot cayendo al aro", que es el ejemplo motivador, queda sistemáticamente infravalorado.
  Decisión de Claude tras la revisión; es geometría de primer orden, no reconstrucción de
  trayectorias;
- reloj de posesión y de partido, periodo;
- **perfil de temporada** del jugador desde esa zona y nivel de presión, tomado de los
  agregados de 293 partidos (`acb_shotsaggregates`), con suavizado hacia la media de liga
  cuando la muestra es pequeña.

### 5.3 Valor de una opción
`valor = P(anotar | features) × puntos del tiro`, en puntos esperados. El modelo de
probabilidad se entrena con los ~1 400 tiros reales de los 10 partidos y se **regulariza con el
perfil de temporada** como feature (no se entrena sobre los agregados; se usan como prior por
jugador y zona). Validación: calibración en partidos no vistos (leave-one-game-out) y
comparación con las tasas de los agregados por zona.

Para las opciones de pase se aplica un **descuento de viabilidad** explícito y documentado:
penalización por distancia del pase y por defensores cerca de la línea tirador-compañero, y
anulación si el reloj de posesión es inferior a un umbral (decisión del constructor, en torno a
2 s, justificado en un ADR). El descuento es una función simple con parámetros visibles, no un
modelo aprendido.

### 5.4 Coste de decisión
`coste = valor(mejor opción viable) − valor(tiro tomado)`, truncado en cero cuando el tiro era
la mejor opción (entonces es una "buena lectura" y se contabiliza aparte). Se agrega por
jugador, equipo, tramo de reloj (24-14, 14-6, 6-0 s) y tipo de alternativa ignorada (corte al
aro, esquina abierta, extra pass, poste).

### 5.5 Validación de cara (obligatoria antes de la capa A)
- Reconstruir el marcador final de los 10 partidos desde eventos: deben cuadrar.
- Animar al menos 20 posesiones elegidas al azar y revisar con Óscar, como entrenador, que las
  opciones valoradas coinciden con lo que él ve. Formato acordado: **sesión en vivo** en esta
  misma conversación, de una a dos horas, en la semana del 9 al 15 de noviembre, viendo las
  posesiones animadas una a una. Esto adelanta a la capa 1 un animador de posesiones mínimo
  (sin pulir) que la capa 2 después reutiliza para los clips. Las discrepancias se registran
  y, si son sistemáticas, cambian el método antes de seguir.
- Sanidad: el coste medio debe caer con el reloj agotándose; los tiros bajo aro abiertos deben
  valer más que los triples con mano encima; el perfil de temporada debe mover el valor en la
  dirección correcta.

### 5.6 Lo que decide el constructor
Umbrales concretos, elección final entre logística y GBM, cómo suavizar perfiles con muestra
pequeña, qué features entran, formato de clips (GIF vs. MP4), estructura interna de módulos,
esquema exacto de tablas. Todo ello documentado en ADRs de media página.

---

## 6. Plan por capas y calendario

Cada capa se cierra con: tests que pasan en CI, documentación, un comando de CLI que la
demuestra, y una entrada en el diario de decisiones. No se abre la siguiente sin cerrar la
anterior. Si el 10 de diciembre una capa no está cerrada, se corta y se entrega lo cerrado.

| Semana | Fechas | Capa | Resultado cerrado |
|---|---|---|---|
| 1 | 2-8 nov | **0. Esqueleto + datos** | Repo, CI, `ventaja data pull`, carga con DuckDB/Polars, modelos pydantic, alineación evento-frame, marcador reconstruido en los 10 partidos. |
| 2 | 9-15 nov | **1. Valoración** | Frame de decisión por tipo de tiro, features por opción con posición proyectada, modelo de valor calibrado, descuento de viabilidad, coste de decisión por tiro, animador mínimo de posesiones y sesión de validación en vivo con Óscar (20 posesiones). |
| 3 | 16-22 nov | **2. A + C** | Curva de ventaja por posesión, clips autogenerados, rankings de los 10 partidos. |
| 4 | 23-29 nov | **3. Ficha de jugador** | Cruce con agregados, tablas por reloj y alternativa ignorada, frase de perfil generada por reglas. |
| 5 | 30 nov-6 dic | **4. Pizarra (B)** | FastAPI + página HTML; arrastrar y recalcular. |
| 6 | 7-11 dic | **5. MCP (D)** | Servidor MCP con herramientas equivalentes a la CLI; probado con un cliente real. |
| 7 | 12-18 dic | **6. Entrega** | README ≤ 1000 palabras y 2 figuras, vídeo de 1 minuto, prueba en entorno limpio (contenedor o máquina virgen), publicación en PyPI opcional, envío en el portal. |

La semana 7 está reservada íntegra a la entrega. El vídeo y el README siempre tardan más de
lo que parece.

---

## 7. Las dos figuras y el minuto de vídeo

- **Figura 1**: el visor de decisión de un tiro real: media pista, diez jugadores, atacantes
  coloreados por valor de opción, flecha a la mejor opción, lista de opciones con valor.
- **Figura 2**: la curva del momento perdido de esa misma posesión, o una tabla-ranking de
  jugadores por coste de decisión. A decidir en la semana 7 viendo cuál comunica más.
- **Vídeo**: 0-10 s la pregunta ("¿era el mejor tiro que había?"); 10-35 s un clip del reel con
  la curva de ventaja; 35-50 s la ficha de un jugador y la pizarra respondiendo a un arrastre;
  50-60 s el MCP contestando una pregunta en lenguaje natural y el `pip install ventaja`.

---

## 8. Estructura prevista del repo (orientativa)

```
ventaja/
  pyproject.toml  uv.lock  LICENSE.md  README.md  CLAUDE.md
  src/ventaja/
    data/        # descarga, caché, carga DuckDB/Polars, alias de jugadores
    model/       # pydantic: Frame, Player, Shot, Option, Decision
    geometry/    # distancias, ángulos, zonas, líneas de pase
    value/       # features, modelo de probabilidad, perfiles de temporada, viabilidad
    decision/    # coste por tiro, curva de ventaja, agregaciones, fichas
    viz/         # visor, curva, clips, figuras del README
    cli.py       # typer
    mcp_server.py
    web/         # FastAPI + static/pizarra.html
  tests/         # fixtures de un partido recortado; tests por capa
  docs/
    decisions/   # ADRs
    superpowers/specs/ (este documento)
  .claude/       # skills del proyecto
  .github/workflows/ci.yml
```

---

## 9. Riesgos y cómo se mitigan

- **El modelo de valor es pobre con 1 400 tiros.** Mitigación: pocas features, prior de
  temporada por jugador y zona, validación leave-one-game-out, y honestidad en el README sobre
  el tamaño de muestra. El mérito está en el marco, no en el AUC.
- **El error de tracking (p95 5-6 ft) distorsiona "abierto" vs. "defendido".** Mitigación:
  usar `isDetected` y `predError` para ponderar la confianza y marcar las decisiones con baja
  confianza; documentarlo.
- **Las "veces que había algo mejor" se perciben como juicio injusto al jugador.** Mitigación:
  la ficha siempre muestra el desglose por reloj y el descuento de viabilidad; el lenguaje de la
  frase de perfil es descriptivo, no acusatorio.
- **Alcance de cuatro superficies en siete semanas.** Mitigación: capas cerradas, corte el
  10 de diciembre, la librería como única fuente de verdad para que B y D sean finos.
- **Fallo en entorno limpio el día de la entrega.** Mitigación: CI en GitHub Actions desde la
  semana 1 que instala desde cero, descarga un partido y ejecuta el pipeline completo.

---

## 10. Abierto para Óscar

- Confirmar el nombre `ventaja` (libre en PyPI a 2026-11-01) y el repo nuevo en
  `~/Repos/ventaja`.
- Disponibilidad real por semana, para ajustar el calendario si alguna semana es corta.
- Si publicará el paquete en PyPI antes de la entrega (recomendado: refuerza "potencial open
  source" y permite el `pip install ventaja` del vídeo).

## 11. Registro de la revisión del constructor (2026-11-01)

Un revisor independiente leyó el documento contra los datos reales. Resultado:
- **Resuelto por Óscar**: frame de decisión retrasado para finalizaciones (5.1); revisión de
  posesiones en sesión en vivo (5.5).
- **Resuelto por Claude**: posición proyectada para opciones de pase (5.2); artefactos
  derivados versionados en el repo (sección 4).
- **Hechos incorporados**: orientación de cámara del tracking y rotación por `leftHoop`;
  `startFrame` como frame de suelta; marcador oficial en `matches.json`; cobertura completa
  de los tiradores en los agregados (sección 3).
