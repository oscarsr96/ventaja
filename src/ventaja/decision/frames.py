"""Decision frames of the valued shots, packaged for the whiteboard.

One row per entity (five attackers, five defenders, the ball) of each valued shot's decision
frame, so the whiteboard can redraw a ``Snapshot`` without tracking data.
"""

from pathlib import Path
from typing import Any

import polars as pl

from ventaja.config import Settings
from ventaja.data.build import _write_parquet_atomic
from ventaja.data.load import load_decisions, load_meta
from ventaja.decision.align import Aligner
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.model.snapshot import BallPos, PlayerPos, Snapshot

__all__ = ["FRAME_SCHEMA", "ROSTER_FILE", "ROSTER_SCHEMA", "build_frames", "snapshot_from_frame"]

FRAME_SCHEMA: dict[str, Any] = {
    "shot_id": pl.String,
    "game_id": pl.Int64,
    "frame_idx": pl.Int64,
    "period": pl.Int64,
    "wall_clock": pl.Int64,
    "game_clock": pl.Float64,
    "shot_clock": pl.Float64,  # null when unknown
    "possession_id": pl.String,
    "chance_id": pl.String,  # null when the possession has no chance
    "off_team_id": pl.Int64,
    "def_team_id": pl.Int64,
    "side": pl.String,  # "offense" | "defense" | "ball"
    "player_id": pl.Int64,  # null on the ball row
    "team_id": pl.Int64,  # null on the ball row
    "x": pl.Float64,
    "y": pl.Float64,
    "z": pl.Float64,  # ball height; null on player rows
    "speed": pl.Float64,
    "is_detected": pl.Boolean,
    "pred_error": pl.Float64,  # null on the ball row
    "vx": pl.Float64,
    "vy": pl.Float64,
}
ROSTER_FILE = "roster.parquet"
ROSTER_SCHEMA: dict[str, Any] = {
    "player_id": pl.Int64,
    "name": pl.String,
    "jersey": pl.String,  # nullable
    "team_id": pl.Int64,
    "team": pl.String,
}
_N_PER_SIDE = 5


def _frame_rows(shot_id: str, snap: Snapshot) -> list[dict[str, Any]]:
    """The 11 rows of a snapshot: offense, defense, then the ball."""
    shared: dict[str, Any] = {
        "shot_id": shot_id,
        "game_id": snap.game_id,
        "frame_idx": snap.frame_idx,
        "period": snap.period,
        "wall_clock": snap.wall_clock,
        "game_clock": snap.game_clock,
        "shot_clock": snap.shot_clock,
        "possession_id": snap.possession_id,
        "chance_id": snap.chance_id,
        "off_team_id": snap.off_team_id,
        "def_team_id": snap.def_team_id,
    }
    rows = [
        {**shared, "side": side, "z": None, **p.model_dump()}
        for side, players in (("offense", snap.offense), ("defense", snap.defense))
        for p in players
    ]
    ball = snap.ball
    rows.append(
        {
            **shared,
            "side": "ball",
            "player_id": None,
            "team_id": None,
            "pred_error": None,
            **ball.model_dump(),
        }
    )
    return rows


def build_frames(game_id: int, settings: Settings, *, out_dir: Path | None = None) -> Path:
    """Write ``{game_id}.parquet`` (``FRAME_SCHEMA``): the decision frame of every valued shot.

    Valued shots are the rows of ``load_decisions`` with ``rule != "excluded"``; each yields
    11 rows (offense players, defense players, ball) from
    ``Aligner.snapshot_for_shot(shot_id, decision=True)``. Written to ``out_dir`` (default: the
    build's ``frames/``). Returns the path.
    """
    aligner = Aligner(game_id, settings)
    valued = load_decisions(game_id, settings).filter(pl.col("rule") != "excluded")
    rows: list[dict[str, Any]] = []
    for shot_id in valued["shot_id"]:
        rows.extend(_frame_rows(shot_id, aligner.snapshot_for_shot(shot_id, decision=True)))
    out = out_dir if out_dir is not None else settings.frames_parquet(game_id).parent
    path = out / f"{game_id}.parquet"
    frames = pl.DataFrame(rows, schema=FRAME_SCHEMA)
    _write_parquet_atomic(frames, path)
    _update_roster(frames, settings, out)
    return path


