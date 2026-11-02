"""Every layer-1 constant lives here and changes only via an ADR."""

# Frames (25 fps) of the gather before release: 10 frames = 0.4 s (ADR-0003).
GATHER_FRAMES = 10
# Frames searched forward when the decision frame has no tracking (ADR-0003).
NO_TRACKING_LOOKAHEAD = 10

# Shots judged at the start of the gather.
JUMP_SHOT_TYPES = (
    "catchAndShoot",
    "dribblePullUp",
    "offMove",
    "stepback",
    "shakeAndRaise",
    "postFadeaway",
    "leaner",
    "heave",
)
# Shots judged at the last dribble, or at the touch start if there is none.
FINISH_TYPES = ("layup", "dunk", "hook", "lob", "floater")
# Shot types that carry no decision.
EXCLUDED_TYPES = ("tip",)

# Prior shrinkage strength: pseudo-attempts at the league rate added to a player's record.
K_SHRINK = 20
