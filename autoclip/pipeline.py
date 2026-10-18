import json
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from autoclip.config import CHANNEL_PROFILES, ChannelProfile, OUTPUT_DIR, TEMP_DIR
from autoclip.classifier import classify_video_metadata
from autoclip.audio_extractor import MediaExtractor
from autoclip.transcriber import AudioTranscriber
from autoclip.hook_detector import HookDetector, DetectedClip
from autoclip.subtitle_generator import group_words_into_short_phrases, build_ass_subtitle_file
from autoclip.video_engine import VideoEngine


class AutoClipPipeline:
    """
    End-to-end pipeline for generating niche-optimized YouTube Shorts with animated subtitles,
    complete with auto category detection, high-speed caption extraction, and dual-canvas rendering.
    """

    def __init__(self, profile_id: Optional[str] = None):
        self.profile_id = profile_id or "f1"
        self.profile: ChannelProfile = CHANNEL_PROFILES.get(self.profile_id, CHANNEL_PROFILES["f1"])
        self.extractor = MediaExtractor()
        self.transcriber = AudioTranscriber()
        self.detector = HookDetector(self.profile)
        self.video_engine = VideoEngine()

    def set_profile(self, profile_id: str):
        if profile_id in CHANNEL_PROFILES:
            self.profile_id = profile_id
            self.profile = CHANNEL_PROFILES[profile_id]
            self.detector = HookDetector(self.profile)

    def inspect_and_classify(self, video_input: str) -> Dict[str, Any]:
        """
        Quickly extracts metadata and automatically detects the category and niche.
        """
        if video_input.startswith("http://") or video_input.startswith("https://"):
            metadata = self.extractor.get_video_metadata(video_input)
            niche, confidence, reasoning = classify_video_metadata(metadata)
            return {
                "metadata": metadata,
                "detected_niche": niche,
                "confidence": confidence,
                "reasoning": reasoning,
                "profile": CHANNEL_PROFILES.get(niche, CHANNEL_PROFILES["f1"])
            }
        else:
            path = Path(video_input)
            mock_meta = {"title": path.stem, "channel": "Local Media", "tags": [], "categories": []}
            niche, conf, r = classify_video_metadata(mock_meta)
            return {
                "metadata": mock_meta,
                "detected_niche": niche,
                "confidence": conf,
                "reasoning": r,
                "profile": CHANNEL_PROFILES.get(niche, CHANNEL_PROFILES["f1"])
            }

    def process_video(
        self,
        video_input: str,  # YouTube URL or local filepath
        max_clips: int = 4,
        auto_detect: bool = True,
        api_key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Metadata & Auto-Classification
        metadata = None
        if video_input.startswith("http://") or video_input.startswith("https://"):
            print(f"[AutoClip] Inspecting YouTube URL...")
            try:
                metadata = self.extractor.get_video_metadata(video_input)
                if auto_detect:
                    detected_niche, confidence, reasoning = classify_video_metadata(metadata)
                    print(f"[AutoClip] Auto-detected category: {detected_niche.upper()} ({confidence}% confidence)")
                    print(f"          Reason: {reasoning}")
                    self.set_profile(detected_niche)
            except Exception as e:
                print(f"[AutoClip] Metadata inspection warning: {e}")

        channel_output_dir = OUTPUT_DIR / self.profile.niche
        channel_output_dir.mkdir(parents=True, exist_ok=True)

        # 2. Extract word-level timestamps (Try fast captions first)
        words = None
        if video_input.startswith("http://") or video_input.startswith("https://"):
            print(f"[{self.profile.name}] Attempting instant caption extraction from YouTube...")
            words = self.extractor.fetch_youtube_captions(video_input, TEMP_DIR)
            if words:
                print(f"[{self.profile.name}] Instantly extracted {len(words)} timestamped words from YouTube captions!")

        # 3. Resolve source video file
        if video_input.startswith("http://") or video_input.startswith("https://"):
            print(f"[{self.profile.name}] Downloading/resolving full YouTube video...")
            video_path = self.extractor.download_youtube_video(video_input, TEMP_DIR / "downloads")
        else:
            video_path = Path(video_input)
            if not video_path.exists():
                raise FileNotFoundError(f"Source video file not found: {video_path}")

        # 4. Fallback transcription if fast captions were not available
        if not words:
            audio_path = TEMP_DIR / f"{video_path.stem}.wav"
            if not audio_path.exists():
                print(f"[{self.profile.name}] Extracting audio stream for speech recognition...")
                self.extractor.extract_audio(video_path, audio_path)
            print(f"[{self.profile.name}] Transcribing words with timestamps...")
            words = self.transcriber.transcribe(audio_path)

        # 5. Detect top viral clips (Guaranteed at least 4 clips)
        print(f"[{self.profile.name}] Detecting top hooks for {self.profile.niche} audience...")
        clips: List[DetectedClip] = self.detector.detect_clips(words, api_key=api_key, max_clips=max_clips, min_clips=4)

        results = []

        # 6. Render each clip into a 9:16 vertical short
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

            # Render 9:16 vertical short with audio & video
            rendered_path = self.video_engine.render_short(
                input_video_path=video_path,
                start_seconds=clip.start_seconds,
                duration=clip.duration,
                subtitle_ass_path=sub_path,
                output_mp4_path=out_mp4,
                profile=self.profile,
                layout_mode=self.profile.layout_mode
            )

            # Save YouTube metadata JSON
            metadata_file = channel_output_dir / f"{clip.id}_{self.profile.niche}_metadata.json"
            meta_dict = {
                "clip_id": clip.id,
                "channel_profile": self.profile.id,
                "channel_handle": self.profile.handle,
                "video_file": str(rendered_path),
                "youtube_title": clip.suggested_title,
                "virality_score": clip.virality_score,
                "hook": clip.hook,
                "duration_seconds": round(clip.duration, 1),
                "hashtags": clip.hashtags,
                "description": f"{clip.hook}\n\n{' '.join(clip.hashtags)}"
            }
            metadata_file.write_text(json.dumps(meta_dict, indent=2), encoding="utf-8")

            results.append(meta_dict)

        print(f"\n[AutoClip] Batch complete! {len(results)} shorts generated in {channel_output_dir}")
        return results
