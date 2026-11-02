# ADR-0008: ficha de jugador y de equipo, con cruce de temporada

## Contexto

El spec (§2, «Ficha de jugador») pide para cada jugador el valor de sus tiros frente al de la mejor opción, el coste de decisión por reloj, la alternativa que más ignora y una frase de perfil, cruzando lo que se ve en el tracking con su perfil de temporada de los agregados de SkillCorner. El §5.4 fija cómo se agrega el coste: por jugador, equipo, tramo de reloj (24-14, 14-6, 6-0 s) y tipo de alternativa ignorada. El §9 avisa del riesgo principal: que «había algo mejor» se lea como un juicio injusto al jugador. La ficha tiene que mostrar siempre el desglose y el tamaño de muestra, y la frase tiene que describir, no acusar.

Los 10 partidos dan 1 351 tiros valorados de 190 tiradores, con una mediana de 6 tiros por jugador. Óscar decidió (2 de noviembre de 2026) que **la ficha existe desde 1 tiro valorado**: no se esconde a nadie, pero tampoco se afirma nada que la muestra no sostenga.

## Decisión

**Quién tiene ficha.** Todo tirador con al menos una decisión valorada (`rule != "excluded"`) en los partidos con decisiones construidas. El nombre («Nombre Apellido») y el equipo salen de `meta/players`, que es el equipo con el que jugó los partidos seguidos (en estos 10 partidos nadie aparece con dos equipos), y el nombre del equipo sale de `meta/games`. Sin `meta/players`, el nombre es el id y el equipo queda nulo.

**Métricas** (`profile/aggregate.py`, sobre las decisiones no excluidas):

- `n_shots`, `n_readable` (`good_read` no nulo) y `n_low_confidence` (confianza < `MIN_RANK_CONFIDENCE`).
- Valor medio del tiro frente al de la mejor alternativa, `mean_cost` y `good_read_share`. Todos se calculan **solo sobre las decisiones legibles**. Una decisión sin pase viable tiene coste 0 por construcción, así que meterla en la media rebajaría el coste sin que haya habido ninguna lectura. `total_cost` sí suma todas las decisiones.
- Coste medio por tramo de reloj (`CLOCK_BUCKETS`, pertenencia en `value/clock.py`, compartida con el diagnóstico `cost_falls_with_clock`). El primer tramo no tiene techo, porque un reloj algo por encima de 24 también abre la posesión, y el último incluye el 0,0. Un reloj nulo (apagado, ADR-0007) no entra en ningún tramo; la ficha lo cuenta aparte.
- Por tipo de alternativa (`ALT_TYPES`), el número de decisiones con coste mayor que `ADVANTAGE_TOLERANCE` cuya mejor alternativa es de ese tipo, y su coste medio. `ignored_alt` es el tipo más frecuente; los empates se resuelven por el orden de `ALT_TYPES`.
- Momentos perdidos, de las curvas (ADR-0006): `n_late_held` (veredicto `late` con `held_to_decision`), su proporción sobre los tiros con curva, el retraso medio y la proporción de veredictos `during`. Tras la revisión R7, `n_late_held`, `late_held_share` y `mean_lag_held` aplican el mismo suelo de reloj que el reel (enmienda de capa 3 de ADR-0006): solo cuentan las decisiones con reloj nulo o ≥ `LATE_MIN_CLOCK` = 2,5 s, porque por debajo es el reloj, y no el tirador, quien cierra la ventana. `n_with_summary` sigue contando todos los tiros con curva.
- **Nulos, nunca ceros.** Una media o proporción con denominador vacío queda nula. Un jugador con 1 tiro tiene nulos en los tramos y alternativas que no ha tocado.

**Temporada** (`profile/season.py`). Se suman las filas por equipo de los agregados `shots` y `drives`. La fila `total` (`team_id` nulo) nunca se usa, para no contar dos veces a un jugador traspasado. Se calculan partidos, intentos, TC, proporción de triples, de tiros tras recepción y con mano encima, TC sin defensor cerca, la mezcla de las cinco zonas principales, la distancia media y el bloque de penetraciones (pase fuera, tiro tras bote, cerca del aro). Son **tasas crudas, sin encoger** hacia la media como hace `Priors`. La ficha describe la temporada de ese jugador, no estima su talento, y con cientos de intentos por jugador el encogimiento apenas cambiaría nada. La mezcla de zonas de los partidos seguidos sale de las opciones de tiro de las decisiones (`backcourt` y `far` van a «otras»), y `shift_{zona}` es la proporción seguida menos la de temporada. `drives` es opcional: sin esa tabla, el bloque de penetraciones queda nulo.

