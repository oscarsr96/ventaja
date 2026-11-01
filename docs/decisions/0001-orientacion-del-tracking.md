# ADR-0001: orientación del tracking

## Contexto

El tracking de SkillCorner llega en orientación de cámara, mientras que los eventos ya vienen en orientación de ataque (aro ofensivo en x negativa). Se verificó sobre los 156 tiros con `location` del partido 114243: al rotar el tracking 180° (`x, y → -x, -y`) cuando `possessions.left_hoop` es `False`, los 156 cuadran con la posición del evento a menos de 4 ft.

## Decisión

Toda la geometría del proyecto se hace en orientación de ataque, con el aro ofensivo en `HOOP = (-40.7, 0.0)` (ajustado sobre 1 433 tiros con error medio de 0,03 ft). La rotación se aplica una sola vez, al construir el `Snapshot` en `decision/align.py`, mediante `geometry.court.orient_to_offense` / `orient_frame`.

## Consecuencias

Nada aguas arriba de `align.py` lee `left_hoop`; los módulos posteriores asumen siempre el mismo marco y no necesitan ramas por sentido de ataque. El coste es que cualquier consumidor que lea tracking crudo fuera de `align.py` debe orientarlo explícitamente.
