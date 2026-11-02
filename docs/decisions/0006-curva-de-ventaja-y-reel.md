# ADR-0006: curva de ventaja de la posesión (y reel)

## Contexto

La superficie A del spec («el momento perdido») pide la curva del valor de la mejor opción frame a frame durante la posesión, con el instante del tiro, y un titular del tipo «la ventaja duró 1,6 s; el tiro llegó 1,2 s tarde». La capa 1 (ADR-0004, ADR-0005) valora el tiro frente a sus cuatro pases en un único frame, el de decisión (ADR-0003); la curva repite esa valoración a lo largo de la jugada.

El primer intento definía la ventaja respecto al **pico** de la curva: la ventana era el tramo contiguo alrededor del máximo de `best_value` (las cinco opciones) dentro de 0,10 puntos del pico, con veredictos `on_time` / `late` / `early` según dónde cayera el frame de decisión. Sobre 21 tiros reales distintos (los 20 de la muestra de revisión y 3 de prueba, dos de ellos repetidos) dio casi siempre lo mismo: «ventaja de 0,6 s, varios segundos tarde». Dos causas: (1) el ruido frame a frame del modelo (unas décimas entre muestras de 0,2 s) encoge cualquier ventana definida respecto al pico a dos o tres muestras; (2) el pico pertenecía a menudo a un jugador con balón anterior (antes del último pase), de modo que el «retraso» medía cuánto tardó el balón en llegar al tirador, no una decisión suya. Además, el tiro hipotético del propio jugador con balón deriva con su posición y generaba «ventajas» que no eran una opción distinta del tiro.

## Decisión

**Curva** (`decision/curve.py`, `possession_curve`). El tramo es la chance del tiro, desde su `frontcourt_frame` (o `start_frame` si es nulo) hasta la suelta, y se muestrea cada `CURVE_STEP_FRAMES` = 5 frames (5 Hz) hacia atrás desde la suelta, que siempre está en la curva. **Enmienda (2026-11-02, R16):** el frame de decisión del tiro también se muestrea siempre, insertado en orden (sin duplicarse si ya es un frame de la rejilla, e incluso si cae antes del inicio del tramo, lo que pasa en 27 tiros). Sin él, en los tiros `touch_start` y `last_dribble` (el frame de decisión rara vez cae en la rejilla de la suelta) la primera fila del tirador podía quedar después del frame de decisión: su racha se descartaba y «la última racha en o antes del frame de decisión» caía en el jugador con balón anterior, que el titular presentaba como si fuera del tirador. En cada frame muestreado, el jugador con balón sale de los toques (`BallHandler`); los frames con el balón en el aire no tienen jugador con balón y no aparecen, y los frames en que ese jugador no está en el tracking se omiten y se cuentan (`skipped_off_court`). Para el jugador con balón se valoran, con el modelo de la capa 1 sin reentrenar, su tiro hipotético desde donde está y los cuatro pases, estos descontados por `viability` (ADR-0004/0005). Cada fila guarda `handler_shot_value`, `best_value` (máximo de las cinco opciones), `best_pass_value` (máximo de los pases; nulo si ninguno es viable), quién es la mejor opción y su tipo.

**Ventaja** (`summarize_curve`). La referencia es el **valor del tiro real** (`shot_value` de la tabla de decisiones de la capa 1), no el pico. Una fila es de ventaja si `best_pass_value >= shot_value + ADVANTAGE_TOLERANCE` (0,10 puntos). Una racha es una secuencia de filas de ventaja consecutivas con el **mismo** jugador con balón; el resumen se queda con la última racha que empieza en o antes del frame de decisión. Veredictos (`Verdict`):

- `late`: esa racha terminó antes del frame de decisión; `release_lag_seconds` es la distancia de su último frame al frame de decisión.
- `during`: el frame de decisión cae dentro de la racha (retraso 0).
- `none`: ninguna fila de ventaja en o antes del frame de decisión.
- `no_window`: la curva tiene menos de `CURVE_MIN_ROWS` = 3 filas.

`advantage_seconds` = filas de la racha × 5 / 25 (la fila del frame de decisión, fuera de la rejilla, cuenta como un paso más). El titular (`headline`, en español e inglés) lee el veredicto: «La ventaja duró X s y se esfumó Y s antes de la decisión», «Había una opción mejor en el instante del tiro (+D pts, abierta X s)», «No hubo mejor opción que el tiro en la posesión». El retraso se mide hasta el frame de decisión, no hasta la suelta. Cuando la racha de un `late` no es del tirador, el titular la atribuye a quien la tuvo: «La ventaja la tuvo J y se esfumó Y s antes de la decisión» (J es el nombre del jugador en el reel, los clips y la figura; en los artefactos, que no tienen nombres, su `player_id`). En español los decimales llevan coma.

Las tres reglas que sustituyen al primer intento:

