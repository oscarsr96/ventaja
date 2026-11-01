"""Build the trimmed test fixture for a SkillCorner game.

The tracking file keeps only the frames around the first N shots; everything
else is copied unchanged. Standard library only.
"""

import argparse
import gzip
import json
import shutil
from pathlib import Path


def _windows(shot_frames: list[int], before: int, after: int) -> list[tuple[int, int]]:
    return [(f - before, f + after) for f in sorted(shot_frames)]


def main(
    source_data_dir: Path,
    out_dir: Path,
    game_id: int = 114243,
    n_shots: int = 20,
    before: int = 75,
    after: int = 25,
) -> None:
    """Write the trimmed data_dir for `game_id` into `out_dir`."""
    rel = Path("matches") / str(game_id)
    src_game = source_data_dir / rel
    out_game = out_dir / rel
    out_game.mkdir(parents=True, exist_ok=True)

    events_name = f"{game_id}_dynamic_events.json"
    events = json.loads((src_game / events_name).read_text())
    frames = sorted(int(s["startFrame"]) for s in events["shots"])[:n_shots]
    windows = _windows(frames, before, after)

    shutil.copyfile(src_game / events_name, out_game / events_name)
    game_name = f"{game_id}_game_data.json"
    shutil.copyfile(src_game / game_name, out_game / game_name)
    shutil.copyfile(source_data_dir / "player_id_aliases.csv", out_dir / "player_id_aliases.csv")

    matches = json.loads((source_data_dir / "matches.json").read_text())
    kept = [m for m in matches if m.get("id") == game_id]
    (out_dir / "matches.json").write_text(json.dumps(kept))

    tracking_name = f"{game_id}_tracking_data.jsonl.gz"
    with (
        gzip.open(src_game / tracking_name, "rt") as src,
        gzip.open(out_game / tracking_name, "wt") as dst,
    ):
        for line in src:
            idx = json.loads(line)["frameIdx"]
            if any(lo <= idx <= hi for lo, hi in windows):
                dst.write(line if line.endswith("\n") else line + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--game", type=int, default=114243)
    parser.add_argument("--n-shots", type=int, default=20)
    parser.add_argument("--before", type=int, default=75)
    parser.add_argument("--after", type=int, default=25)
    a = parser.parse_args()
    main(a.source_dir, a.out_dir, a.game, a.n_shots, a.before, a.after)
