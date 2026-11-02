# ADR-0007: un reloj de posesión a 0,0 significa «apagado», no «cero»

## Contexto

Durante la capa 2 (2 de noviembre de 2026) se revisaron los relojes de posesión de las decisiones valoradas de los 10 partidos. 76 de los 1 351 tiros valorados tenían `shot_clock` exactamente 0,0. En 55 de ellos el reloj de partido estaba por debajo de 24 s: al final de un periodo el reloj de posesión se apaga y el tracking lo reporta como 0,0. En 50 tiros el reloj marca 0,0 durante más de 1 s antes de la suelta (hasta 19 s), algo imposible con un reloj en marcha.

La capa 1 trata `shot_clock < SHOT_CLOCK_MIN_PASS` (2 s) como «ningún pase viable» (ADR-0004), así que 76 de sus 116 decisiones sin lectura eran este artefacto. La curva de la capa 2 lo heredaba: por ejemplo, en `shot-191313-4-132` el reloj está a 0,0 los últimos 3 s, los pases quedaban anulados y la curva contaba un «momento perdido» de 4,6 s que en realidad era el reloj apagado.

## Decisión

En `Aligner._build` (`decision/align.py`), un `shot_clock` bruto igual a `SHOT_CLOCK_OFF = 0.0` (constante nueva en `value/params.py`) se lee como `None` (desconocido). Todo lo demás ya sabía tratar un reloj desconocido:

- `viability(..., None)` no aplica la anulación por reloj: el pase se juzga por distancia y carril.
- El modelo de valor imputa la feature `shot_clock` con el `fill` de entrenamiento (la media) y `shot_clock_low` vale 0.
- El chequeo `cost_falls_with_clock` ignora las filas con reloj nulo.

Un reloj de 0,4 s sigue siendo 0,4 s: solo el 0,0 exacto cambia. Se elige esta regla frente a usar el reloj de partido (apagado si `game_clock < 24`) porque cubre también los 21 tiros con el reloj a 0,0 fuera de ese caso y no necesita otra fuente.

Un tiro sobre la bocina de posesión con el reloj exactamente a 0,0 también pasa a `None`. Es inofensivo: el reloj llega a 0,0 en la suelta o después, mientras que el frame de decisión es anterior (0,4 s en `gather`, hasta 2,4 s en finalizaciones), así que en ese frame el reloj aún marca un valor positivo; y si alguno quedara a 0,0, perderlo solo quita la anulación de unos pases que de todos modos tienen un valor bajo en esa situación.

## Consecuencias

Se regeneró todo, en este orden: modelo (`ventaja model train --all`), decisiones (`artifacts/decisions/` y el build), chequeos, curvas (`artifacts/curves/` y el build), kit de revisión (`docs/review/2026-11-sample/review.md`, con las respuestas del entrenador recopiadas) y reel (`docs/reel/2026-11/index.md`).

| cifra | antes | después |
|---|---:|---:|
| tiros valorados con reloj nulo | 20 | 96 |
| logloss / Brier / AUC (LOGO) | 0,6418 / 0,2256 / 0,6539 | 0,6417 / 0,2256 / 0,6540 |
| correlación con `shotQuality` | 0,5740 | 0,5756 |
| sin pase viable (`good_read` nulo) | 116 | 40 |
| buenas lecturas | 41,9 % de 1 235 | 41,4 % de 1 311 |
| coste medio (mediana) | 0,178 (0,032) | 0,193 (0,071) |
| coste por reloj 24-14 / 14-6 / 6-0 s | 0,161 / 0,204 / 0,146 (n 402 / 638 / 291) | 0,163 / 0,204 / 0,193 (n 402 / 638 / 215) |
| veredictos `during` / `late` / `none` / `no_window` | 521 / 529 / 269 / 32 | 558 / 528 / 233 / 32 |
| `late` con `held_to_decision` | 213 | 216 |
| ventaja: mediana / p90 | 1,0 / 3,4 s | 1,0 / 3,6 s |
| retraso `late`: mediana / p90 | 0,8 / 3,8 s | 0,8 / 3,5 s |

Los 40 tiros que siguen sin pase viable tienen un reloj real entre 0 y 2 s. El modelo apenas cambia (las 76 filas pasan de reloj 0 a la media imputada). `lane_blocked` no cambia (47,4 % de los pases). La mejor alternativa es `extra_pass` en 759 tiros, `open_corner` en 242, `other` en 177, `post` en 80 y `rim_cut` en 53.

`cost_falls_with_clock` sigue fallando, y ahora con más claridad: el tramo 6-0 s ya no tiene los 76 costes 0 del artefacto. Ese descenso al final de la posesión que señalaba ADR-0004 era en buena parte el reloj apagado. Se mantiene como diagnóstico (CI con `--allow-fail`, `xfail` en el test con datos reales).

Los cuatro tiros de la sesión del 2 de noviembre se leen igual que los juzgó el entrenador: Kurucs, Andric y González con la mejor alternativa en el receptor señalado (coste 0,794 / 0,342 / 0,133, `good_read` falso) y Spagnolo bloqueado (coste 0, `good_read` verdadero). `shot-191313-4-132` deja de ser un momento perdido de 4,6 s (ahora es un `late` con 0,2 s de retraso) y sale del top 3 del reel; entra `shot-114099-4-117`. Ese cambio no viene del reloj sino del reentrenamiento: una fila de su curva estaba 0,001 puntos por debajo de la tolerancia y ahora la supera, con lo que dos rachas se unen y la ventaja pasa de 0,2 a 4,0 s. La longitud de la ventana es sensible a cambios pequeños del modelo cerca de `ADVANTAGE_TOLERANCE`.

La figura 2 provisional (`docs/figures/curve-shot-191313-4-132.png`) contaba el artefacto y se sustituye.
