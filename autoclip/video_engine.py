import subprocess
import shutil
import sys
from pathlib import Path
from typing import Optional
from autoclip.config import ChannelProfile


class VideoEngine:
    """
    Renders 9:16 vertical YouTube Shorts with burned animated subtitles using FFmpeg.
    Supports multiple portrait layout modes:
    - crop_fill: 100% full-bleed edge-to-edge vertical portrait (no letterboxing)
    - split_screen: Top close-up crop + bottom wide context
    - fit_blur: Centered 16:9 with ambient blurred background
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
        profile: ChannelProfile,
        layout_mode: str = "crop_fill"
    ) -> Path:
        """
        Extracts segment, formats into 1080x1920 vertical canvas, and burns animated ASS subtitles.
        """
        output_mp4_path.parent.mkdir(parents=True, exist_ok=True)

        # Escape path for FFmpeg subtitles filter
        escaped_sub_path = str(subtitle_ass_path.resolve()).replace("\\", "/").replace(":", "\\:")

        # Layout filter graph selection
        if layout_mode == "crop_fill":
            # 100% Edge-to-edge portrait fill: scale to fill 1080x1920, center crop, burn subtitles
            filter_complex = (
                f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2[base];"
                f"[base]subtitles='{escaped_sub_path}'[v]"
            )
        elif layout_mode == "split_screen":
            # Split screen: Top 1080x960 zoomed crop + Bottom 1080x960 full context
            filter_complex = (
                f"[0:v]split=2[top_src][bot_src];"
                f"[top_src]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960:(in_w-1080)/2:(in_h-960)/2[top];"
                f"[bot_src]scale=1080:960:force_original_aspect_ratio=decrease,pad=1080:960:(ow-iw)/2:(oh-ih)/2:black[bot];"
                f"[top][bot]vstack=inputs=2[stacked];"
                f"[stacked]subtitles='{escaped_sub_path}'[v]"
            )
        else:
            # fit_blur: Blurred ambient background + sharp centered 16:9
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
            "-map", "0:a:0?",              # Map first audio stream
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

        print(f"[VideoEngine] Executing ({layout_mode}): {' '.join(cmd[:10])} ... -> {output_mp4_path.name}")
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg render failed:\n{process.stderr[-1000:]}")

        return output_mp4_path
