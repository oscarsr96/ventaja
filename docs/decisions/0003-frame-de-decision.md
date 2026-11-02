# ADR-0003: frame de decisión

## Contexto

La capa 1 valora cada tiro en el momento en que se decide, no en el de la suelta. Medirlo en `start_frame` (la suelta) falsea las finalizaciones: el 44 % ya está en el aire en ese instante, y en ellas la mediana entre el último bote y la suelta es de 1,2 s (p10 0,8 s, p90 2,4 s); 268 de las 682 finalizaciones no tienen ningún bote. El `releaseTime` mediano es de 1,8 s (1,12 s en tiros en suspensión, 2,2 s en bandejas). Sobre los 1 459 tiros de los 10 partidos, los tipos son: layup 486, dribblePullUp 277, catchAndShoot 230, offMove 141, floater 71, hook 69, dunk 42, tip 38, stepback 30, sin tipo 26, postFadeaway 16, lob 11, shakeAndRaise 10, heave 9 y leaner 3; 81 tiros no tienen `touch_id`.

## Decisión

Óscar (entrenador y dueño del proyecto) decide retrasar el frame de bandejas y mates al último bote o al inicio del toque, en lugar de medirlos siempre en la suelta. Reglas, en `decision/frame.py`:

- Sin `touch_id`, sin tipo o de tipo `tip`: `excluded` (`no_touch`, `no_type`, `tip`).
- Tiros en suspensión (`JUMP_SHOT_TYPES`): `max(start_frame - GATHER_FRAMES, touch.start_frame)`, regla `gather`. `GATHER_FRAMES = 10` (0,4 s) aproxima el inicio del gather, por debajo de la mediana de 1,12 s de los lanzadores.
- Finalizaciones (`FINISH_TYPES`: layup, dunk, hook, lob, floater): último bote con `frame <= start_frame` (`last_dribble`); si no hay, `touch.start_frame` (`touch_start`). Desde la enmienda del 2 de noviembre, nunca más de `FINISH_MAX_LAG_FRAMES = 60` frames antes de la suelta (ver abajo).
- Tipo no listado: `excluded` con `unknown_type:<tipo>`.
- Si el frame elegido no tiene tracking se avanza hasta `NO_TRACKING_LOOKAHEAD = 10` frames (0,4 s); si ninguno tiene, `excluded` con `no_tracking`.

Todas las constantes viven en `value/params.py` y solo cambian mediante un ADR. Alternativa descartada: medir siempre en el frame de la suelta; es lo más simple, pero evalúa la defensa y el espacio cuando la finalización ya no tiene vuelta atrás.

## Consecuencias

Cada tiro tiene un frame de decisión propio y los tiros excluidos se contabilizan con su motivo en lugar de descartarse en silencio. `ventaja snapshot SHOT_ID --decision` permite inspeccionarlo. El coste es que `GATHER_FRAMES` es una aproximación fija y que las finalizaciones sin bote dependen del inicio del toque, que puede ser anterior a la intención real de tirar.

## Enmienda 2026-11-02: tope de retraso en finalizaciones

La regla original no ponía límite al tiempo entre el frame de decisión de una finalización y su suelta. En la revisión final de la capa 1, con el modelo de entonces, 24 de las 649 finalizaciones válidas se juzgaban más de 60 frames (2,4 s) antes de la suelta (12 con `last_dribble` y 12 con `touch_start`), con máximos de 4,1 s (102 frames, `last_dribble`) y 9,3 s (233 frames, `touch_start`). El tiro de mayor coste de toda la muestra, `shot-114243-3-108`, se juzgaba 100 frames antes de soltar el balón: a esa distancia temporal ya no se evalúa la decisión de tirar, sino una jugada anterior (un bote lejano en transición o la recepción en el otro campo).

Decisión: para `FINISH_TYPES`, `frame = max(candidato, start_frame − FINISH_MAX_LAG_FRAMES)`, con `FINISH_MAX_LAG_FRAMES = 60` (2,4 s, el p90 del tiempo entre último bote y suelta citado en el contexto) en `value/params.py`. El candidato sigue siendo el último bote o el inicio del toque y el nombre de la regla no cambia (`last_dribble` / `touch_start`); después se aplica igual que antes la búsqueda de `NO_TRACKING_LOOKAHEAD` frames si el frame no tiene tracking. Los tiros en suspensión no cambian: su retraso ya está acotado por `GATHER_FRAMES`. El tope es una aproximación más que se revisa en la sesión en vivo (pregunta 6 de `docs/review/README.md`).

Resultado tras regenerar: ninguna finalización supera ya los 60 frames (máximo 60 en `last_dribble` y en `touch_start`; medianas de 30 y 25 frames) y el número de tiros válidos no cambia (1 351). `shot-114243-3-108` se juzga ahora 60 frames antes de la suelta y sigue siendo el tiro de mayor coste (1,539 puntos).
