"""Kit of the live review session (spec 5.5): a stratified sample of shots as GIFs + review.md."""

import random
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from ventaja.config import Settings
from ventaja.data.load import load_decisions, load_meta
from ventaja.decision.align import Aligner
from ventaja.decision.cost import ShooterOffCourtError, decide
from ventaja.errors import DataNotFoundError, NoTrackingError
from ventaja.model.decision import Decision
from ventaja.value.model import ValueModel
from ventaja.value.priors import Priors
from ventaja.viz.animate import render_shot_gif
from ventaja.viz.text import format_option_table

__all__ = ["RULES", "allocate", "review_kit"]

RULES = ("gather", "last_dribble", "touch_start")
REVIEW_LINES = ("Frame de decisión: ok / mal → ", "Opciones valoradas: ok / mal → ", "Comentario: ")


@dataclass(frozen=True)
class _Candidate:
    game_id: int
    shot_id: str
    rule: str
    release_frame: int


def allocate(counts: dict[str, int], n: int) -> dict[str, int]:
    """Split ``n`` across rules in proportion to ``counts`` (largest-remainder rounding).

    Every present rule gets at least one shot when ``n >= 3``; no rule gets more than it has.
    """
    total = sum(counts.values())
    if n >= total:
        return dict(counts)
    exact = {r: n * c / total for r, c in counts.items()}
    quota = {r: int(q) for r, q in exact.items()}
    by_remainder = sorted(counts, key=lambda r: exact[r] - quota[r], reverse=True)
    for r in by_remainder[: n - sum(quota.values())]:
        quota[r] += 1
    if n >= len(RULES):
        for r in counts:
            if counts[r] and not quota[r]:
                donor = max(quota, key=lambda k: quota[k])
                quota[donor] -= 1
                quota[r] = 1
    return quota


def _candidates(aligner: Aligner, settings: Settings) -> list[_Candidate]:
    """Non-excluded shots of a game: from its built decisions table, else from decision frames."""
    g = aligner.game_id
    if settings.decisions_parquet(g).exists():
        df = load_decisions(g, settings).filter(pl.col("rule") != "excluded")
        return [
            _Candidate(g, r["shot_id"], r["rule"], r["release_frame"])
            for r in df.iter_rows(named=True)
        ]
    out: list[_Candidate] = []
    for shot in aligner._shots.iter_rows(named=True):
        frame = aligner.decision_frame(shot["id"])
        if frame.rule != "excluded":
            out.append(_Candidate(g, shot["id"], frame.rule, shot["start_frame"]))
    return out


def _sample(
    candidates: list[_Candidate],
    quota: dict[str, int],
    seed: int,
    aligners: dict[int, Aligner],
    priors: Priors,
    model: ValueModel,
) -> list[Decision]:
    """Draw ``quota[rule]`` decided shots per rule, without replacement, in a seeded order.

    Shots that cannot be decided (shooter off court, no tracking) are skipped and the next
    shot of the shuffled pool takes their place.
    """
    rng = random.Random(seed)
    picked: list[Decision] = []
    for rule in RULES:
        pool = sorted(
            (c for c in candidates if c.rule == rule),
            key=lambda c: (c.game_id, c.release_frame, c.shot_id),
        )
        rng.shuffle(pool)
        taken = 0
        for c in pool:
            if taken >= quota.get(rule, 0):
                break
            try:
                d = decide(aligners[c.game_id], c.shot_id, priors, model)
            except (ShooterOffCourtError, NoTrackingError):
                continue
            if d is not None:
                picked.append(d)
                taken += 1
    return sorted(picked, key=lambda d: (d.game_id, d.release_frame))


def _players(settings: Settings) -> pl.DataFrame | None:
    try:
        return load_meta("players", settings)
    except DataNotFoundError:
        return None


def _read(good_read: bool | None) -> str:
    if good_read is None:
        return "— (ningún pase viable)"
    return "sí" if good_read else "no"