**Fila LIGA.** `players.parquet` lleva una fila con `player_id = 0`, `name = "LIGA"` y equipo nulo, con las mismas métricas sobre todas las decisiones. Lleva además dos claves de temporada de liga ponderadas por intentos sobre las filas por equipo: `season_cns_share = Σ cns_attempts / Σ attempts` (0,456) y `season_contested_share = Σ contested_attempts / Σ attempts` (0,684). La frase y el ranking tienen así la referencia a mano, en la misma tabla. `find_player` nunca la devuelve, `player rank` la excluye y no tiene frase. Se descartó una tabla `league.parquet` aparte porque obligaba a cada lector a abrir dos ficheros para comparar.

**Frase** (`profile/phrase.py`, en es y en). Las reglas y sus umbrales (en `value/params.py`) son:

1. **Muestra.** Con menos de `PROFILE_MIN_SHOTS` = 8 tiros legibles, la frase es solo «Con {n} tiros valorados la muestra es pequeña» (singular con 1). Tras la revisión R6 ya no añade la regla 5: antes, 28 de las 124 frases de muestra pequeña llevaban una cláusula de reloj basada en 2 a 4 tiros. El umbral se mide en tiros legibles: cuando hay tiros no legibles (`n_readable < n_shots`), la apertura dice las dos cifras (revisión R5, que afina la R4): Jordan Walker, con 2 tiros y 1 legible, lee «Con 1 tiro legible de 2 valorados la muestra es pequeña»; cuando coinciden, queda la forma corta. No se afirma ninguna tendencia por debajo de 8. Es el mínimo de apoyo para afirmar algo; el mínimo para tener ficha sigue siendo 1.
2. **Lectura frente a la liga.** «Elige bien el tiro» si `good_read_share` ≥ la de la liga + `PROFILE_READ_DELTA` (0,08). Si no, «suele tener un pase mejor disponible» si `mean_cost` ≥ el de la liga + `PROFILE_COST_DELTA` (0,05). Si no, «decide en la media de la liga».
3. **Alternativa.** «La opción que más deja pasar es {alternativa}», si `ignored_alt` tiene al menos `PROFILE_ALT_MIN` = 3 decisiones.
4. **Momentos perdidos.** «Tiende a tirar cuando la ventaja ya se ha esfumado» si `late_held_share` ≥ `PROFILE_LATE_SHARE` (0,25).
5. **Reloj** (revisión R6, relativa a la liga). Para cada tramo con al menos `CLOCK_MIN_SHOTS` = 2 tiros legibles se calcula el exceso sobre la liga, `cost_tramo − coste de liga del tramo`. Con dos o más tramos, la frase dice «su coste es más alto con {mucho reloj / el reloj medio / el reloj agotándose}» (en: «his cost is highest with {plenty of clock / mid clock / the clock running out}») y nombra el tramo de mayor exceso si supera al menor exceso en `PROFILE_COST_DELTA` o más. Comparar los tramos del jugador entre sí no servía: el coste de la liga ya sube 0,07 del primer tramo al último (más que `PROFILE_COST_DELTA`), así que un jugador que seguía exactamente a la liga «subía con el reloj agotándose». Y «sube con mucho reloj» no tenía sentido para el primer tramo.
6. **Temporada** (segunda frase, solo si hay bloque de temporada). «En estos partidos tira más desde {zona} que en su temporada» si el mayor `shift` es ≥ `PROFILE_ZONE_SHIFT` (0,15). Tras la revisión R3, las cláusulas de tiro tras recepción («la mayoría de sus tiros de temporada llegan tras recepción», revisión R8: antes decía «es sobre todo un tirador tras recepción», que etiquetaba de tirador a pívots que casi no tiran de fuera) y de mano encima son **relativas a la liga**: aparecen solo si la proporción del jugador es ≥ la de la liga + `PROFILE_SEASON_DELTA` (0,10). Con un umbral absoluto, «la mayoría de sus tiros son con mano encima» describía a casi todo el mundo, porque la media de la liga es 0,684.

**Desglose y viabilidad en la ficha** (§9). Además de las tablas por reloj y por alternativa, el bloque «Valor» de `player show` y `player team` dice siempre que el valor de las alternativas está descontado por la viabilidad del pase (carril, distancia, reloj por debajo de 2 s), y cuántas decisiones del jugador no tenían pase viable (`n_shots − n_readable`): cuentan con coste 0 y quedan fuera de las medias. Con `--lang en` esa nota y la frase salen en inglés; el resto de etiquetas, en español.

