"""Plain-text rendering of player and team cards for ``ventaja player`` (labels in Spanish)."""

from ventaja.profile.card import PlayerCard, TeamCard
from ventaja.profile.phrase import ZONE_NAMES_ES, Lang
from ventaja.profile.season import MAIN_ZONES

__all__ = ["ALT_LABELS_ES", "render_card", "render_team"]

ALT_LABELS_ES = {
    "rim_cut": "corte al aro",
    "open_corner": "esquina abierta",
    "extra_pass": "pase extra",
    "post": "poste",
    "other": "otra",
}


def _num(value: float | int | None, spec: str = ".3f") -> str:
    return "-" if value is None else format(value, spec)


def _pct(value: float | int | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _games(games: list[int]) -> str:
    return f"{_plural(len(games), 'partido', 'partidos')} ({', '.join(map(str, games))})"


def _decision_blocks(card: PlayerCard | TeamCard, league: PlayerCard) -> list[str]:
    """Value, clock, alternatives and lost moments: what player and team cards share."""
    lines = [
        "",
        "Valor",
        f"  tiro {_num(card.mean_shot_value)} vs mejor alternativa "
        f"{_num(card.mean_best_alt_value)}  "
        f"[liga {_num(league.mean_shot_value)} vs {_num(league.mean_best_alt_value)}]",
        f"  coste medio {_num(card.mean_cost)}  [liga {_num(league.mean_cost)}]",
        f"  buena lectura {_pct(card.good_read_share)} de {card.n_readable} legibles  "
        f"[liga {_pct(league.good_read_share)}]",
        "",
        "Por reloj",
        f"  {'tramo':<7}{'n':>4}{'coste':>8}{'liga':>8}",
    ]
    for bucket, (n, cost) in card.clock.items():
        lines.append(f"  {bucket:<7}{n:>4}{_num(cost):>8}{_num(league.clock[bucket][1]):>8}")
    lines += ["", "Por alternativa", f"  {'alternativa':<16}{'n':>4}{'coste':>8}"]
    for alt, (n, cost) in card.alternatives.items():
        lines.append(f"  {ALT_LABELS_ES[alt]:<16}{n:>4}{_num(cost):>8}")
    lines += [
        "",
        "Momentos perdidos",
        f"  tarde con el balón en la mano: {card.n_late_held} de {card.n_with_summary} tiros "
        f"con curva ({_pct(card.late_held_share)}), retraso medio "
        f"{_num(card.mean_lag_held, '.1f')} s  [liga {_pct(league.late_held_share)}]",
        f"  tiro durante la ventaja: {_pct(card.during_share)}  [liga {_pct(league.during_share)}]",
    ]
    return lines


def _season_block(card: PlayerCard, league: PlayerCard) -> list[str]:
    s = card.season
    if s.get("season_attempts") is None:
        return ["", "Temporada", "  sin datos de temporada"]
    lines = [
        "",
        "Temporada",
        f"  {_plural(int(s['season_games'] or 0), 'partido', 'partidos')}, "
        f"{s['season_attempts']} tiros, TC {_pct(s['season_fg'])}, "
        f"triples {_pct(s['season_three_share'])}, "
        f"distancia media {_num(s['season_avg_distance'], '.1f')}",
        f"  tras recepción {_pct(s['season_cns_share'])} "
        f"[liga {_pct(league.season['season_cns_share'])}], "
        f"con mano encima {_pct(s['season_contested_share'])} "
        f"[liga {_pct(league.season['season_contested_share'])}], "
        f"TC sin defensor cerca {_pct(s['season_open_fg'])}",
        f"  {'zona':<18}{'seguidos':>10}{'temporada':>11}{'cambio':>8}",
    ]
    for z in MAIN_ZONES:
        tracked = card.tracked_zone.get(f"tracked_zone_share_{z}")
        shift = card.zone_shift.get(f"shift_{z}")
        shift = None if shift is None else round(shift, 2) + 0.0  # no "-0.00"
        lines.append(
            f"  {ZONE_NAMES_ES[z]:<18}{_pct(tracked):>10}"
            f"{_pct(s[f'season_zone_share_{z}']):>11}{_num(shift, '+.2f'):>8}"
        )
    lines.append(
        f"  {'otras':<18}{_pct(card.tracked_zone.get('tracked_zone_share_other')):>10}"
        f"  ({card.tracked_zone.get('tracked_attempts')} tiros seguidos)"
    )
    if s.get("season_drives") is None:
        lines.append("  penetraciones: sin datos")
    else:
        lines.append(
            f"  penetraciones {s['season_drives']}: pase fuera "
            f"{_pct(s['season_drive_kickout_share'])}, tiro tras bote "
            f"{_pct(s['season_drive_pullup_share'])}, cerca del aro "
            f"{_pct(s['season_drive_rim_share'])}"
        )
    return lines


def render_card(card: PlayerCard, league: PlayerCard, *, lang: Lang = "es") -> str:
    """The text card of a player against the league row; the phrase in ``lang``."""
    header = (
        f"{card.name} · {card.team or 'sin equipo'} · "
        f"{_plural(card.n_shots, 'tiro', 'tiros')} "
        f"({_plural(card.n_readable, 'legible', 'legibles')}) · "
        f"{_games(card.games)}"
    )
    phrase = card.phrase_es if lang == "es" else card.phrase_en
    lines = [header, *_decision_blocks(card, league), *_season_block(card, league)]
    return "\n".join([*lines, "", phrase or "-"])


def render_team(team: TeamCard, league: PlayerCard) -> str:
    """The text card of a team against the league row (no season, no phrase)."""
    header = (
        f"{team.team or team.team_id} · {_plural(team.n_players, 'jugador', 'jugadores')} · "
        f"{_plural(team.n_shots, 'tiro', 'tiros')} "
        f"({_plural(team.n_readable, 'legible', 'legibles')}) · "
        f"{_games(team.games)}"
    )
    return "\n".join([header, *_decision_blocks(team, league)])
