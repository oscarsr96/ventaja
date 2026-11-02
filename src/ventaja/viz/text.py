"""Plain-text option table shared by ``ventaja decisions show`` and the review kit."""

from collections.abc import Mapping
from typing import Any

import polars as pl

from ventaja.model.decision import Option

__all__ = ["format_option_table"]


def _mark(row: Mapping[str, Any], shooter_id: int, best_alt_player_id: int | None) -> str:
    if row["player_id"] == shooter_id:
        return "*"
    if best_alt_player_id is not None and row["player_id"] == best_alt_player_id:
        return ">"
    return " "


def format_option_table(
    options: list[Option] | pl.DataFrame,
    *,
    shooter_id: int,
    best_alt_player_id: int | None,
    names: Mapping[int, str] | None = None,
) -> str:
    """Header plus one line per option, ``*`` on the shooter and ``>`` on the best alternative.

    ``options`` are ``Option`` objects or rows of the ``decision_options`` table, printed in the
    given order. With ``names`` a trailing player-name column is added.
    """
    rows = (
        list(options.iter_rows(named=True))
        if isinstance(options, pl.DataFrame)
        else [o.model_dump() for o in options]
    )
    header = (
        f"  {'player_id':>9} {'type':5} {'zone':16} {'P':>5} {'value':>6} "
        f"{'viab':>5} {'adj':>6} {'alternative':11}"
    )
    lines = [f"{header} name" if names is not None else header.rstrip()]
    for o in rows:
        line = (
            f"{_mark(o, shooter_id, best_alt_player_id)} {o['player_id']:>9} "
            f"{o['option_type']:5} {o['zone']:16} {o['proba']:>5.2f} {o['value']:>6.3f} "
            f"{o['viability']:>5.2f} {o['adjusted_value']:>6.3f} "
            f"{o['alternative_type'] or '-':11}"
        )
        if names is not None:
            line = f"{line} {names.get(o['player_id'], '-')}"
        lines.append(line.rstrip())
    return "\n".join(lines)
