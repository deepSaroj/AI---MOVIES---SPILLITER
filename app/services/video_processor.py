"""FFmpeg splitting engine.

Pure duration maths lives in calculate_clips() so it is unit-testable without
FFmpeg. split_video() runs FFmpeg once per clip (stream copy by default,
optional re-encode) and reports *real* progress: completed clips / total clips.
No shell is ever used; arguments are passed as a list (no command injection).
"""
import os
import subprocess
from pathlib import Path


class SplitError(Exception):
    pass


def calculate_clips(total_duration, clip_duration):
    """Return [(start, end), ...] covering the whole video.

    The final clip holds whatever remains (e.g. 65 min @ 10 min -> last clip 60-65).
    """
    total = float(total_duration)
    step = float(clip_duration)
    if total <= 0:
        raise ValueError("Total duration must be positive.")
    if step <= 0:
        raise ValueError("Clip duration must be positive.")
    clips = []
    start = 0.0
    eps = 0.05  # ignore sub-50ms tails
    while start < total - eps:
        end = min(start + step, total)
        clips.append((round(start, 3), round(end, 3)))
        start = end
    return clips


def format_ts(seconds):
    seconds = int(round(float(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _run_ffmpeg(cmd, timeout=3600):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result


def split_one_clip(src, dst, start, end, output_format="mp4", reencode=False,
                   ffmpeg_bin="ffmpeg"):
    """Cut one clip [start, end) from src into dst. Raises SplitError on failure."""
    duration = max(0.1, float(end) - float(start))
    base = [ffmpeg_bin, "-y", "-ss", f"{float(start):.3f}", "-i", str(src),
            "-t", f"{duration:.3f}"]
    if reencode:
        if output_format == "webm":
            codec = ["-c:v", "libvpx-vp9", "-b:v", "1M", "-c:a", "libopus"]
        else:
            codec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                     "-c:a", "aac", "-movflags", "+faststart"]
    else:
        codec = ["-c", "copy"]
        if output_format == "mp4":
            codec += ["-movflags", "+faststart"]
    cmd = base + codec + [str(dst)]
    try:
        result = _run_ffmpeg(cmd)
    except FileNotFoundError as exc:
        raise SplitError("FFmpeg is not installed on the server.") from exc
    except subprocess.TimeoutExpired as exc:
        raise SplitError("FFmpeg timed out while creating a clip.") from exc
    if result.returncode != 0 or not Path(dst).exists() or Path(dst).stat().st_size == 0:
        tail = (result.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else "unknown FFmpeg error"
        raise SplitError(f"FFmpeg failed: {detail}")
    return Path(dst).stat().st_size


def split_video(src, out_dir, total_duration, clip_duration, prefix="clip",
                output_format="mp4", reencode=False, ffmpeg_bin="ffmpeg",
                progress_cb=None, is_cancelled=None):
    """Split src into clips inside out_dir.

    Returns list of dicts(filename, clip_number, start, end, duration, file_size).
    Stream-copy first; if a copy-mode clip fails and reencode was not requested,
    that clip is retried once with re-encoding before giving up.
    """
    ranges = calculate_clips(total_duration, clip_duration)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_prefix = "".join(c for c in prefix if c.isalnum() or c in "-_").strip() or "clip"
    results = []
    total = len(ranges)
    for idx, (start, end) in enumerate(ranges, start=1):
        if is_cancelled and is_cancelled():
            raise SplitError("cancelled")
        filename = f"{safe_prefix}_{idx:02d}.{output_format}"
        dst = out_dir / filename
        try:
            size = split_one_clip(src, dst, start, end, output_format, reencode, ffmpeg_bin)
        except SplitError:
            if reencode:
                raise
            # One automatic retry with re-encoding (fixes keyframe/codec edge cases)
            size = split_one_clip(src, dst, start, end, output_format, True, ffmpeg_bin)
        results.append({
            "filename": filename, "clip_number": idx, "start_time": start,
            "end_time": end, "duration": round(end - start, 3), "file_size": size,
        })
        if progress_cb:
            progress_cb(int(idx * 100 / total))
    return results


def make_thumbnail(src, dst, ffmpeg_bin="ffmpeg", at_seconds=1.0):
    """Best-effort poster frame; returns True on success."""
    cmd = [ffmpeg_bin, "-y", "-ss", f"{at_seconds}", "-i", str(src),
           "-frames:v", "1", "-q:v", "3", str(dst)]
    try:
        result = _run_ffmpeg(cmd, timeout=60)
        return result.returncode == 0 and Path(dst).exists() and Path(dst).stat().st_size > 0
    except Exception:
        return False
