# ADR-0004: modelo de valor, viabilidad del pase y coste de decisión

## Contexto

La capa 1 compara, en el frame de decisión (ADR-0003), el tiro tomado con los cuatro pases posibles. Hace falta (a) un valor en puntos esperados para cada opción, (b) un descuento por lo difícil que es que el pase llegue y (c) una regla de coste. El spec (5.3-5.4) pide un modelo de probabilidad interpretable, regularizado con el perfil de temporada, y una viabilidad con parámetros visibles, no aprendida.

## Decisión

**Modelo de valor.** `valor = P(anotar | features) × puntos` (`value/model.py`). Regresión logística (`C = 1.0`) sobre features estandarizadas; solo se guardan coeficientes, medias, escalas e imputaciones en JSON (`models/value_model.json`), nunca el objeto de sklearn. Features (`OPTION_FEATURES`, `value/features.py`): distancia al aro y su cuadrado, ángulo, si es triple, distancia al defensor más cercano, defensor entre jugador y aro, velocidad de cierre del defensor, velocidad hacia el aro, `prior_zone` (tasa de temporada del jugador en esa zona, encogida hacia la de la liga con `K_SHRINK = 20` intentos ficticios), reloj de posesión y bandera de reloj bajo (< 4 s). Los nulos (reloj apagado) se imputan con la media de entrenamiento. La fila del tiro describe el tiro que realmente se intentó: su zona sale de la `region` del evento (o, si es nula o desconocida, de la posición del tirador), sus puntos y `is_three` del campo `three` del evento (3 si es triple, 2 si no) y `prior_zone` de esa zona; el resto de features (distancias, ángulo, defensores, velocidades, reloj) se mide en el estado del frame de decisión. Las filas de pase describen un catch-and-shoot en la posición proyectada del receptor (velocidad × tiempo de vuelo, con tope de 10 ft). Las zonas `backcourt` y `far` valen 3 puntos. Se elige la logística frente a un GBM porque con unos 1 350 tiros un GBM sobreajusta con facilidad, la logística es interpretable coeficiente a coeficiente (odds ratios en `ventaja model report`) y su calibración es razonable sin postproceso.

Validación leave-one-game-out sobre 1 351 tiros: logloss 0,6418, Brier 0,2256, AUC 0,6539 y correlación de Pearson 0,5740 con el `shotQuality` de SkillCorner (figura en `docs/figures/calibration.png`). Se excluyen 108 de los 1 459 tiros: 81 sin `touch_id`, 20 sin tipo y 7 palmeos. Las features con más peso son `prior_zone`, la distancia al defensor y la distancia al aro al cuadrado.

Comparación por zona (spec 5.3; `zone_table` en `models/value_model.json`, impresa por `ventaja model report`): predicción media fuera de muestra, tasa observada en los 10 partidos y tasa de liga de los agregados de temporada.

| zona | n | predicción media | observada | liga |
|---|---:|---:|---:|---:|
| restricted_area | 337 | 0,600 | 0,567 | 0,678 |
| paint_non_ra | 349 | 0,389 | 0,421 | 0,493 |
| mid_range | 152 | 0,331 | 0,329 | 0,406 |
| corner_3 | 101 | 0,398 | 0,337 | 0,378 |
| above_break_3 | 401 | 0,324 | 0,342 | 0,351 |
| backcourt | 8 | 0,040 | 0,000 | 0,047 |
| far | 3 | 0,096 | 0,000 | 0,120 |

El modelo sigue la tasa observada en media distancia y triples frontales; sobrestima la esquina (0,398 frente a 0,337) y la zona restringida (0,600 frente a 0,567) e infravalora la pintura no restringida. Las tasas de liga (293 partidos de temporada) son más altas que las observadas en estos 10 partidos en el aro, la pintura y la media distancia; con estas muestras no se puede separar el efecto de la muestra del de la asignación de zonas.

**Nota honesta sobre `prior_zone`.** Los perfiles se construyen con los agregados de temporada, que incluyen los 10 partidos con tracking. Por tanto la validación LOGO no es estrictamente fuera de muestra para esa feature: el resultado del tiro evaluado está dentro de su propio prior. El efecto es pequeño (un tiro diluido entre toda una temporada de intentos y encogido con K = 20), pero las métricas pueden ser algo optimistas.

**Viabilidad del pase** (`decision/cost.py`, `viability`). El tiro tiene siempre viabilidad 1,0. Para un pase: 0 si el reloj de posesión es inferior a `SHOT_CLOCK_MIN_PASS = 2,0 s` (no da tiempo a pasar y tirar); si no, `d = 1 − clamp((distancia − 30) / (60 − 30), 0, 1)` con `PASS_DISTANCE_SOFT = 30 ft` y `PASS_DISTANCE_HARD = 60 ft`, multiplicado por `LANE_BLOCKED_FACTOR = 0,4` si hay un defensor en la línea de pase. Un reloj desconocido no penaliza. `valor_ajustado = valor × viabilidad`.

**Coste.** Mejor alternativa = máximo `valor_ajustado` entre los cuatro pases (en empate, el primero). `coste = max(0, mejor_alternativa − valor_del_tiro)`; `good_read` si la mejor alternativa no supera el tiro. Si ningún pase es viable (mejor `valor_ajustado` = 0, típicamente con reloj < 2 s) no hay alternativa: `best_alt_*` quedan nulos, `coste = 0` y `good_read` es nulo, porque no hubo lectura que hacer; las proporciones de buenas lecturas se calculan solo sobre las filas no nulas. `confidence` es la fracción de los 10 jugadores detectados (no extrapolados) en el frame.

