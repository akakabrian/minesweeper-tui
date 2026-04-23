"""Sound diagnostic for minesweeper-tui.

90% of "I can't hear anything" is the user SSH'd in — audio plays where
the process runs. This script prints the detected player, runs one
synchronous synth playback, and reports the exit code.

    python -m tests.sound_test
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from minesweeper_tui.sounds import SoundBoard, _detect_player, _synth


def main() -> None:
    print("minesweeper-tui — sound diagnostic\n")

    # 1. Player detection.
    player = _detect_player()
    if player is None:
        print("  [FAIL]  no audio player found on PATH")
        print("          install `paplay` (PulseAudio) or `aplay` (ALSA).")
        return
    print(f"  player : {' '.join(player)}  (first of paplay/aplay/afplay on PATH)")

    # 2. Paths to the players (for SSH debugging).
    for p in ("paplay", "aplay", "afplay"):
        w = shutil.which(p)
        print(f"  which {p:<8}= {w or '(not installed)'}")

    # 3. Synth one tone + play it synchronously.
    data = _synth([880, 1320], 0.15, 5, 40)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = Path(f.name)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22_050)
        w.writeframes(data)
    print(f"\n  wrote synth wav to {path} ({path.stat().st_size} bytes)")
    print("  playing one beep, blocking until done...")
    try:
        rc = subprocess.call([*player, str(path)])
        print(f"  exit code: {rc}  {'OK' if rc == 0 else '(non-zero — check audio pipeline)'}")
    finally:
        try:
            path.unlink()
        except OSError:
            pass

    # 4. SoundBoard end-to-end, fire-and-forget.
    print("\n  SoundBoard end-to-end (non-blocking, debounced)...")
    sb = SoundBoard(enabled=True)
    print(f"    enabled={sb.enabled}  player={sb._player}")
    sb.play("reveal")
    sb.play("explosion")
    print("    dispatched 2 sounds (reveal, explosion).")
    # Give them time to play before cleanup.
    import time as _t
    _t.sleep(0.8)
    sb.close()
    print("\n  If you heard two tones, sound is working.")
    print("  If not: SSH? Remote audio? Check `pactl info` / `aplay -l`.")


if __name__ == "__main__":
    main()
