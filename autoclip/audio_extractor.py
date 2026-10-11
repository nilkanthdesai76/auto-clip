import json
import re
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from autoclip.subtitle_generator import WordTimestamp


class MediaExtractor:
    """
    Handles downloading YouTube video/audio streams via yt-dlp, extracting metadata,
    parsing high-speed word-level captions, and extracting audio via FFmpeg.
    """

    def __init__(self, ytdlp_bin: Optional[str] = None, ffmpeg_bin: Optional[str] = None):
        self.ytdlp_bin = ytdlp_bin or shutil.which("yt-dlp") or "/opt/homebrew/bin/yt-dlp"
        if Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg").exists():
            self.ffmpeg_bin = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
        else:
            self.ffmpeg_bin = ffmpeg_bin or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

    def get_video_metadata(self, url: str) -> Dict[str, Any]:
        """Fetches metadata, category tags, and duration for a YouTube URL using yt-dlp."""
        cmd = [
            self.ytdlp_bin,
            "--dump-json",
            "--no-playlist",
            url
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to fetch YouTube metadata: {res.stderr[:300]}")

        raw = json.loads(res.stdout)
        return {
            "id": raw.get("id", ""),
            "title": raw.get("title", ""),
            "channel": raw.get("channel", "") or raw.get("uploader", ""),
            "description": raw.get("description", ""),
            "duration": raw.get("duration", 0),
            "thumbnail": raw.get("thumbnail", ""),
            "tags": raw.get("tags", []),
            "categories": raw.get("categories", []),
            "view_count": raw.get("view_count", 0),
            "url": url
        }

    def fetch_youtube_captions(self, url: str, output_dir: Path) -> Optional[List[WordTimestamp]]:
        """
        Attempts to download YouTube's automatic or manual subtitle stream in json3 format.
        Parses exact word timestamps in milliseconds within <1 second.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        sub_template = str(output_dir / "captions_%(id)s.%(ext)s")

        cmd = [
            self.ytdlp_bin,
            "--write-auto-sub",
            "--write-sub",
            "--sub-lang", "en",
            "--sub-format", "json3",
            "--skip-download",
            "-o", sub_template,
            url
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            return None

        # Look for downloaded .json3 file
        candidates = list(output_dir.glob("captions_*.json3"))
        if not candidates:
            return None

        caption_file = candidates[-1]
        try:
            data = json.loads(caption_file.read_text(encoding="utf-8"))
            words: List[WordTimestamp] = []
            for ev in data.get("events", []):
                t_start = ev.get("tStartMs", 0) / 1000.0
                segs = ev.get("segs", [])
                for i, seg in enumerate(segs):
                    text = seg.get("utf8", "").strip()
                    if not text or text == "\n" or text == ">>":
                        continue
                    # Remove bracketed noises like [Applause], [Music]
                    clean_text = re.sub(r"\[.*?\]", "", text).strip()
                    if not clean_text:
                        continue

                    offset = seg.get("tOffsetMs", 0) / 1000.0
                    w_start = t_start + offset
                    if i + 1 < len(segs) and "tOffsetMs" in segs[i + 1]:
                        w_end = t_start + (segs[i + 1]["tOffsetMs"] / 1000.0)
                    else:
                        w_end = w_start + 0.35
                    words.append(WordTimestamp(word=clean_text, start=round(w_start, 2), end=round(max(w_start + 0.1, w_end), 2)))

            return words if len(words) > 10 else None
        except Exception as e:
            print(f"[MediaExtractor] Caption parse error: {e}")
            return None

    def download_youtube_video(self, url: str, output_dir: Path) -> Path:
        """Downloads standard 1080p MP4 with multiplexed audio and video."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Check if already cached in output_dir
        # Extract video id if possible
        match = re.search(r"[?&]v=([^&#]+)", url) or re.search(r"youtu\.be/([^?&#]+)", url)
        if match:
            vid = match.group(1)
            cached_mp4 = output_dir / f"{vid}.mp4"
            if cached_mp4.exists() and cached_mp4.stat().st_size > 1024 * 1024:
                print(f"[MediaExtractor] Reusing cached video: {cached_mp4.name}")
                return cached_mp4

        template = str(output_dir / "%(id)s.%(ext)s")

        cmd = [
            self.ytdlp_bin,
            "--ffmpeg-location", self.ffmpeg_bin,
            "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", template,
            url
        ]

        print(f"[MediaExtractor] Downloading YouTube: {url}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"yt-dlp download failed: {res.stderr}")

        downloaded_files = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not downloaded_files:
            raise FileNotFoundError("Downloaded video file not found in output directory.")

        return downloaded_files[0]

    def extract_audio(self, video_path: Path, output_wav_path: Path) -> Path:
        """Extracts mono 16kHz WAV audio optimized for speech models."""
        output_wav_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(output_wav_path)
        ]

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Audio extraction failed: {res.stderr}")

        return output_wav_path
