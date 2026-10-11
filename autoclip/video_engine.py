import subprocess
import shutil
import sys
from pathlib import Path
from typing import Optional
from autoclip.config import ChannelProfile


class VideoEngine:
    """
    Renders 9:16 vertical YouTube Shorts with burned animated subtitles using FFmpeg.
    """

    def __init__(self, ffmpeg_bin: Optional[str] = None):
        if ffmpeg_bin:
            self.ffmpeg_bin = ffmpeg_bin
        elif Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg").exists():
            self.ffmpeg_bin = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
        else:
            self.ffmpeg_bin = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

    def is_available(self) -> bool:
        return shutil.which(self.ffmpeg_bin) is not None or Path(self.ffmpeg_bin).exists()

    def render_short(
        self,
        input_video_path: Path,
        start_seconds: float,
        duration: float,
        subtitle_ass_path: Path,
        output_mp4_path: Path,
        profile: ChannelProfile
    ) -> Path:
        """
        Extracts segment, formats into 1080x1920 vertical canvas, and burns animated ASS subtitles.
        """
        output_mp4_path.parent.mkdir(parents=True, exist_ok=True)

        # Escape path for FFmpeg subtitles filter
        # In FFmpeg filter syntax, colons and backslashes must be escaped
        escaped_sub_path = str(subtitle_ass_path.resolve()).replace("\\", "/").replace(":", "\\:")

        # Layout filter:
        # Background: Scale to 1080x1920, crop, heavy boxblur, slight dim
        # Foreground: Scale to 1080 width preserving aspect ratio, centered vertically
        # Subtitles: Rendered on top of composited result
        filter_complex = (
            f"[0:v]split=2[bg_src][fg_src];"
            f"[bg_src]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"boxblur=25:5,eq=brightness=-0.12[bg];"
            f"[fg_src]scale=1080:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[comp];"
            f"[comp]subtitles='{escaped_sub_path}'[v]"
        )

        cmd = [
            self.ffmpeg_bin,
            "-y",                          # Overwrite output without asking
            "-ss", f"{start_seconds:.3f}", # Fast seek
            "-t", f"{duration:.3f}",       # Duration
            "-i", str(input_video_path),
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "0:a?",                # Map audio if present
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-movflags", "+faststart",     # Optimizes for YouTube stream start
            str(output_mp4_path)
        ]

        print(f"[VideoEngine] Executing: {' '.join(cmd[:10])} ... -> {output_mp4_path.name}")
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg render failed:\n{process.stderr[-1000:]}")

        return output_mp4_path