1. **Solo cuentan los pases.** El tiro hipotético del jugador con balón no abre ventaja: su deriva con la posición no es una opción distinta del tiro que acabó haciendo.
2. **Las rachas se parten por jugador con balón.** Así «abierta X s» describe lo que vio un mismo jugador, y una ventaja anterior al último pase no se atribuye al tirador.
3. **La referencia es el tiro real.** `during` es, en el frame de decisión, la versión de curva del `cost > 0,10` de la capa 1 (coinciden en el 93,9 % de los tiros; difieren cuando el frame de decisión no es un frame muestreado o la racha se parte justo antes), de modo que las dos capas no se contradicen; la curva añade cuánto tiempo llevaba abierta la opción y si se cerró antes.

**Enmienda (2026-11-02): `held_to_decision`.** El resumen añade la bandera `held_to_decision` (columna de `SUMMARY_SCHEMA`; `summarize_curve` recibe `shooter_id`). Vale `True` solo en un `late` cuya racha es del tirador y en el que todas las filas de la curva posteriores al fin de la racha, hasta el frame de decisión inclusive, tienen al tirador como jugador con balón: se quedó con el balón mientras la ventaja se cerraba. En `during`, `none` y `no_window` vale `False`. Un `late` sin la bandera significa que la ventaja se usó (el balón fue a otro jugador, a menudo la mejor opción, y volvió o acabó en el tirador) o que era de un jugador con balón anterior; solo los `late` con la bandera son «momentos perdidos» del tirador, y es el filtro del ranking `late` del reel. Cifras reales (tras ADR-0007): 216 de los 528 `late` llevan la bandera (de los 225 cuya racha es del tirador, 9 la pierden porque otro jugador toca el balón entre la racha y el frame de decisión); su retraso mediano es 0,6 s (p90 1,6 s) y 163 tienen una ventaja de al menos 0,4 s.

**Reel** (`reel.py`, `ventaja reel rankings` / `ventaja reel build`). Tres rankings sobre las decisiones valoradas con `confidence ≥ MIN_RANK_CONFIDENCE` = 0,8 (fracción de los diez jugadores detectados en el frame de decisión): **peores decisiones** (mayor `cost`) y **mejores lecturas** (`good_read` con mayor margen `shot_value − best_alt_value`), ambos con algún pase viable en el frame de decisión; y **momentos perdidos**: `late` con `held_to_decision` y `advantage_seconds ≥ MIN_RANK_ADVANTAGE` = 0,4 s (dos muestras), ordenados por `release_lag_seconds`, sin exigir pase viable en el frame de decisión (la ventaja suele haberse cerrado ya: 20 de los 159 candidatos no tienen ninguno). `build_reel` genera un clip por fila y un `index.md`; los clips de momentos perdidos empiezan `min(REEL_LATE_MAX_BEFORE_S, max(CLIP_BEFORE_S, (frame de decisión − inicio de la ventana)/25 + REEL_LATE_LEAD_S))` antes del frame de decisión, con `REEL_LATE_LEAD_S` = 1,0 s y `REEL_LATE_MAX_BEFORE_S` = 12,0 s, para que la ventana se vea. Un clip que falla (`VentajaError`) se lista con su motivo y no detiene el reel. Cifras del reel de los 10 partidos (`docs/reel/2026-11/`, top 10): 30 clips; 66 de los 1 351 tiros valorados quedan fuera por confianza (los 66 tienen algún pase viable; antes de ADR-0007 eran 59 con pase viable); 216 de los 528 `late` llevan `held_to_decision`.

Las constantes viven en `value/params.py` (`CURVE_STEP_FRAMES`, `ADVANTAGE_TOLERANCE`, `CURVE_MIN_ROWS`) y solo cambian por ADR.

Alternativas descartadas: interpolar el balón en vuelo para valorar también esos frames (el jugador con balón no está definido mientras el balón vuela y se inventaría una opción); valorar a todos los atacantes en cada frame en lugar del jugador con balón (la pregunta es qué podía hacer quien tenía el balón, y multiplicaría el coste por cinco).

## Consecuencias

Artefactos versionados en `artifacts/curves/`: `{partido}.parquet` (una fila por frame muestreado, `CURVE_SCHEMA`) y `{partido}.summary.parquet` (una fila por tiro valorado, `SUMMARY_SCHEMA`: los campos de `CurveSummary` más `headline_es`, `headline_en` y `skipped_off_court`). Se regeneran con `ventaja curves build --all --out artifacts/curves` (por defecto escribe en el `curves/` del build); los lectores (`load_curves`, `load_curve_summaries`, vistas SQL `curves` y `curve_summaries`) usan el build si tiene alguna curva y si no los artefactos, sin mezclar (`load.artifact_dir`, la misma regla que las decisiones). `ventaja curves show SHOT_ID` imprime el titular, el resumen y la curva.

