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

        # Extract exact video ID
        vid_match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
        video_id = vid_match.group(1) if vid_match else "unknown"

        # Check if already downloaded for this EXACT video
        candidates = list(output_dir.glob(f"captions_{video_id}*.json3"))
        if not candidates:
            candidates = list(output_dir.glob(f"captions_{video_id}*.vtt"))

        if not candidates:
            sub_template = str(output_dir / f"captions_{video_id}.%(ext)s")
            
            # Prioritize en-orig first: YouTube rarely rate-limits or 429s the original track
            lang_attempts = ["en-orig", "en", "en-US", "en.*"]
            downloaded = False
            
            for lang in lang_attempts:
                cmd = [
                    self.ytdlp_bin,
                    "--write-auto-sub",
                    "--write-sub",
                    "--sub-lang", lang,
                    "--sub-format", "json3",
                    "--skip-download",
                    "-o", sub_template,
                    url
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                candidates = list(output_dir.glob(f"captions_{video_id}*.json3"))
                if candidates:
                    downloaded = True
                    break

            # If json3 failed on all langs, try VTT format
            if not downloaded:
                for lang in lang_attempts:
                    cmd_vtt = [
                        self.ytdlp_bin,
                        "--write-auto-sub",
                        "--write-sub",
                        "--sub-lang", lang,
                        "--skip-download",
                        "-o", sub_template,
                        url
                    ]
                    res = subprocess.run(cmd_vtt, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    candidates = list(output_dir.glob(f"captions_{video_id}*.vtt"))
                    if candidates:
                        downloaded = True
                        break

        if not candidates:
            return None

        # Parse json3 if available
        json3_files = [f for f in candidates if f.name.endswith(".json3")]
        if json3_files:
            caption_file = json3_files[0]
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

                if len(words) > 10:
                    return words
            except Exception as e:
                print(f"[MediaExtractor] JSON3 caption parse error: {e}")

        # Fallback parse VTT if available
        vtt_files = [f for f in candidates if f.name.endswith(".vtt")]
        if vtt_files:
            caption_file = vtt_files[0]
            try:
                vtt_text = caption_file.read_text(encoding="utf-8", errors="replace")
                words: List[WordTimestamp] = []
                def parse_time(ts):
                    parts = ts.strip().split(':')
                    if len(parts) == 3:
                        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                    elif len(parts) == 2:
                        return float(parts[0]) * 60 + float(parts[1])
                    return 0.0

                pattern = re.compile(r'(\d+:\d+:\d+\.\d+|\d+:\d+\.\d+)\s*-->\s*(\d+:\d+:\d+\.\d+|\d+:\d+\.\d+)(?:[^\n]*)\n([\s\S]*?)(?=\n\n|\Z)')
                seen_texts = set()

                for match in pattern.finditer(vtt_text):
                    start_t = parse_time(match.group(1))
                    end_t = parse_time(match.group(2))
                    raw_content = match.group(3).strip()
                    lines = [l.strip() for l in raw_content.split('\n') if l.strip() and not l.strip().startswith('align:')]
                    if not lines:
                        continue
                    last_line = lines[-1]
                    if '<' in last_line and '>' in last_line:
                        tokens = re.split(r'(<\d+:\d+:\d+\.\d+>|<\d+:\d+\.\d+>)', last_line)
                        curr_time = start_t
                        for token in tokens:
                            token = token.strip()
                            if not token:
                                continue
                            time_match = re.match(r'<(\d+:\d+:\d+\.\d+|\d+:\d+\.\d+)>', token)
                            if time_match:
                                curr_time = parse_time(time_match.group(1))
                            else:
                                clean = re.sub(r'<[^>]+>', '', token).strip()
                                for w in clean.split():
                                    w_clean = re.sub(r'\[.*?\]', '', w).strip()
                                    if w_clean and (w_clean, round(curr_time, 2)) not in seen_texts:
                                        seen_texts.add((w_clean, round(curr_time, 2)))
                                        words.append(WordTimestamp(word=w_clean, start=round(curr_time, 2), end=round(curr_time + 0.35, 2)))
                    else:
                        clean = re.sub(r'<[^>]+>', '', last_line).strip()
                        if clean and clean not in seen_texts:
                            seen_texts.add(clean)
                            tokens = clean.split()
                            if tokens:
                                dur = max(0.5, end_t - start_t) / len(tokens)
                                for i, w in enumerate(tokens):
                                    w_clean = re.sub(r'\[.*?\]', '', w).strip()
                                    if w_clean:
                                        words.append(WordTimestamp(word=w_clean, start=round(start_t + i * dur, 2), end=round(start_t + (i + 1) * dur, 2)))

                if len(words) > 10:
                    return words
            except Exception as e:
                print(f"[MediaExtractor] VTT caption parse error: {e}")

        return None

    def is_valid_media_file(self, path: Path) -> bool:
        """Verifies if a media file has readable video streams and valid duration using ffprobe."""
        if not path.exists() or path.stat().st_size < 100 * 1024:
            return False
        ffprobe_bin = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
        try:
            cmd = [
                ffprobe_bin,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name:format=duration",
                "-of", "json",
                str(path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            if res.returncode != 0:
                return False
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            dur_str = data.get("format", {}).get("duration", "0")
            dur = float(dur_str) if dur_str and dur_str != "N/A" else 0.0
            return len(streams) > 0 and dur > 0.5
        except Exception:
            return False

    def download_youtube_video(self, url: str, output_dir: Path) -> Path:
        """Downloads standard 1080p MP4 with multiplexed audio and video."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Check if already cached and valid in output_dir
        match = re.search(r"[?&]v=([^&#]+)", url) or re.search(r"youtu\.be/([^?&#]+)", url)
        vid = match.group(1) if match else None
        if vid:
            cached_mp4 = output_dir / f"{vid}.mp4"
            if cached_mp4.exists():
                if self.is_valid_media_file(cached_mp4):
                    print(f"[MediaExtractor] Reusing validated cached video: {cached_mp4.name}")
                    return cached_mp4
                else:
                    print(f"[MediaExtractor] Cached file {cached_mp4.name} is incomplete or corrupt. Cleaning up...")
                    for dangling in output_dir.glob(f"{vid}*"):
                        try:
                            dangling.unlink()
                        except Exception:
                            pass

        template = str(output_dir / "%(id)s.%(ext)s")

        def run_ytdlp(extra_args=None):
            cmd = [
                self.ytdlp_bin,
                "--ffmpeg-location", self.ffmpeg_bin,
                "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
                "--merge-output-format", "mp4",
                "--retries", "5",
                "--fragment-retries", "5",
                "--no-playlist",
                "-o", template,
            ]
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(url)
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        print(f"[MediaExtractor] Downloading YouTube: {url}")
        res = run_ytdlp()

        # Fallback 1: YouTube SABR/client bypass (e.g. android/web client)
        if res.returncode != 0:
            print(f"[MediaExtractor] Direct download hit resistance. Attempting android/web client fallback...")
            res = run_ytdlp(["--extractor-args", "youtube:player_client=android,web"])

        # Fallback 2: Browser cookies (ViralCutter pattern)
        if res.returncode != 0:
            print(f"[MediaExtractor] Client fallback hit resistance. Attempting browser cookie fallback...")
            browsers = ["arc", "brave", "safari", "chrome", "firefox", "edge"]
            for browser in browsers:
                try:
                    res_browser = run_ytdlp(["--cookies-from-browser", browser])
                    if res_browser.returncode == 0:
                        print(f"[MediaExtractor] Download succeeded using cookies from {browser}!")
                        res = res_browser
                        break
                except Exception:
                    continue

        if res.returncode != 0:
            raise RuntimeError(f"yt-dlp download failed: {res.stderr}")

        downloaded_files = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not downloaded_files:
            raise FileNotFoundError("Downloaded video file not found in output directory.")

        target_file = downloaded_files[0]
        if not self.is_valid_media_file(target_file):
            # Clean up the invalid file so it doesn't poison future renders
            try:
                target_file.unlink()
            except Exception:
                pass
            raise RuntimeError(f"Downloaded video file {target_file.name} is corrupt or unreadable by FFmpeg.")

        return target_file

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