El bloque «Por reloj» termina con `reloj desconocido: {n} decisiones` (`n_readable` menos la suma de los tramos: las decisiones legibles con reloj nulo), y el título del bloque de alternativas dice qué cuenta: «Por alternativa (decisiones con coste > 0,10)». El umbral de reloj de la nota de viabilidad se escribe desde `SHOT_CLOCK_MIN_PASS`, no como literal (revisión R9). En la frase, el artículo forma parte del nombre de la zona o del tramo («desde el triple frontal», «desde la zona restringida», «con el reloj medio»); la tabla de zonas de temporada usa las etiquetas sin artículo.

El vocabulario es descriptivo («suele tener un pase mejor», «la opción que más deja pasar»). Nunca usa «falla», «se equivoca» ni «mala decisión».

**Artefactos.** `players.parquet` y `teams.parquet` tienen esquemas explícitos (`PLAYERS_SCHEMA`, `TEAMS_SCHEMA`) y se escriben de forma atómica. Cada escalar de la ficha es una columna. Los bloques se aplanan con prefijos (`clock_{tramo}_{n,cost}`, `alt_{tipo}_{n,cost}`, `season_*`, `tracked_*`, `shift_*`), `games` es una lista, y llevan `built_at` (ISO UTC) y `model_trained_at`. Se construyen en el build (`players/`) o en `artifacts/` con `--out artifacts`. Como no son ficheros por partido, `artifact_dir("players")` cae en `artifacts/` y no en `artifacts/players/`. DuckDB los expone como `player_cards` y `team_cards`. CLI: `ventaja player build | show | rank | team`.

## Consecuencias

Cifras reales (`ventaja player build`, 2 de noviembre de 2026):

| cifra | valor |
|---|---:|
| jugadores con ficha | 190 (17 equipos) |
| tiros por jugador: mín / p25 / mediana / p75 / máx | 1 / 4 / 6 / 10 / 30 |
| jugadores con ≥ 8 tiros / ≥ 15 / con 1 tiro | 67 / 18 / 19 |
| LIGA: tiros (legibles) | 1 351 (1 303) |
| LIGA: valor del tiro vs. mejor alternativa | 0,959 vs. 1,017 |
| LIGA: coste medio sobre legibles / buenas lecturas | 0,199 / 41,4 % |
| LIGA: tarde con el balón (con suelo de reloj, R7) / durante la ventaja | 13,5 % (182 de 1 351; antes 15,4 %, 208) / 46,0 % |
| LIGA: coste por reloj 24-14 / 14-6 / 6-0 (n) | 0,164 / 0,205 / 0,234 (402 / 638 / 175) |
| LIGA: legibles con reloj desconocido | 88 |
| equipo con menor / mayor coste medio | Real Madrid 0,107 / Basquet Girona 0,255 |

Fichas de equipo, por coste medio. **14 de los 17 equipos tienen un solo partido seguido** (solo Leche Rio Breogan, Casademont Zaragoza y Dreamland Gran Canaria tienen dos), así que una ficha de equipo describe uno o dos partidos, no una temporada:

| equipo | partidos | jugadores | tiros (legibles) | coste medio | tarde con el balón |
|---|---:|---:|---:|---:|---:|
| Real Madrid | 1 | 11 | 68 (68) | 0,107 | 22,1 % |
| Bitci Baskonia | 1 | 10 | 67 (65) | 0,159 | 11,9 % |
| Valencia BC | 1 | 10 | 70 (66) | 0,175 | 12,9 % |
| Lenovo Tenerife | 1 | 11 | 65 (62) | 0,178 | 12,3 % |
| San Pablo Burgos | 1 | 10 | 76 (76) | 0,183 | 10,5 % |
| Leche Rio Breogan | 2 | 12 | 134 (130) | 0,188 | 9,7 % |
| CB UCAM Murcia | 1 | 11 | 65 (63) | 0,190 | 18,5 % |
| Coviran Granada | 1 | 11 | 75 (73) | 0,193 | 16,0 % |
| Casademont Zaragoza | 2 | 13 | 130 (128) | 0,194 | 15,4 % |
| Club Joventut Badalona | 1 | 9 | 73 (72) | 0,209 | 17,8 % |
| BC Barcelona | 1 | 11 | 62 (58) | 0,215 | 14,5 % |
| BC MoraBanc Andorra | 1 | 12 | 77 (76) | 0,216 | 22,1 % |
| Malaga | 1 | 12 | 65 (58) | 0,218 | 7,7 % |
| Dreamland Gran Canaria | 2 | 16 | 119 (113) | 0,221 | 7,6 % |
| Bilbao Basket | 1 | 10 | 72 (65) | 0,233 | 12,5 % |
| BAXI Manresa | 1 | 10 | 66 (64) | 0,251 | 16,7 % |
| Basquet Girona | 1 | 11 | 67 (66) | 0,255 | 6,0 % |