Con las tres reglas, sobre los 21 tiros de la revisión: `during` 12, `late` 5, `none` 4, con retrasos `late` de 0,2 a 1,1 s.

**Cifras reales** (los 1 351 tiros valorados de los 10 partidos, modelo versionado, tras la regla del reloj apagado de [ADR-0007](0007-reloj-de-posesion-apagado.md); `artifacts/curves/`; antes de ADR-0007 eran `during` 521, `late` 529, `none` 269, `no_window` 32):

| veredicto | tiros |
|---|---:|
| `during` | 558 (41,3 %) |
| `late` | 528 (39,1 %) |
| `none` | 233 (17,2 %) |
| `no_window` | 32 (2,4 %; 17 curvas vacías y 15 de 1-2 filas) |

- `advantage_seconds` en los 1 086 tiros con ventana: mediana 1,0 s, p90 3,6 s.
- `release_lag_seconds` en los `late`: mediana 0,8 s (p90 3,5 s; 334 de 528 hasta 1,1 s, 61 por encima de 3 s).
- Correlación de Pearson entre el `cost` de la capa 1 y `release_lag_seconds` en los `late`: −0,11. Son medidas distintas: un `late` suele tener coste bajo en el frame de decisión precisamente porque la ventaja ya se había cerrado.
- La ventana es del tirador en el 72,1 % de los tiros con ventana: en el 100 % de los `during` (en el frame de decisión el jugador con balón es el tirador) y en el 42,6 % de los `late` (225 tiros, retraso mediano 0,6 s); en el resto de `late` la ventaja la tuvo un compañero antes del último pase (retraso mediano 1,0 s).
- Los cinco mayores retrasos son de 8,0 a 10,2 s (`shot-188630-4-115`, `shot-179612-1-31`, `shot-114099-1-16`, `shot-114234-2-37`, `shot-191313-1-5`); los cuatro primeros tienen la ventana en otro jugador y ventajas de 0,2 a 0,8 s (dos de una sola muestra al principio de la chance). Son el caso límite de la regla «última racha antes del frame de decisión»; los consumidores (el reel) deberían filtrar por `advantage_seconds` o por `window_handler_id` cuando quieran «el tirador llegó tarde».
- `skipped_off_court` total: 0. Filas de curva: 48 399 (mediana de 33 por tiro).
- Comparación con la capa 1 (test `realdata`): en los 678 tiros `gather` con una fila de curva justo en el frame de decisión, el mejor pase de la curva coincide con el de la tabla de opciones en 677 (diferencia 0); el otro (`shot-114169-3-104`) es el único en que los toques dan el balón a un compañero del tirador en ese frame. El tiro hipotético de la curva difiere del tiro real en 77 de esas filas (hasta 0,70 puntos) porque la curva toma zona y puntos de la posición y `decide` del evento; por eso la ventaja se mide solo con pases y contra el `shot_value` de la capa 1.

**Coste de cómputo.** `ventaja curves build --all` tarda unos 3 min 45 s en un portátil (226 s con `--out artifacts/curves`, 222 s al build), muy por debajo de los 15 min previstos. Los 20 ficheros ocupan 1,45 MB.

**Extrapolación.** El modelo de valor se entrenó con tiros reales, en el instante en que alguien tiró. La curva lo aplica a frames en los que nadie tiró, a un jugador con balón que quizá estaba de espaldas, botando en el medio campo o recibiendo: el valor de esos frames es una extrapolación y su ruido entre muestras contiguas es de unas décimas de punto. Por eso se exige una tolerancia de 0,10 sobre el tiro real y no se lee el pico; los valores absolutos de la curva fuera del frame de decisión deben leerse como orientativos.

**Reel de los 10 partidos** (`docs/reel/2026-11/index.md`, top 10 por ranking, 30 clips, tras ADR-0007). Top 3 de peores decisiones: `shot-191313-1-31` (coste 1,14), `shot-191313-4-126` (1,12), `shot-114086-4-108` (1,09). Top 3 de mejores lecturas: `shot-114234-2-35` (margen 1,34), `shot-178442-2-65` (1,17), `shot-114243-1-25` (1,16). Top 3 de momentos perdidos: `shot-191313-1-5` (retraso 8,0 s), `shot-188630-3-81` (5,2 s), `shot-114099-4-117` (4,8 s). Antes de ADR-0007 el tercero era `shot-191313-4-132` (4,6 s), cuya historia venía del reloj apagado.

**Figura 2 provisional**: `docs/figures/curve-shot-179612-1-7.png` (Kameron Taylor; una sola ventana de 1,6 s con un pase de 1,40 puntos frente a un tiro de 1,07, cerrada 2,2 s antes del frame de decisión, con 16,3 s de posesión). Sustituye a `curve-shot-191313-4-132.png`, invalidada por ADR-0007.
