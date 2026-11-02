# ADR-0003: frame de decisión

## Contexto

La capa 1 valora cada tiro en el momento en que se decide, no en el de la suelta. Medirlo en `start_frame` (la suelta) falsea las finalizaciones: el 44 % ya está en el aire en ese instante, y en ellas la mediana entre el último bote y la suelta es de 1,2 s (p10 0,8 s, p90 2,4 s); 268 de las 682 finalizaciones no tienen ningún bote. El `releaseTime` mediano es de 1,8 s (1,12 s en tiros en suspensión, 2,2 s en bandejas). Sobre los 1 459 tiros de los 10 partidos, los tipos son: layup 486, dribblePullUp 277, catchAndShoot 230, offMove 141, floater 71, hook 69, dunk 42, tip 38, stepback 30, sin tipo 26, postFadeaway 16, lob 11, shakeAndRaise 10, heave 9 y leaner 3; 81 tiros no tienen `touch_id`.

## Decisión

Óscar (entrenador y dueño del proyecto) decide retrasar el frame de bandejas y mates al último bote o al inicio del toque, en lugar de medirlos siempre en la suelta. Reglas, en `decision/frame.py`:

- Sin `touch_id`, sin tipo o de tipo `tip`: `excluded` (`no_touch`, `no_type`, `tip`).
- Tiros en suspensión (`JUMP_SHOT_TYPES`): `max(start_frame - GATHER_FRAMES, touch.start_frame)`, regla `gather`. `GATHER_FRAMES = 10` (0,4 s) aproxima el inicio del gather, por debajo de la mediana de 1,12 s de los lanzadores.
- Finalizaciones (`FINISH_TYPES`: layup, dunk, hook, lob, floater): último bote con `frame <= start_frame` (`last_dribble`); si no hay, `touch.start_frame` (`touch_start`).
- Tipo no listado: `excluded` con `unknown_type:<tipo>`.
- Si el frame elegido no tiene tracking se avanza hasta `NO_TRACKING_LOOKAHEAD = 10` frames (0,4 s); si ninguno tiene, `excluded` con `no_tracking`.

Todas las constantes viven en `value/params.py` y solo cambian mediante un ADR. Alternativa descartada: medir siempre en el frame de la suelta; es lo más simple, pero evalúa la defensa y el espacio cuando la finalización ya no tiene vuelta atrás.

## Consecuencias

Cada tiro tiene un frame de decisión propio y los tiros excluidos se contabilizan con su motivo en lugar de descartarse en silencio. `ventaja snapshot SHOT_ID --decision` permite inspeccionarlo. El coste es que `GATHER_FRAMES` es una aproximación fija y que las finalizaciones sin bote dependen del inicio del toque, que puede ser anterior a la intención real de tirar.