**Hallazgo: sobre las decisiones legibles, el coste de la liga sube a medida que se agota el reloj** (0,164, 0,205 y 0,234). Es lo contrario de lo que esperaba el diagnóstico de la capa 1 (`cost_falls_with_clock`, ADR-0004). La «bajada» del tramo 6-0 que se veía antes (0,184 en ADR-0007, tras R18) venía de las filas sin pase viable: tienen coste 0 por construcción y las 48 están en ese tramo (223 decisiones válidas frente a 175 legibles), porque un reloj por debajo de 2 s anula los pases. Sin ellas, la tendencia es monótona y creciente. El diagnóstico `cost_falls_with_clock` mantiene su propia convención (todas las filas válidas) y sigue como `xfail`. La ficha usa la convención de legibles, que es la que responde a «¿cuánto deja pasar cuando había lectura?».

Las frases sobre 190 jugadores (tras las revisiones R6 a R8): 124 son solo la nota de muestra pequeña, ninguna con cláusula de reloj (antes 28). De las 66 con 8 o más tiros legibles, la lectura frente a la liga da «elige bien» en 21, «suele tener un pase mejor» en 20 y «en la media» en 25. La alternativa aparece en 50, los momentos perdidos en 17 (antes 20) y el reloj, ya relativo a la liga, en 57 (antes 50, y 78 contando las de muestra pequeña). En la frase de temporada, el desplazamiento de zona aparece en 27, el tiro tras recepción en 17 y la mano encima en 5. Todos los jugadores tienen bloque de temporada y 184 tienen penetraciones.

Los tres jugadores que pierden la regla 4 con el suelo de reloj son Chris Duarte, Kevin Punter y Dylan Ennis. Duarte es el caso claro: sus 4 momentos perdidos (`shot-179612-1-37`, `-3-89`, `-3-104`, `-4-108`) tenían entre 0,92 y 1,92 s de reloj, ninguno legible (sin pase viable), así que su proporción pasa de 28,6 % a 0. Ennis baja de 5 a 3 (27,8 % a 16,7 %) y Punter de 4 a 3 (28,6 % a 21,4 %). Su frase es ahora «Suele tener un pase mejor disponible; la opción que más deja pasar es la esquina abierta; su coste es más alto con el reloj medio. En estos partidos tira más desde el triple frontal que en su temporada.»

**Honestidad sobre `n`.** La cabecera de la ficha muestra siempre los tiros y los legibles, y `player rank` muestra `n` en cada fila. `--min-shots` cuenta tiros valorados (`n_shots`), mientras que el umbral de la frase cuenta tiros legibles. Con `--min-shots 1` (el valor por defecto) el primero por coste medio es un jugador con 1 tiro legible (Jordan Walker, 0,968). Con `--min-shots 8` los tres primeros son Grant Golden (0,447, n 10), Marco Spissu (0,412, n 12) y DeWayne Russell (0,367, n 30). La diferencia entre las dos listas es la razón de mostrar `n` y de que la frase no afirme tendencias por debajo de 8.

**Lo que la ficha NO afirma.** No dice que un jugador decida mal: dice cuánto valor esperado tenía la mejor alternativa viable según un modelo entrenado con 10 partidos (ADR-0004), en el frame de decisión elegido (ADR-0003). No corrige el contexto táctico (una jugada diseñada para él, el marcador, la defensa que se espera). Las tasas de temporada son crudas y no ajustan el rival ni los minutos. La frase con menos de 8 tiros legibles solo constata la muestra (desde R6, sin cláusula de reloj), y la de equipo no existe: un equipo es la suma de sus tiradores en uno o dos partidos.

**Mantenimiento.** `artifacts/players.parquet` y `artifacts/teams.parquet` dependen de las decisiones, las curvas, `meta/` y los agregados. Se regeneran después de las curvas con `ventaja player build --out artifacts`, y nunca se editan a mano.
