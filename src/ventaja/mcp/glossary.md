# Ventaja glossary

How to read what the tools return. Every threshold below is the one the code uses.

## Decision frame
The decision frame is the moment the ball handler commits to the shot. Each shot is valued
there: the ten players' positions, the options (the shot and each possible pass) and the
shooter's choice. Shots without a reliable frame are excluded and cannot be explained
(ADR-0003).

## Option value and viability
Each option has a value in expected points: probability of scoring times points. A pass is
discounted by its viability, the chance that the pass lane stays open and the pass arrives;
the discounted figure is `adjusted_value`. A blocked lane is flagged `lane_blocked`
(ADR-0004, ADR-0005).

## Decision cost and good_read
`cost` is the expected points the best alternative would have added over the shot taken, at
the decision frame, never below zero. `mean_cost` is its average over a player's readable
shots. `good_read` is true when the shot was at least as good as every alternative within
the tolerance, false when a better option was ignored, null when the shot cannot be read.

## Advantage curve verdicts
The curve follows the ball handler's best option along the possession, sampled at 5 Hz. A
row is advantage when the best pass beats the shot by more than $ADVANTAGE_TOLERANCE points.
The verdict says what happened to that window (ADR-0006):
- `late`: an advantage appeared and was held until after the decision moment; the shot came
  late.
- `during`: the advantage existed only at the decision moment.
- `none`: no advantage along the possession.
- `no_window`: the curve is too short to tell.

## Shot-clock bands
Decisions are bucketed by the seconds left on the shot clock: $CLOCK_BANDS. Lost moments with
under $LATE_MIN_CLOCK seconds of possession at the decision frame are not ranked. A possession
clock at 0.0 means "off", not zero (ADR-0007).

## Confidence
`confidence` is the share of the ten players detected at the decision frame. Rankings only
use decisions with a confidence of at least $MIN_RANK_CONFIDENCE.

## Player-card thresholds
A tendency is stated only from at least $PROFILE_MIN_SHOTS readable shots; rankings and cards
compare against the league row (ADR-0008).

## What if
`what_if` moves up to $BOARD_MAX_MOVES players of a decision frame to a point of the half
court (feet, offense orientation, clamped to the court) and values the shot again. Moved
players have zero velocity (ADR-0009).

## Known limits
- The defence does not react to a moved player: only the positions you set change.
- Only 10 ACB games carry tracking; the rest of the season is aggregates.
- The value model was trained on those same 10 games, so figures describe them, not the
  league.
- Moved players have zero velocity, so passes projected from them are conservative.
- A name absent from `list_games` has no tracked decisions.

## ADR pointers
ADR-0001 tracking orientation; ADR-0002 raw, build and artifacts; ADR-0003 decision frame;
ADR-0004 value model, viability and cost; ADR-0005 pass lane; ADR-0006 advantage curve;
ADR-0007 possession clock; ADR-0008 player card; ADR-0009 whiteboard and packaged frames.
