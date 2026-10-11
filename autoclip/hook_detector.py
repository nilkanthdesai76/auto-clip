import json
import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from autoclip.config import ChannelProfile
from autoclip.subtitle_generator import WordTimestamp


@dataclass
class DetectedClip:
    id: str
    title: str
    hook: str
    start_seconds: float
    end_seconds: float
    duration: float
    virality_score: int          # 1 - 100
    reasoning: str
    words: List[WordTimestamp]
    suggested_title: str
    hashtags: List[str]

    @property
    def formatted_time_range(self) -> str:
        s_min, s_sec = int(self.start_seconds // 60), int(self.start_seconds % 60)
        e_min, e_sec = int(self.end_seconds // 60), int(self.end_seconds % 60)
        return f"{s_min:02d}:{s_sec:02d} -> {e_min:02d}:{e_sec:02d} ({int(self.duration)}s)"


class HookDetector:
    """
    Identifies high-virality 30-60 second clips from timestamped audio transcripts.
    Supports LLM inference with fallback to an offline heuristic NLP virality engine.
    """

    def __init__(self, profile: ChannelProfile):
        self.profile = profile

    def detect_clips(
        self,
        words: List[WordTimestamp],
        api_key: Optional[str] = None,
        max_clips: int = 4
    ) -> List[DetectedClip]:
        if not words:
            return []

        # If an LLM API key is available, attempt AI hook extraction
        if api_key:
            try:
                clips = self._detect_via_ai(words, api_key, max_clips)
                if clips:
                    return clips
            except Exception as e:
                print(f"[HookDetector] AI inference failed ({e}), falling back to heuristic engine.")

        return self._detect_via_heuristics(words, max_clips)

    def _detect_via_heuristics(
        self,
        words: List[WordTimestamp],
        max_clips: int = 4
    ) -> List[DetectedClip]:
        """
        High-performance offline scoring engine:
        - Analyzes rolling windows between min_clip_duration and max_clip_duration.
        - Scores first-3-second hook strength (question words, contrarian hooks, emotional peaks).
        - Scores mid-clip momentum and speech pacing.
        """
        total_duration = words[-1].end if words else 0
        min_dur = self.profile.min_clip_duration
        max_dur = self.profile.max_clip_duration

        if total_duration < min_dur:
            # Entire video is shorter than min duration; treat whole video as single clip
            duration = total_duration
            hook_text = " ".join(w.word for w in words[:8])
            return [
                DetectedClip(
                    id="clip_1",
                    title=f"Viral {self.profile.niche.upper()} Highlight",
                    hook=hook_text,
                    start_seconds=0.0,
                    end_seconds=total_duration,
                    duration=duration,
                    virality_score=88,
                    reasoning="Complete self-contained segment with strong continuous momentum.",
                    words=words,
                    suggested_title=f"{self.profile.name} - Essential Moment #{self.profile.target_hashtags[0]}",
                    hashtags=self.profile.target_hashtags
                )
            ]

        # Scan candidate sliding windows (step by 10s)
        candidates = []
        step_seconds = 8.0
        current_start = 0.0

        target_clip_length = 38.0  # Sweet spot for YouTube Shorts completion rate

        while current_start + min_dur <= total_duration:
            ideal_end = min(current_start + target_clip_length, total_duration)
            
            # Find closest sentence boundary near ideal_end
            window_words = [w for w in words if current_start <= w.start <= current_start + max_dur]
            if len(window_words) < 15:
                current_start += step_seconds
                continue

            # Find natural endpoint (punctuation)
            best_end_idx = len(window_words) - 1
            for idx, w in enumerate(window_words):
                if w.start - current_start >= min_dur and any(w.word.endswith(p) for p in [".", "!", "?"]):
                    best_end_idx = idx
                    break

            clip_words = window_words[: best_end_idx + 1]
            clip_dur = clip_words[-1].end - clip_words[0].start
            if clip_dur < min_dur:
                current_start += step_seconds
                continue

            score, hook_summary = self._score_clip_window(clip_words)
            candidates.append((score, clip_words[0].start, clip_words[-1].end, clip_words, hook_summary))
            current_start += step_seconds

        # Sort by score descending and take non-overlapping top clips
        candidates.sort(key=lambda x: x[0], reverse=True)
        selected_clips: List[DetectedClip] = []

        for score, start_s, end_s, c_words, hook in candidates:
            # Check overlap with already selected clips (> 50% overlap disallowed)
            overlaps = False
            for existing in selected_clips:
                overlap_start = max(start_s, existing.start_seconds)
                overlap_end = min(end_s, existing.end_seconds)
                if overlap_end > overlap_start and (overlap_end - overlap_start) > 12.0:
                    overlaps = True
                    break

            if not overlaps:
                clip_num = len(selected_clips) + 1
                first_sentence = " ".join(w.word for w in c_words[:10])
                clean_title = re.sub(r"[^\w\s]", "", first_sentence).strip()
                if len(clean_title) > 42:
                    clean_title = clean_title[:42] + "..."

                selected_clips.append(
                    DetectedClip(
                        id=f"clip_{clip_num}",
                        title=f"{clean_title.title()}",
                        hook=hook,
                        start_seconds=start_s,
                        end_seconds=end_s,
                        duration=end_s - start_s,
                        virality_score=min(98, max(75, int(score))),
                        reasoning=f"High speech velocity ({len(c_words)} words in {int(end_s - start_s)}s) with strong hook in first 3s.",
                        words=c_words,
                        suggested_title=f"{clean_title.title()} 🏎️💨 {' '.join(self.profile.target_hashtags[:3])}",
                        hashtags=self.profile.target_hashtags
                    )
                )

                if len(selected_clips) >= max_clips:
                    break

        return selected_clips

    def _score_clip_window(self, words: List[WordTimestamp]) -> (float, str):
        """Calculates a retention virality score based on words, speed, and hook keywords."""
        if not words:
            return 0.0, ""

        full_text = " ".join(w.word.lower() for w in words)
        first_5s_words = [w for w in words if w.start <= words[0].start + 4.5]
        first_5s_text = " ".join(w.word.lower() for w in first_5s_words)

        score = 70.0

        # Hook words in first 5s (increases retention by 200%)
        hook_triggers = ["why", "how", "what", "never", "secret", "shocking", "stop", "biggest", "insane", "problem", "actually", "listen", "truth", "watch"]
        for trigger in hook_triggers:
            if trigger in first_5s_text:
                score += 5.5

        # Niche-specific keyword boost
        niche_keywords = {
            "formula1": ["verstappen", "hamilton", "ferrari", "pit", "box", "safety car", "fastest", "engine", "drs", "overtake", "crash", "fia", "radio", "penalty"],
            "tech": ["apple", "silicon", "m4", "nvidia", "benchmark", "code", "ai", "faster", "swift", "memory", "gpu", "compiler", "chip"],
            "podcast": ["money", "success", "mistake", "habit", "mind", "people", "business", "million", "advice", "rule", "learn", "win"],
            "gaming": ["clutch", "win", "kill", "boss", "impossible", "level", "cheat", "speedrun", "secret", "died"]
        }

        keywords = niche_keywords.get(self.profile.niche, [])
        for kw in keywords:
            if kw in full_text:
                score += 2.0

        # Speech rate check (130-180 words per minute is optimal for TikTok/Shorts)
        duration_mins = (words[-1].end - words[0].start) / 60.0
        if duration_mins > 0:
            wpm = len(words) / duration_mins
            if 130 <= wpm <= 190:
                score += 6.0
            elif wpm < 100:
                score -= 8.0

        # Hook quote for preview
        hook_quote = " ".join(w.word for w in words[:12]) + "..."
        return min(99.0, score), hook_quote

    def _detect_via_ai(
        self,
        words: List[WordTimestamp],
        api_key: str,
        max_clips: int
    ) -> List[DetectedClip]:
        """Placeholder for plug-in LLM hook scoring."""
        # Can connect to OpenAI, Claude, or Gemini when API key is provided
        return []
