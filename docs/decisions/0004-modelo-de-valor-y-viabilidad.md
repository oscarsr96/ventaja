# ADR-0004: modelo de valor, viabilidad del pase y coste de decisión

## Contexto

La capa 1 compara, en el frame de decisión (ADR-0003), el tiro tomado con los cuatro pases posibles. Hace falta (a) un valor en puntos esperados para cada opción, (b) un descuento por lo difícil que es que el pase llegue y (c) una regla de coste. El spec (5.3-5.4) pide un modelo de probabilidad interpretable, regularizado con el perfil de temporada, y una viabilidad con parámetros visibles, no aprendida.

## Decisión

**Modelo de valor.** `valor = P(anotar | features) × puntos` (`value/model.py`). Regresión logística (`C = 1.0`) sobre features estandarizadas; solo se guardan coeficientes, medias, escalas e imputaciones en JSON (`models/value_model.json`), nunca el objeto de sklearn. Features (`OPTION_FEATURES`, `value/features.py`): distancia al aro y su cuadrado, ángulo, si es triple, distancia al defensor más cercano, defensor entre jugador y aro, velocidad de cierre del defensor, velocidad hacia el aro, `prior_zone` (tasa de temporada del jugador en esa zona, encogida hacia la de la liga con `K_SHRINK = 20` intentos ficticios), reloj de posesión y bandera de reloj bajo (< 4 s). Los nulos (reloj apagado) se imputan con la media de entrenamiento. Las opciones de pase se valoran en la posición proyectada del receptor (velocidad × tiempo de vuelo, con tope de 10 ft). Se elige la logística frente a un GBM porque con unos 1 350 tiros un GBM sobreajusta con facilidad, la logística es interpretable coeficiente a coeficiente (odds ratios en `ventaja model report`) y su calibración es razonable sin postproceso.

Validación leave-one-game-out sobre 1 351 tiros: logloss 0,6494, Brier 0,2293, AUC 0,6294 y correlación de Pearson 0,5211 con el `shotQuality` de SkillCorner (figura en `docs/figures/calibration.png`). Se excluyen 108 de los 1 459 tiros: 81 sin `touch_id`, 20 sin tipo y 7 palmeos. Las features con más peso son `prior_zone`, la distancia al defensor y la distancia al aro al cuadrado.

**Nota honesta sobre `prior_zone`.** Los perfiles se construyen con los agregados de temporada, que incluyen los 10 partidos con tracking. Por tanto la validación LOGO no es estrictamente fuera de muestra para esa feature: el resultado del tiro evaluado está dentro de su propio prior. El efecto es pequeño (un tiro diluido entre toda una temporada de intentos y encogido con K = 20), pero las métricas pueden ser algo optimistas.

**Viabilidad del pase** (`decision/cost.py`, `viability`). El tiro tiene siempre viabilidad 1,0. Para un pase: 0 si el reloj de posesión es inferior a `SHOT_CLOCK_MIN_PASS = 2,0 s` (no da tiempo a pasar y tirar); si no, `d = 1 − clamp((distancia − 30) / (60 − 30), 0, 1)` con `PASS_DISTANCE_SOFT = 30 ft` y `PASS_DISTANCE_HARD = 60 ft`, multiplicado por `LANE_BLOCKED_FACTOR = 0,4` si hay un defensor en la línea de pase. Un reloj desconocido no penaliza. `valor_ajustado = valor × viabilidad`.

**Coste.** Mejor alternativa = máximo `valor_ajustado` entre los cuatro pases (en empate, el primero). `coste = max(0, mejor_alternativa − valor_del_tiro)`; `good_read` si la mejor alternativa no supera el tiro. `confidence` es la fracción de los 10 jugadores detectados (no extrapolados) en el frame.

**Tipo de alternativa** (`classify_alternative`), con `CUT_SPEED = 4 ft/s` y `OPEN_DEF_DIST = 6 ft`: `rim_cut` si está en zona restringida o pintura y va hacia el aro a ≥ 4 ft/s; `open_corner` si está en la esquina de triple con el defensor a ≥ 6 ft; `post` si está en la pintura sin cortar; `extra_pass` si está en triple frontal o media distancia y abierto; si no, `other`.

**Observación sobre `lane_blocked`.** Con `LANE_END_MARGIN = 2 ft` (menos que una distancia de defensa típica), la línea se marca como bloqueada en el 59 % de las opciones de pase, de modo que el factor 0,4 pesa mucho en el resultado. No se ajusta ahora: se revisará en la sesión de validación en vivo (spec 5.5) con las posesiones animadas.

**Artefactos versionados.** `models/value_model.json` (modelo entrenado con los 10 partidos) y `artifacts/decisions/` con 20 parquet: `{game_id}.parquet` (una fila por tiro, con `rule = "excluded"` y `reason` para los excluidos) y `{game_id}.options.parquet` (una fila por opción de los tiros válidos, con las features en columnas). `load_decisions`, `load_decision_options` y las vistas DuckDB `decisions` / `decision_options` leen primero el build y, si no existe, estos artefactos, así que `ventaja decisions show` y `ventaja sql` funcionan en un clon recién descargado. Regenerar: `ventaja model train --all` y después `ventaja decisions build --all`, y copiar `{build}/decisions/*.parquet` a `artifacts/decisions/`.

Todas las constantes viven en `value/params.py` y solo cambian mediante un ADR.

## Consecuencias

Cada tiro de los 10 partidos tiene un coste explicable opción a opción (`ventaja decisions show SHOT_ID`). Sobre los 1 351 tiros válidos el coste medio es 0,153 puntos (mediana 0) y el 51 % son buenas lecturas; por tramo de reloj, 0,149 (24-14 s), 0,179 (14-6 s) y 0,102 (6-0 s), así que el coste cae al final de la posesión pero no de forma monótona. Riesgos aceptados: la viabilidad es una heurística sin aprendizaje, `lane_blocked` está probablemente sobredisparado, el modelo tiene una discriminación modesta (AUC 0,63) y las finalizaciones cuyo último bote ocurre lejos del aro se valoran desde esa posición lejana (16 tiros en zona `far`/`backcourt`).
