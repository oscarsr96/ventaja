# Ventaja glossary

How to read what the tools return. Numbers in this text are the ones the code uses.

## Decision frame
The decision frame is the moment the shot was decided, earlier than the release (ADR-0003).
For jump shots it is about $GATHER_FRAMES frames (0.4 s) before the release, at the gather.
For finishes (layup, dunk, hook, lob, floater) it is the last dribble or, without one, the
start of the touch. Shots with no touch, no type or no tracking there are excluded and
cannot be explained.

## Option value and viability
The value of an option is the probability of scoring times its points (expected points).
The shot always has viability 1. A pass has a viability that is a heuristic multiplier, not
a probability (ADR-0004):
- 0 when the possession clock is under $SHOT_CLOCK_MIN_PASS s (no time to pass and shoot).
- Otherwise full up to $PASS_DISTANCE_SOFT ft, falling linearly to 0 at $PASS_DISTANCE_HARD ft.
- Multiplied by $LANE_BLOCKED_FACTOR when a defender is in the passing lane (`lane_blocked`).
- An unknown clock does not penalise.
`adjusted_value` is value times viability.

## Decision cost and good_read
The best alternative is the pass with the highest `adjusted_value`. `cost` is the best
alternative minus the shot value, never below zero. `good_read` is true when the best
alternative does not exceed the shot. When no pass is viable there is no alternative: the
cost is 0 and `good_read` is null, because there was no read to make. Shares of good reads
use only the non-null rows. `confidence` is the share of the ten players detected (not
extrapolated) at the decision frame (ADR-0004).

## Advantage curve verdicts
The curve values, about every 5 frames (5 Hz) of the possession, the best option of the
ball handler. A row is advantage when the best pass is worth at least the real shot plus
$ADVANTAGE_TOLERANCE points. A streak is consecutive advantage rows with the same ball handler;
the verdict looks at the last streak starting at or before the decision frame (ADR-0006):
- `late`: that streak ended before the decision frame; `release_lag_seconds` is the gap.
- `during`: the decision frame falls inside the streak (it may have started earlier).
- `none`: no advantage row at or before the decision frame.
- `no_window`: the curve has fewer than $CURVE_MIN_ROWS rows.
`held_to_decision` is a separate flag, true only for a `late` streak of the shooter who kept
the ball until the decision frame: a lost moment. A `late` without it means the advantage
was used (the ball moved to someone else) or belonged to an earlier ball handler.

## Shot-clock bands
Decisions are bucketed by the possession clock at the decision frame: $CLOCK_BANDS (seconds
left). Lost moments with under $LATE_MIN_CLOCK s are not ranked, because the window closes
when the clock voids the passes, not because the shooter ignored it (ADR-0006).

## Possession clock
A clock at 0.0 that was reached by a countdown within the previous $SHOT_CLOCK_EXPIRY_LOOKBACK
frames is expired and voids the passes. A 0.0 without that countdown means the clock is off
and is read as unknown (ADR-0007).

## Confidence
The reel rankings use decisions with `confidence` of at least $MIN_RANK_CONFIDENCE (ADR-0006).
`rank_players` and `player_profile` read the player cards instead (ADR-0008).

## Player-card thresholds
A card states a tendency only from at least $PROFILE_MIN_SHOTS readable shots and compares
the player against the league row (ADR-0008).

## What if
`what_if` moves up to $BOARD_MAX_MOVES players of a decision frame to a point of the half
court (feet, offense orientation, clamped to the court) and values the shot again. A moved
player is placed, not running: velocity is 0, and a pass from a stopped player is valued
differently from one on the run (ADR-0009).

## Known limits
- The defence does not react to a moved player: only the positions you set change.
- Only 10 ACB games carry tracking; the rest of the season is aggregates.
- The value model was trained on those same 10 games, and the season priors include them
  (ADR-0004), so the figures may be somewhat optimistic.
- Moved players have zero velocity.
- A player or team absent from `list_games` has no tracked decisions.

## ADR pointers
ADR-0003 decision frame; ADR-0004 value model, viability and cost; ADR-0006 advantage curve
and reel; ADR-0007 possession clock; ADR-0008 player card; ADR-0009 whiteboard and packaged
frames.