def _update_roster(frames: pl.DataFrame, settings: Settings, out_dir: Path) -> None:
    """Merge the players of ``frames`` (from ``meta/``) into ``roster.parquet``.

    The file is the union of the existing roster and the new rows, deduplicated on
    ``player_id`` (new wins). Without ``meta/`` there is nothing to add and nothing is written.
    """
    try:
        players = load_meta("players", settings)
        games = load_meta("games", settings)
    except DataNotFoundError:
        return
    teams: dict[int, str] = {}
    for g in games.iter_rows(named=True):
        teams[g["home_team_id"]] = g["home_team_name"]
        teams[g["away_team_id"]] = g["away_team_name"]
    meta = {p["player_id"]: p for p in players.iter_rows(named=True)}
    seen = frames.filter(pl.col("player_id").is_not_null()).select("player_id", "team_id").unique()
    rows = [
        {
            "player_id": pid,
            "name": f"{meta[pid]['first_name']} {meta[pid]['last_name']}".strip(),
            "jersey": meta[pid]["jersey"],
            "team_id": tid,
            "team": teams.get(tid),
        }
        for pid, tid in seen.iter_rows()
        if pid in meta
    ]
    new = pl.DataFrame(rows, schema=ROSTER_SCHEMA)
    path = out_dir / ROSTER_FILE
    if path.exists():
        old = pl.read_parquet(path).cast(ROSTER_SCHEMA)  # type: ignore[arg-type]
        new = pl.concat([old, new])
    new = new.unique("player_id", keep="last", maintain_order=True)
    _write_parquet_atomic(new.sort("player_id"), path)


def snapshot_from_frame(rows: pl.DataFrame) -> Snapshot:
    """Rebuild the ``Snapshot`` of one shot from its frame rows.

    Raises ``VentajaError`` unless the rows hold exactly 10 players (five per side) and one
    ball. Players keep the order of the rows.
    """
    sides = rows["side"].to_list()
    if (
        rows.height != 2 * _N_PER_SIDE + 1
        or sides.count("offense") != _N_PER_SIDE
        or sides.count("defense") != _N_PER_SIDE
        or sides.count("ball") != 1
    ):
        raise VentajaError(
            f"a decision frame needs 10 players ({_N_PER_SIDE} per side) and 1 ball, "
            f"got {rows.height} rows: "
            f"{sides.count('offense')} offense, {sides.count('defense')} defense, "
            f"{sides.count('ball')} ball"
        )
    head = rows.row(0, named=True)
    by_side: dict[str, list[dict[str, Any]]] = {"offense": [], "defense": [], "ball": []}
    for r in rows.iter_rows(named=True):
        by_side[r["side"]].append(r)
    fields = tuple(PlayerPos.model_fields)
    return Snapshot(
        game_id=head["game_id"],
        frame_idx=head["frame_idx"],
        wall_clock=head["wall_clock"],
        period=head["period"],
        game_clock=head["game_clock"],
        shot_clock=head["shot_clock"],
        possession_id=head["possession_id"],
        chance_id=head["chance_id"],
        off_team_id=head["off_team_id"],
        def_team_id=head["def_team_id"],
        offense=[PlayerPos(**{k: r[k] for k in fields}) for r in by_side["offense"]],
        defense=[PlayerPos(**{k: r[k] for k in fields}) for r in by_side["defense"]],
        ball=BallPos(**{k: by_side["ball"][0][k] for k in BallPos.model_fields}),
    )