def _section(i: int, d: Decision, names: dict[int, str] | None) -> str:
    clock = "—" if d.shot_clock is None else f"{d.shot_clock:.1f} s"
    table = format_option_table(
        d.options, shooter_id=d.shooter_id, best_alt_player_id=d.best_alt_player_id, names=names
    )
    return "\n".join(
        [
            f"## {i}. {d.shot_id}",
            "",
            f"regla {d.rule} · frame de decisión {d.decision_frame} · lanzamiento "
            f"{d.release_frame} · reloj {clock} · coste {d.cost:.3f} · "
            f"good_read {_read(d.good_read)} · confidence {d.confidence:.1f}",
            "",
            f"![{d.shot_id}]({d.shot_id}.gif)",
            "",
            "```text",
            table,
            "```",
            "",
            *(line for review in REVIEW_LINES for line in (review, "")),
        ]
    )


def review_kit(
    settings: Settings,
    game_ids: list[int],
    n: int,
    seed: int,
    out_dir: Path,
    *,
    model: ValueModel | None = None,
    priors: Priors | None = None,
    before_s: float = 3.0,
    after_s: float = 1.0,
    fps: int = 12,
) -> Path:
    """Sample ``n`` valid shots stratified by rule, render one GIF each and write review.md.

    Returns ``out_dir / "review.md"``. Raises DataNotFoundError if the versioned model is
    missing (and no ``model`` is given).
    """
    model = model or ValueModel.default()
    priors = priors or Priors.from_settings(settings)
    aligners = {g: Aligner(g, settings) for g in game_ids}
    candidates = [c for g in game_ids for c in _candidates(aligners[g], settings)]
    counts = Counter(c.rule for c in candidates)
    quota = allocate({r: counts.get(r, 0) for r in RULES}, n)
    sample = _sample(candidates, quota, seed, aligners, priors, model)
    players = _players(settings)
    names = (
        {
            r["player_id"]: f"{r['first_name']} {r['last_name']}"
            for r in players.iter_rows(named=True)
        }
        if players is not None
        else None
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    for d in sample:
        jerseys = (
            {
                r["player_id"]: r["jersey"]
                for r in players.filter(pl.col("game_id") == d.game_id).iter_rows(named=True)
            }
            if players is not None
            else None
        )
        render_shot_gif(
            aligners[d.game_id],
            d,
            out_dir / f"{d.shot_id}.gif",
            before_s=before_s,
            after_s=after_s,
            fps=fps,
            labels=jerseys,
        )
    split = ", ".join(f"{r} {sum(d.rule == r for d in sample)}" for r in RULES)
    population = ", ".join(f"{r} {counts.get(r, 0)}" for r in RULES)
    header = "\n".join(
        [
            "# Revisión en vivo de la capa 1 — muestra de posesiones",
            "",
            f"- Fecha: {date.today().isoformat()}",
            f"- Partidos: {', '.join(str(g) for g in game_ids)}",
            f"- Muestra: n {len(sample)} (pedidos {n}), seed {seed}; por regla: {split}",
            f"- Tiros válidos de partida por regla: {population}",
            f"- Modelo: entrenado el {model.trained_at or '—'} con {model.trained_on}",
            "",
            "Leyenda: atacantes coloreados por el valor ajustado de su opción (viridis, "
            "0,6-1,5 pts), defensores en gris, balón naranja, tirador con borde negro. En el "
            "frame de decisión la animación se congela 1 s: círculos huecos en la posición "
            "proyectada de cada receptor y flecha roja a la mejor alternativa. En la tabla, "
            "`*` es el tirador y `>` la mejor alternativa.",
            "",
        ]
    )
    body = "\n".join(_section(i, d, names) for i, d in enumerate(sample, start=1))
    path = out_dir / "review.md"
    path.write_text(f"{header}\n{body}")
    return path
