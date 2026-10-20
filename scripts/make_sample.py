"""Generate a small sample video for local testing (no download needed).

Usage:  python scripts/make_sample.py [seconds] [output.mp4]
Creates a test-pattern video WITH audio tone, using FFmpeg lavfi sources.
Equivalent raw command:
  ffmpeg -f lavfi -i testsrc=duration=65:size=640x360:rate=15 \
         -f lavfi -i sine=frequency=440:duration=65 \
         -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest sample_65s.mp4
"""
import subprocess
import sys

seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 65
out = sys.argv[2] if len(sys.argv) > 2 else f"sample_{seconds}s.mp4"
cmd = [
    "ffmpeg", "-y",
    "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=640x360:rate=15",
    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out,
]
print("Running:", " ".join(cmd))
subprocess.run(cmd, check=True)
print("Created", out)