**Tipo de alternativa** (`classify_alternative`), con `CUT_SPEED = 4 ft/s` y `OPEN_DEF_DIST = 6 ft`: `rim_cut` si está en zona restringida o pintura y va hacia el aro a ≥ 4 ft/s; `open_corner` si está en la esquina de triple con el defensor a ≥ 6 ft; `post` si está en la pintura sin cortar; `extra_pass` si está en triple frontal o media distancia y abierto; si no, `other`.

**Observación sobre `lane_blocked`.** Con `LANE_END_MARGIN = 2 ft` (menos que una distancia de defensa típica), la línea se marca como bloqueada en el 59 % de las opciones de pase, de modo que el factor 0,4 pesa mucho en el resultado. No se ajusta ahora: se revisará en la sesión de validación en vivo (spec 5.5) con las posesiones animadas.

**Artefactos versionados.** `models/value_model.json` (modelo entrenado con los 10 partidos) y `artifacts/decisions/` con 20 parquet: `{game_id}.parquet` (una fila por tiro, con `rule = "excluded"` y `reason` para los excluidos) y `{game_id}.options.parquet` (una fila por opción de los tiros válidos, con las features en columnas). `load_decisions`, `load_decision_options` y las vistas DuckDB `decisions` / `decision_options` leen un único directorio, elegido una vez por `decisions_dir`: `{build}/decisions/` si contiene algún parquet de decisiones y, si no, estos artefactos. Nunca se mezclan: con un build de un solo partido, los demás partidos dan `DataNotFoundError` en lugar de leerse del paquete. Así `ventaja decisions show` y `ventaja sql` funcionan en un clon recién descargado. Regenerar: `ventaja model train --all` y después `ventaja decisions build --all --out artifacts/decisions`.

Todas las constantes viven en `value/params.py` y solo cambian mediante un ADR.

## Consecuencias

La regla de `lane_blocked` descrita aquí se modificó tras la sesión en vivo del 2 de noviembre de 2026: véase [ADR-0005](0005-carril-de-pase-tras-la-sesion.md).

**Enmienda ADR-0007 (2026-11-02).** Un reloj de posesión bruto de 0,0 es el reloj apagado y se lee como desconocido ([ADR-0007](0007-reloj-de-posesion-apagado.md)). Las cifras de este ADR son anteriores a esa regla y se dejan como histórico. Tras reentrenar: logloss 0,6417, Brier 0,2256, AUC 0,6540, correlación 0,5756; 40 tiros sin pase viable (antes 116, de ellos 76 con el reloj apagado); el 41,4 % de los 1 311 con lectura son buenas lecturas; coste medio 0,193; coste por reloj 0,163 / 0,204 / 0,193 (24-14 / 14-6 / 6-0 s), de modo que la caída al final de la posesión descrita abajo era en buena parte el artefacto. La tabla por zona cambia en la tercera cifra decimal. Con la enmienda R18 de ADR-0007 (un 0,0 al que se llega por una cuenta atrás en el segundo anterior es un reloj agotado y sigue en 0,0), 8 decisiones recuperan el reloj a 0: logloss 0,6416, Brier 0,2256, AUC 0,6541, correlación 0,5760; 48 tiros sin pase viable; el 41,4 % de los 1 303 con lectura son buenas lecturas; coste medio 0,192; coste por reloj 0,164 / 0,205 / 0,184.

Cada tiro de los 10 partidos tiene un coste explicable opción a opción (`ventaja decisions show SHOT_ID`). Sobre los 1 351 tiros válidos el coste medio es 0,159 puntos (mediana 0). En 116 tiros, todos con menos de 2 s de posesión, ningún pase es viable y no cuentan como lectura; de los 1 235 restantes, el 48 % son buenas lecturas. Por tramo de reloj el coste medio es 0,148 (24-14 s), 0,184 (14-6 s) y 0,122 (6-0 s): cae al final de la posesión (en parte porque los 116 tiros sin pase viable tienen coste 0), pero no de forma monótona, así que el chequeo `cost_falls_with_clock` falla. No se ajusta para que pase: es un diagnóstico para la sesión en vivo y CI lo permite con `--allow-fail` (los otros tres chequeos bloquean). La mejor alternativa es un `extra_pass` en 694 tiros, `open_corner` en 205, `other` en 198, `post` en 79 y `rim_cut` en 59.

**Corrección sobre las zonas lejanas.** Una versión anterior de este ADR atribuía los 16 tiros válidos en zona `far`/`backcourt` a finalizaciones juzgadas en un último bote lejano. No era así: 11 de los 16 eran tiros en suspensión (`gather`), 8 de ellos heaves, y su zona se tomaba de la posición del tirador en el frame de decisión. Con la zona y los puntos tomados del evento, quedan 11 tiros en esas zonas (8 `backcourt` y 3 `far`), todos tiros en suspensión (8 heaves, un catchAndShoot, un dribblePullUp y un shakeAndRaise) y todos valorados como triples; ninguna finalización cae ya en ellas.

**Sesgos declarados.** (1) La mejor alternativa es el máximo de cuatro valores de pase con ruido: aunque cada valor fuera insesgado, su máximo no lo es, así que el coste medio está sesgado al alza. (2) El modelo se ajusta con tiros que sí se tomaron y se aplica a compañeros que no tiraron: las situaciones de los receptores (catch-and-shoot hipotético en una posición proyectada) no tienen por qué parecerse a las de los tiros de entrenamiento, y su probabilidad es una extrapolación.

Riesgos aceptados: la viabilidad es una heurística sin aprendizaje, `lane_blocked` está probablemente sobredisparado (59 % de los pases) y el modelo tiene una discriminación modesta (AUC 0,65).
