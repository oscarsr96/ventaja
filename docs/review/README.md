# Sesión de revisión en vivo de la capa 1

Guion de la sesión de validación de cara de la capa 1 (spec 5.5), prevista para la **semana del 9 al 15 de noviembre de 2026**: una o dos horas, en directo, viendo una a una 20 posesiones animadas con Óscar como entrenador.

## Objetivo

El spec (5.5) exige, antes de abrir la capa siguiente, animar al menos 20 posesiones elegidas al azar y comprobar con un entrenador que **las opciones valoradas coinciden con lo que él ve**. No se mide la precisión del modelo (eso ya lo hace la validación leave-one-game-out de ADR-0004); se juzga si el método tiene sentido baloncestístico: si el frame de decisión (ADR-0003) es de verdad el momento de decidir y si el valor de cada opción (ADR-0004) ordena las opciones como lo haría un entrenador. Las discrepancias se registran y, si son sistemáticas, cambian el método antes de seguir.

## Cómo se generó la muestra

```bash
uv run ventaja review sample --all --n 20 --seed 7 --out docs/review/2026-11-sample
```

- Población: los tiros no excluidos de los 10 partidos (los que tienen frame de decisión y valoración en `decisions`).
- Muestra estratificada por regla de frame de decisión (`gather`, `last_dribble`, `touch_start`) en proporción a su frecuencia (redondeo por restos mayores, al menos un tiro por regla), sin reemplazo dentro de cada regla, con `random.Random(7)`. El reparto y los totales de partida están en la cabecera de `review.md`.
- Por cada tiro hay un GIF (`{shot_id}.gif`) desde 3 s antes del frame de decisión hasta 1 s después de la suelta, a 12 fps, solo con los frames de la posesión del tiro. Los GIF no se versionan: se regeneran con el comando de arriba (unos 45 s). Lo que sí se versiona es `review.md`.

Cómo leer el GIF: atacantes coloreados por el **valor ajustado** de su opción (escala fija 0,6-1,5 puntos, `viridis`: morado bajo, amarillo alto), defensores en gris, balón naranja, tirador con borde negro, dorsal encima de cada jugador. En el frame de decisión la animación se congela 1 s y aparecen la posición **proyectada** de cada receptor (círculo hueco, unido con puntos a su posición actual) y una flecha roja del tirador a la mejor alternativa. El título lleva tiro, regla, reloj de posesión y coste. Debajo de cada GIF, en `review.md`, la tabla de opciones (`*` tirador, `>` mejor alternativa) con probabilidad, valor, viabilidad y valor ajustado.

## Qué mirar en cada posesión

1. **¿El frame es el momento de decidir?** En tiros en suspensión es 0,4 s antes de la suelta (`gather`); en finalizaciones, el último bote (`last_dribble`) o el inicio del toque (`touch_start`). ¿Coincide con el instante en que tú dirías que el jugador ya ha decidido tirar? ¿Llega tarde (la decisión era antes, en la recepción o en el último pase) o pronto?
2. **¿Las opciones mejor valoradas coinciden con lo que ve un entrenador?** ¿El orden de la tabla (y los colores) es razonable? ¿Hay un compañero claramente libre al que el modelo no da valor, o uno marcado al que da demasiado?
3. **¿La proyección del cortador es razonable?** El receptor se valora donde estaría al llegar el pase (velocidad × tiempo de vuelo, con tope de 10 ft). ¿El círculo hueco cae donde iría el balón, o la proyección lleva al jugador a sitios absurdos (fuera de pista, detrás de la canasta)?
4. **¿Es creíble la bandera `lane_blocked`?** Se activa en un 59 % de los pases (con un margen de 2 ft en los extremos de la línea) y multiplica la viabilidad por 0,4. En la tabla se ve como `viab 0.40`. ¿De verdad había un defensor en la línea de pase o el pase era jugable?
5. **¿Son un problema las finalizaciones en transición juzgadas en un último bote lejos del aro?** 16 tiros válidos caen en zona `far`/`backcourt` porque el último bote ocurre lejos y se valoran desde allí. Si aparece alguno en la muestra, ¿tiene sentido evaluar la decisión en ese punto?

6. **¿Es razonable el tope de 2,4 s en finalizaciones?** Desde la enmienda de ADR-0003, una bandeja, mate, gancho, lob o floater nunca se juzga más de 60 frames (2,4 s) antes de la suelta, aunque el último bote o el inicio del toque sean anteriores. En los tiros afectados, ¿el frame congelado cae ya en la decisión de atacar el aro, o el tope corta demasiado pronto (o demasiado tarde)?

## Cómo se registran las discrepancias

En `docs/review/2026-11-sample/review.md`, cada tiro termina con tres líneas en blanco. Durante la sesión se rellenan así:

```text
Frame de decisión: ok / mal → mal: la decisión es en la recepción, 1 s antes
Opciones valoradas: ok / mal → ok
Comentario: el corte de 23 está bien proyectado; lane_blocked dudoso en el pase a 5
```

Se deja `ok` o `mal` (borrando el otro) y, tras la flecha, el motivo. Al terminar se cuentan los `mal` por tipo de problema y se versiona el `review.md` rellenado.

## Qué pasa después

- Si una discrepancia es **sistemática** (se repite en varias posesiones con la misma causa), se corrige el método: constantes en `value/params.py` (por ejemplo `LANE_END_MARGIN`, `LANE_BLOCKED_FACTOR`, `PROJECTION_CAP`, `GATHER_FRAMES`) o reglas en `decision/frame.py`, siempre mediante un **ADR nuevo**, y se regeneran el modelo y las decisiones. Esto ocurre **antes de abrir la capa 2**.
- Si las discrepancias son aisladas, se anotan como límites conocidos en la documentación de la capa 1 y no se cambia nada.
