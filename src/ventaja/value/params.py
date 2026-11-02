"""Every layer-1 constant lives here and changes only via an ADR."""

# Frames (25 fps) of the gather before release: 10 frames = 0.4 s (ADR-0003).
GATHER_FRAMES = 10
# Frames searched forward when the decision frame has no tracking (ADR-0003).
NO_TRACKING_LOOKAHEAD = 10
# Maximum lag of a finish's decision frame before release: 60 frames = 2.4 s, the p90 of
# the last-dribble-to-release time (ADR-0003, amendment 2026-11-02).
FINISH_MAX_LAG_FRAMES = 60

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

# Pass projection: the receiver is evaluated where he will be when the ball arrives.
PASS_SPEED = 40.0  # ft/s, assumed ball speed of a pass
FLIGHT_MIN = 0.2  # s, lower clamp of the flight time
FLIGHT_MAX = 1.0  # s, upper clamp of the flight time
PROJECTION_CAP = 10.0  # ft, maximum displacement applied to a receiver
# Geometry of defensive pressure.
LANE_WIDTH = 3.0  # ft, a defender closer than this to the passer->receiver segment is in the lane
LANE_END_MARGIN = 2.0  # ft, segment ends ignored (a defender guarding passer or receiver)
# Lane rule (ADR-0005): a defender mid-lane blocks only if the receiver is not open or the
# passer is driving; a defender near either end of the segment always blocks.
LANE_END_ZONE = 6.0  # ft, a lane defender this close to either end of the segment always blocks
LANE_OPEN_RECEIVER = 6.0  # ft, receiver's nearest defender at least this far: open for a lob pass
LANE_DRIVING_SPEED = 4.0  # ft/s, passer moving to the hoop at least this fast: no time to lob
BETWEEN_WIDTH = 3.0  # ft, a defender this close to the player->hoop segment is between them
# A raw shot clock of exactly this value is the clock switched off (end of period, or not
# running), not a clock at zero: the snapshot reads it as unknown, ``None``, unless it was
# reached by a countdown within ``SHOT_CLOCK_EXPIRY_LOOKBACK`` frames (ADR-0007).
SHOT_CLOCK_OFF = 0.0
# Frames (1 s) searched back from a 0.0 reading: a 0.0 reached by a countdown within them is
# a clock that has just run out (expired, stays 0.0), not a clock switched off (ADR-0007).
SHOT_CLOCK_EXPIRY_LOOKBACK = 25
# Shot clock below this many seconds sets the ``shot_clock_low`` flag.
SHOT_CLOCK_LOW = 4.0

# Pass viability (ADR-0004): a simple, visible discount, not a learned model.
SHOT_CLOCK_MIN_PASS = 2.0  # s, below this shot clock no pass is viable
LANE_BLOCKED_FACTOR = 0.4  # viability multiplier when a defender sits in the passing lane
PASS_DISTANCE_SOFT = 30.0  # ft, passes up to this length keep full viability
PASS_DISTANCE_HARD = 60.0  # ft, viability falls linearly to zero at this length
# Classification of the ignored alternative.
OPEN_DEF_DIST = 6.0  # ft, nearest defender at least this far makes the option "open"
CUT_SPEED = 4.0  # ft/s toward the hoop that makes a paint option a "cut"

# Advantage curve (layer 2): the best option of the ball handler sampled along the possession.
# Frames between curve samples (25 fps / 5 = 5 Hz), counted back from release; the decision
# frame is sampled too, off this grid when it falls between two step frames (ADR-0006).
CURVE_STEP_FRAMES = 5
ADVANTAGE_TOLERANCE = 0.10  # pts, a row is advantage when its best pass beats the shot by this
CURVE_MIN_ROWS = 3  # curves with fewer rows get no advantage window (verdict ``no_window``)

# Possession clip (layer 2): the court and the advantage curve animated together.
CLIP_BEFORE_S = 3.0  # s shown before the decision frame (as the layer-1 review GIFs)
CLIP_AFTER_S = 1.0  # s shown after the release, so the ball's flight is visible

# Rankings and reel (layer 2): which decisions are trusted enough to rank, and the late clips.
MIN_RANK_CONFIDENCE = 0.8  # share of the ten players detected at the decision frame
MIN_RANK_ADVANTAGE = 0.4  # s, a lost moment needs an advantage of at least two sampled rows
LATE_MIN_CLOCK = (
    2.5  # s of possession at the decision frame below which a lost moment is not ranked
)
REEL_LATE_LEAD_S = 1.0  # s shown before a late clip's window starts
REEL_LATE_MAX_BEFORE_S = 12.0  # s, cap of a late clip's lead before the decision frame

# Player card (layer 3): shot-clock buckets and the kinds of ignored alternative.
# (label, lower bound exclusive, upper bound inclusive); the last bucket also includes 0.0.
# Same membership as the buckets of ``validate.decisions.cost_falls_with_clock``.
CLOCK_BUCKETS = (("24-14", 14.0, 24.0), ("14-6", 6.0, 14.0), ("6-0", 0.0, 6.0))
# Types of ``best_alt_type`` a card counts as an ignored alternative, in tie-break order.
ALT_TYPES = ("rim_cut", "open_corner", "extra_pass", "post", "other")

# Player card profile phrase (layer 3): thresholds of the rules that write the phrase.
PROFILE_MIN_SHOTS = 8  # readable shots needed to state a tendency
# pts of mean cost over (or under) the league for "leaves options" / clock rule
PROFILE_COST_DELTA = 0.05
PROFILE_READ_DELTA = 0.08  # share of good reads over the league for "picks the shot well"
PROFILE_LATE_SHARE = 0.25  # share of lost moments held to the decision, among shots with a curve
PROFILE_ALT_MIN = 3  # decisions needed to name the alternative the player most often leaves
PROFILE_ZONE_SHIFT = 0.15  # change of zone mix against the season that is worth mentioning
# share of catch-and-shoot / contested season attempts over the league that is worth mentioning
PROFILE_SEASON_DELTA = 0.10
