"""FFprobe wrapper: reads real metadata. Never uses a shell."""
import json
import subprocess


class ProbeError(Exception):
    pass


def probe_video(path, ffprobe_bin="ffprobe"):
    """Return dict(duration_seconds, has_audio, has_video, width, height, format)."""
    cmd = [
        ffprobe_bin, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError as exc:
        raise ProbeError("FFprobe is not installed on the server.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("Probing the file timed out.") from exc
    if result.returncode != 0:
        raise ProbeError("This file could not be read as a video.")
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProbeError("Could not parse video metadata.") from exc

    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams:
        raise ProbeError("No video stream found in this file.")

    duration = None
    fmt = data.get("format", {})
    if fmt.get("duration"):
        try:
            duration = float(fmt["duration"])
        except (TypeError, ValueError):
            duration = None
    if duration is None:
        for s in video_streams:
            if s.get("duration"):
                duration = float(s["duration"])
                break
    if not duration or duration <= 0:
        raise ProbeError("Could not determine the video duration.")

    v = video_streams[0]
    return {
        "duration": duration,
        "has_audio": len(audio_streams) > 0,
        "has_video": True,
        "width": v.get("width"),
        "height": v.get("height"),
        "format": fmt.get("format_name"),
    }
