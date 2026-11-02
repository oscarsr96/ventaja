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

# Pass projection: the receiver is evaluated where he will be when the ball arrives.
PASS_SPEED = 40.0  # ft/s, assumed ball speed of a pass
FLIGHT_MIN = 0.2  # s, lower clamp of the flight time
FLIGHT_MAX = 1.0  # s, upper clamp of the flight time
PROJECTION_CAP = 10.0  # ft, maximum displacement applied to a receiver
# Geometry of defensive pressure.
LANE_WIDTH = 3.0  # ft, a defender closer than this to the passer->receiver segment is in the lane
LANE_END_MARGIN = 2.0  # ft, segment ends ignored (a defender guarding passer or receiver)
BETWEEN_WIDTH = 3.0  # ft, a defender this close to the player->hoop segment is between them
# Shot clock below this many seconds sets the ``shot_clock_low`` flag.
SHOT_CLOCK_LOW = 4.0
