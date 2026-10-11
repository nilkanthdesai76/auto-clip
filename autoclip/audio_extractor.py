import subprocess
import shutil
from pathlib import Path
from typing import Optional


class MediaExtractor:
    """
    Handles downloading YouTube video/audio streams via yt-dlp and extracting audio via FFmpeg.
    """

    def __init__(self, ytdlp_bin: Optional[str] = None, ffmpeg_bin: Optional[str] = None):
        self.ytdlp_bin = ytdlp_bin or shutil.which("yt-dlp") or "/opt/homebrew/bin/yt-dlp"
        self.ffmpeg_bin = ffmpeg_bin or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

    def download_youtube_video(self, url: str, output_dir: Path) -> Path:
        """Downloads standard 1080p video from YouTube."""
        output_dir.mkdir(parents=True, exist_ok=True)
        template = str(output_dir / "%(id)s.%(ext)s")

        cmd = [
            self.ytdlp_bin,
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", template,
            url
        ]

        print(f"[MediaExtractor] Downloading YouTube: {url}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"yt-dlp download failed: {res.stderr}")

        # Find the downloaded file
        downloaded_files = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not downloaded_files:
            raise FileNotFoundError("Downloaded video file not found in output directory.")

        return downloaded_files[0]

    def extract_audio(self, video_path: Path, output_wav_path: Path) -> Path:
        """Extracts mono 16kHz WAV audio optimized for Whisper speech-to-text models."""
        output_wav_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", str(video_path),
            "-vn",              # Disable video
            "-acodec", "pcm_s16le",
            "-ar", "16000",     # 16kHz sample rate standard for Whisper
            "-ac", "1",         # Mono audio
            str(output_wav_path)
        ]

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Audio extraction failed: {res.stderr}")

        return output_wav_path
