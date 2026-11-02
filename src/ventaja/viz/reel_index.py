"""The reel's ``index.md`` (Spanish): a header, then one table and its GIFs per ranking."""

from collections.abc import Mapping
from datetime import date
from typing import Any

import polars as pl

from ventaja.value.params import MIN_RANK_ADVANTAGE, MIN_RANK_CONFIDENCE

__all__ = ["SECTIONS", "UNAVAILABLE", "write_index"]

UNAVAILABLE = "(clip no disponible"

# (ranking key, heading, metric column header)
SECTIONS = (
    ("worst", "Peores decisiones", "Coste"),
    ("best", "Mejores lecturas", "Margen"),
    ("late", "Momentos perdidos", "Retraso"),
)

_INTRO = {
    "worst": (
        "Los tiros con mayor coste en el frame de decisión: la mejor alternativa de pase "
        "valía más que el tiro (coste = mejor alternativa − tiro)."
    ),
    "best": (
        "Buenas lecturas (el tiro valía al menos lo que el mejor pase) ordenadas por margen "
        "= tiro − mejor alternativa."
    ),
    "late": (
        "Veredicto `late` de la curva: el tirador tuvo una ventaja de al menos "
        f"{MIN_RANK_ADVANTAGE:.1f} s, se le cerró y siguió con el balón hasta tirar "
        "(`held_to_decision`). Ordenados por el retraso entre el fin de la ventaja y el frame "
        "de decisión; el clip empieza antes para que se vea la ventana."
    ),
}


def _num(value: float | None, spec: str = ".2f") -> str:
    return "—" if value is None else format(value, spec).replace(".", ",")


def _metric(kind: str, row: Mapping[str, Any]) -> str:
    if kind == "worst":
        return f"{_num(row['cost'])} pts"
    if kind == "best":
        return f"{_num(row['margin'])} pts"
    return (
        f"{_num(row['release_lag_seconds'], '.1f')} s "
        f"(ventaja {_num(row['advantage_seconds'], '.1f')} s)"
    )


def _row(kind: str, row: Mapping[str, Any]) -> str:
    clock = "—" if row["shot_clock"] is None else f"{_num(row['shot_clock'], '.1f')} s"
    alt = (
        "—"
        if row["best_alt_value"] is None
        else f"{row['best_alt_player']} ({row['best_alt_type']}) {_num(row['best_alt_value'])}"
    )
    cells = [
        str(row["rank"]),
        row["game_label"],
        f"{row['shooter']} ({row['team']})",
        f"{row['period']}.º · {clock}",
        f"{_num(row['shot_value'])} ({row['rule']})",
        alt,
        _metric(kind, row),
        row["headline_es"] or "—",
    ]
    return "| " + " | ".join(c.replace("|", "/") for c in cells) + " |"


def _section(
    kind: str,
    heading: str,
    metric: str,
    table: pl.DataFrame,
    gifs: Mapping[tuple[str, str], str],
    failures: Mapping[tuple[str, str], str],
) -> list[str]:
    lines = [f"## {heading}", "", _INTRO[kind], ""]
    if table.height == 0:
        return [*lines, "Ningún tiro cumple el filtro.", ""]
    lines += [
        f"| # | Partido | Jugador | Cuarto y reloj | Tiro | Mejor alternativa | {metric} "
        "| Titular |",
        "|---:|---|---|---|---|---|---|---|",
        *(_row(kind, r) for r in table.iter_rows(named=True)),
        "",
    ]
    for r in table.iter_rows(named=True):
        lines += [f"### {r['rank']}. {r['shot_id']} — {r['shooter']}", ""]
        gif = gifs.get((kind, r["shot_id"]))
        reason = failures.get((kind, r["shot_id"]), "sin clip")
        lines += [f"![{r['shot_id']}]({gif})" if gif else f"{UNAVAILABLE}: {reason})", ""]
    return lines


def write_index(
    tables: Mapping[str, pl.DataFrame],
    gifs: Mapping[tuple[str, str], str],
    failures: Mapping[tuple[str, str], str],
    *,
    game_ids: list[int],
    game_labels: list[str],
    trained_at: str,
    n: int,
    excluded_low_confidence: int,
) -> str:
    """Markdown of the reel: header, then the three sections with their tables and GIFs."""
    games = ", ".join(f"{label} ({g})" for g, label in zip(game_ids, game_labels, strict=True))
    lines = [
        "# Reel de decisiones — capa 2",
        "",
        f"- Fecha: {date.today().isoformat()}",
        f"- Partidos ({len(game_ids)}): {games}",
        f"- Modelo: entrenado el {trained_at}",
        f"- Top {n} por sección. Filtro común: regla no excluida y confidence ≥ "
        f"{_num(MIN_RANK_CONFIDENCE, '.1f')} (jugadores detectados en el frame de decisión); "
        f"{excluded_low_confidence} decisiones quedaron fuera por confianza. Peores y mejores "
        "exigen además algún pase viable en el frame de decisión; los momentos perdidos no.",
        f"- Clips: {sum(t.height for t in tables.values()) - len(failures)} generados, "
        f"{len(failures)} clips no disponibles.",
        "",
        "Cada clip muestra la pista arriba (atacantes coloreados por el valor de su opción, "
        "flecha roja a la mejor alternativa en el frame de decisión) y la curva de ventaja "
        "abajo: en naranja la ventana del veredicto, en gris las ventajas anteriores (de "
        "otros jugadores con balón o del mismo antes de la ventana). El reloj es el de posesión.",
        "",
    ]
    for kind, heading, metric in SECTIONS:
        lines += _section(kind, heading, metric, tables[kind], gifs, failures)
    return "\n".join(lines)
