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
        self._cached_encoder = None

    def is_available(self) -> bool:
        return shutil.which(self.ffmpeg_bin) is not None or Path(self.ffmpeg_bin).exists()

    def get_best_encoder(self) -> tuple:
        """
        Detects fastest hardware encoder available (adapted from ViralCutter):
        Priority: Apple Silicon/macOS VideoToolbox > NVIDIA NVENC > AMD AMF > Intel QSV > CPU libx264
        """
        if self._cached_encoder:
            return self._cached_encoder

        try:
            res = subprocess.run([self.ffmpeg_bin, "-hide_banner", "-encoders"], capture_output=True, text=True)
            output = res.stdout
            if "h264_videotoolbox" in output:
                print("[VideoEngine] Hardware acceleration detected: macOS VideoToolbox (h264_videotoolbox)")
                self._cached_encoder = ("h264_videotoolbox", ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p"])
                return self._cached_encoder
            if "h264_nvenc" in output:
                print("[VideoEngine] Hardware acceleration detected: NVIDIA NVENC (h264_nvenc)")
                self._cached_encoder = ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22", "-pix_fmt", "yuv420p"])
                return self._cached_encoder
            if "h264_amf" in output:
                print("[VideoEngine] Hardware acceleration detected: AMD AMF (h264_amf)")
                self._cached_encoder = ("h264_amf", ["-c:v", "h264_amf", "-quality", "speed", "-pix_fmt", "yuv420p"])
                return self._cached_encoder
            if "h264_qsv" in output:
                print("[VideoEngine] Hardware acceleration detected: Intel QSV (h264_qsv)")
                self._cached_encoder = ("h264_qsv", ["-c:v", "h264_qsv", "-preset", "veryfast", "-pix_fmt", "yuv420p"])
                return self._cached_encoder
        except Exception as e:
            print(f"[VideoEngine] Error checking hardware encoders: {e}")

        print("[VideoEngine] Using CPU encoder: libx264")
        self._cached_encoder = ("libx264", ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p"])
        return self._cached_encoder

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

        if not input_video_path.exists():
            raise FileNotFoundError(f"Source video file not found: {input_video_path}")

        # Quick validation of input video
        ffprobe_bin = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
        try:
            probe_cmd = [
                ffprobe_bin, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "csv=p=0",
                str(input_video_path)
            ]
            probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
            if probe_res.returncode != 0 or not probe_res.stdout.strip():
                raise RuntimeError(f"Input video file '{input_video_path.name}' contains no readable video streams or is corrupted.")
        except subprocess.TimeoutExpired:
            pass

        encoder_name, encoder_flags = self.get_best_encoder()

        def build_cmd(enc_flags, fast_seek=True):
            if fast_seek:
                return [
                    self.ffmpeg_bin,
                    "-y",                          # Overwrite output without asking
                    "-ss", f"{start_seconds:.3f}", # Fast seek
                    "-t", f"{duration:.3f}",       # Duration
                    "-i", str(input_video_path),
                    "-filter_complex", filter_complex,
                    "-map", "[v]",
                    "-map", "0:a:0?",              # Map first audio stream if present
                    *enc_flags,
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-ar", "48000",
                    "-movflags", "+faststart",     # Optimizes for YouTube stream start
                    str(output_mp4_path)
                ]
            else:
                return [
                    self.ffmpeg_bin,
                    "-y",
                    "-i", str(input_video_path),
                    "-ss", f"{start_seconds:.3f}", # Accurate seek after demux
                    "-t", f"{duration:.3f}",
                    "-filter_complex", filter_complex,
                    "-map", "[v]",
                    "-map", "0:a:0?",
                    *enc_flags,
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-ar", "48000",
                    "-movflags", "+faststart",
                    str(output_mp4_path)
                ]

        # Attempt 1: Fast seek with best encoder
        cmd = build_cmd(encoder_flags, fast_seek=True)
        print(f"[VideoEngine] Executing ({layout_mode}, {encoder_name}, fast_seek): {' '.join(cmd[:12])} ... -> {output_mp4_path.name}")
        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Attempt 2: If seek failed or stream mismatch, fallback to decode seek
        if process.returncode != 0 and ("could not seek" in process.stderr or "matches no streams" in process.stderr):
            print(f"[VideoEngine] Fast seek failed. Falling back to accurate decode seek...")
            cmd_seek = build_cmd(encoder_flags, fast_seek=False)
            process = subprocess.run(cmd_seek, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Attempt 3: If hardware encoder failed, fallback to CPU libx264
        if process.returncode != 0 and encoder_name != "libx264":
            print(f"[VideoEngine] Hardware encoder {encoder_name} failed. Falling back to CPU libx264...")
            fallback_flags = ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p"]
            cmd_fallback = build_cmd(fallback_flags, fast_seek=True)
            process = subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            if process.returncode != 0 and ("could not seek" in process.stderr or "matches no streams" in process.stderr):
                print(f"[VideoEngine] libx264 fast seek failed. Retrying with accurate decode seek...")
                cmd_fallback_seek = build_cmd(fallback_flags, fast_seek=False)
                process = subprocess.run(cmd_fallback_seek, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg render failed:\n{process.stderr[-1000:]}")

        return output_mp4_path
