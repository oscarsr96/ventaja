# ADR-0005: regla del carril de pase tras la sesión en vivo

## Contexto

El 2 de noviembre de 2026 Óscar, como entrenador, revisó en directo 20 posesiones de la muestra de `docs/review/2026-11-sample` (seed 7). Sus respuestas están en [`respuestas-2026-11-02.json`](../review/2026-11-sample/respuestas-2026-11-02.json). Resultado: frame de decisión 19 `ok` y 1 `mal`; opciones valoradas 17 `ok` y 3 `mal`.

Los tres `mal` de las opciones son pases que el modelo penalizaba por `lane_blocked` (ADR-0004: un defensor a menos de `LANE_WIDTH` = 3 ft del segmento pasador→receptor proyectado y a más de `LANE_END_MARGIN` = 2 ft de ambos extremos, viabilidad × 0,4):

- `shot-191313-2-46`, pase al dorsal 47 (Kurucs).
- `shot-191313-4-127`, pase al dorsal 37 (Andric).
- `shot-191313-4-137`, pase al dorsal 7 (Gonzalez); el comentario del entrenador es «tiro precipitado».

En los tres, el defensor estaba en el MEDIO de un pase de 20-25 ft (a 8-9 ft de ambos extremos), el receptor estaba libre y el pasador estaba parado: un pasador parado lo supera con un pase por alto. La distancia del defensor más cercano al receptor era 17,3 / 10,5 / 7,1 ft y el `moving_to_hoop` del pasador 3,6 / −1,1 / 1,3 ft/s.

El contraejemplo es `shot-114086-4-102` (Spagnolo): el entrenador escribe «el pase fuera está tapado por línea de pase» y valora las opciones como `ok`. Allí el receptor tenía un defensor a 11,6 ft, pero el pasador se movía hacia el aro a 13,5 ft/s: con el pasador en carrera no hay tiempo de superar al defensor del carril.

Sensibilidad medida en la sesión: con la regla vigente `lane_blocked` se activa en el 56 % de los pases; si solo contaran los extremos del segmento, en el 25 %. (Sobre las 5 404 filas de pase de `artifacts/decisions/` la regla vigente da un 59,0 %.)

## Decisión

Regla B. Un defensor en el carril (mismo criterio: `perp < LANE_WIDTH` y `LANE_END_MARGIN < along < length − LANE_END_MARGIN`) bloquea el pase si:

1. está a `LANE_END_ZONE` = 6,0 ft o menos de cualquiera de los dos extremos (cerca de las manos del pasador o del receptor: ahí no hay pase por alto que valga), o
2. está en el medio y el receptor no está abierto: su defensor más cercano, en la posición proyectada, a menos de `LANE_OPEN_RECEIVER` = 6,0 ft (el mismo umbral que `OPEN_DEF_DIST`), o
3. está en el medio y el pasador conduce: `moving_to_hoop` del pasador de `LANE_DRIVING_SPEED` = 4,0 ft/s o más.

Si el defensor está en el medio, el receptor está abierto y el pasador parado, el pase no se bloquea. `LANE_WIDTH`, `LANE_END_MARGIN` y `LANE_BLOCKED_FACTOR` no cambian. Las tres constantes nuevas viven en `value/params.py`.

Se elige esta regla frente a la alternativa de contar solo los extremos (25 %) porque conserva las dos situaciones que el entrenador distingue (receptor tapado, pasador en carrera) y solo suelta el caso que consideró jugable. `lane_blocked` no es una característica del modelo (solo entra en `viability`), así que el modelo no se reentrena; se reconstruyen las decisiones.

## Consecuencias

Sobre las 5 404 filas de pase, `lane_blocked` baja del 59,0 % al 47,4 %. Sobre los 1 351 tiros válidos, el coste medio sube de 0,159 a 0,178 puntos (más pases viables, mejor alternativa mayor), la proporción de buenas lecturas baja del 48,0 % al 41,9 % (de los 1 235 con lectura; los 116 sin pase viable no cambian) y el coste medio por reloj es 0,161 (>14 s), 0,204 (14-6 s) y 0,146 (≤6 s); `cost_falls_with_clock` sigue sin cumplirse y no se ajusta. La mejor alternativa es `extra_pass` en 714 tiros, `open_corner` en 231, `other` en 162, `post` en 79 y `rim_cut` en 49.

Los cuatro tiros de la sesión: Kurucs, Andric y Gonzalez pasan a `lane_blocked` falso (coste 0,793 / 0,345 / 0,131; `good_read` falso en los tres; mejor alternativa `open_corner` / `extra_pass` / `extra_pass`; antes los tres tenían coste 0 y `good_read` verdadero); Spagnolo sigue bloqueado (coste 0, `good_read` verdadero, `open_corner`).

La reducción es menor de lo previsto en la sesión (se esperaba por debajo del 45 %; queda en 47,4 %). El test con datos reales exige menos de 0,50.

Quedan dos observaciones para la capa 2, sin tocar la capa 1: (1) el campo de visión del pasador, «jugador con balón no puede ver la llegada del compañero abierto en el triple» (`shot-114234-1-25`); (2) los pases largos y arriesgados, «el pase es arriesgado» (`shot-114243-4-140`, 37 ft con viabilidad 0,77).

Queda además el único `mal` del frame (`shot-114086-3-68`, «cuando marca los pasos en la entrada»): una bandeja que el frame juzga en el último bote, 1,8 s antes de la suelta, mientras el entrenador sitúa la decisión en los pasos de la recogida. No se cambia con un solo caso; se vigilará si se repite.
