import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from autoclip.config import CHANNEL_PROFILES, ChannelProfile, OUTPUT_DIR, TEMP_DIR
from autoclip.audio_extractor import MediaExtractor
from autoclip.transcriber import AudioTranscriber
from autoclip.hook_detector import HookDetector, DetectedClip
from autoclip.subtitle_generator import group_words_into_short_phrases, build_ass_subtitle_file
from autoclip.video_engine import VideoEngine


class AutoClipPipeline:
    """
    End-to-end pipeline for generating niche-optimized YouTube Shorts with animated subtitles.
    """

    def __init__(self, profile_id: str = "f1"):
        if profile_id not in CHANNEL_PROFILES:
            raise ValueError(f"Unknown profile '{profile_id}'. Available: {list(CHANNEL_PROFILES.keys())}")
        self.profile: ChannelProfile = CHANNEL_PROFILES[profile_id]
        self.extractor = MediaExtractor()
        self.transcriber = AudioTranscriber()
        self.detector = HookDetector(self.profile)
        self.video_engine = VideoEngine()

    def process_video(
        self,
        video_input: str,  # YouTube URL or local filepath
        max_clips: int = 3,
        api_key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        channel_output_dir = OUTPUT_DIR / self.profile.niche
        channel_output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Resolve source video file
        if video_input.startswith("http://") or video_input.startswith("https://"):
            print(f"[{self.profile.name}] Downloading YouTube video...")
            video_path = self.extractor.download_youtube_video(video_input, TEMP_DIR / "downloads")
        else:
            video_path = Path(video_input)
            if not video_path.exists():
                raise FileNotFoundError(f"Source video file not found: {video_path}")

        # 2. Extract audio
        audio_path = TEMP_DIR / f"{video_path.stem}.wav"
        if not audio_path.exists():
            print(f"[{self.profile.name}] Extracting audio stream...")
            self.extractor.extract_audio(video_path, audio_path)

        # 3. Transcribe word-level timestamps
        print(f"[{self.profile.name}] Transcribing words with timestamps...")
        words = self.transcriber.transcribe(audio_path)

        # 4. Detect top clips
        print(f"[{self.profile.name}] Detecting top hooks for {self.profile.niche} audience...")
        clips: List[DetectedClip] = self.detector.detect_clips(words, api_key=api_key, max_clips=max_clips)

        results = []

        # 5. Render each clip into a 9:16 vertical short
        for clip in clips:
            print(f"\n--- Processing {clip.id}: '{clip.title}' (Virality Score: {clip.virality_score}/100) ---")
            sub_path = TEMP_DIR / f"{clip.id}_subtitles.ass"
            out_mp4 = channel_output_dir / f"{clip.id}_{self.profile.niche}.mp4"

            # Generate subtitle phrases and .ass file
            phrases = group_words_into_short_phrases(clip.words)
            # Rebase timestamps relative to clip start
            rebased_phrases = []
            for p in phrases:
                rebased_words = [
                    w.__class__(
                        word=w.word,
                        start=max(0.0, w.start - clip.start_seconds),
                        end=max(0.0, w.end - clip.start_seconds)
                    )
                    for w in p.words
                ]
                rebased_phrases.append(
                    p.__class__(
                        words=rebased_words,
                        start=max(0.0, p.start - clip.start_seconds),
                        end=max(0.0, p.end - clip.start_seconds)
                    )
                )

            build_ass_subtitle_file(rebased_phrases, sub_path, self.profile)

            # Render 9:16 vertical short
            rendered_path = self.video_engine.render_short(
                input_video_path=video_path,
                start_seconds=clip.start_seconds,
                duration=clip.duration,
                subtitle_ass_path=sub_path,
                output_mp4_path=out_mp4,
                profile=self.profile
            )

            # Save YouTube metadata JSON
            metadata = {
                "clip_id": clip.id,
                "channel_profile": self.profile.id,
                "channel_handle": self.profile.handle,
                "video_file": str(rendered_path),
                "youtube_title": clip.suggested_title,
                "virality_score": clip.virality_score,
                "hook": clip.hook,
                "duration_seconds": round(clip.duration, 2),
                "hashtags": clip.hashtags,
                "description": (
                    f"{clip.hook}\n\n"
                    f"Subscribe to {self.profile.handle} for more daily {self.profile.niche.upper()} moments!\n\n"
                    f"{' '.join(clip.hashtags)}"
                )
            }

            meta_path = channel_output_dir / f"{clip.id}_{self.profile.niche}_metadata.json"
            meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

            results.append(metadata)

        print(f"\n[AutoClip] Batch complete! {len(results)} shorts generated in {channel_output_dir}")
        return results
