import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
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
    is_ai_enriched: bool = False

    @property
    def formatted_time_range(self) -> str:
        s_min, s_sec = int(self.start_seconds // 60), int(self.start_seconds % 60)
        e_min, e_sec = int(self.end_seconds // 60), int(self.end_seconds % 60)
        return f"{s_min:02d}:{s_sec:02d} -> {e_min:02d}:{e_sec:02d} ({int(self.duration)}s)"


VIRALCUTTER_SYSTEM_PROMPT = """You are a World-Class Viral Video Editor and Storyteller. You are an expert at finding "gold nuggets" in long transcripts that can stand alone as viral TikToks/Reels/Shorts.

Your goal is to extract segments that have **Perfect Narrative Completeness** (Start, Middle, End) while respecting time constraints.

### STRICT VIRAL RULES (The "ViralCutter Standard"):
1. NO "GARBAGE" STARTS:
   - NEVER start with filler words ("Um", "Uh", "So...", "And then", "Like", "You know").
   - NEVER start with low-energy intros ("Hi guys, welcome back", "Today we are").
   - ALWAYS start with a Hook: A strong statement, a question, or high-energy insight.
2. THE "STANDALONE" TEST:
   - Can this segment be shown to a stranger without ANY prior context?
   - If it contains dangling pronouns ("That's why he said that"), it FAILS. Eliminate or expand context.
3. NARRATIVE ARC:
   - Start: Hook (0-3s).
   - Middle: Value/Story (Retain attention).
   - End: Punchline/Conclusion (Satisfying ending). NEVER cut mid-sentence.
4. DURATION MATH:
   - Constraints: Between {min_duration}s and {max_duration}s.
"""


class HookDetector:
    """
    Identifies high-virality 30-60 second clips from timestamped audio transcripts.
    Supports local AI inference (Qwen-0.5B via llama-cli on Metal) with fallback to an offline heuristic NLP virality engine.
    Follows the ViralCutter Standard (No Garbage Starts, Standalone Test, Narrative Arc).
    Guarantees at least 4 clips minimum on all videos.
    """

    def __init__(self, profile: ChannelProfile):
        self.profile = profile
        self.llama_cli_path = self._find_llama_cli()
        self.local_model_path = self._find_local_model()

    def _find_llama_cli(self) -> Optional[str]:
        """Locates the llama-cli binary on Apple Silicon or standard PATH."""
        candidates = [
            "/opt/homebrew/bin/llama-cli",
            "/usr/local/bin/llama-cli",
            shutil.which("llama-cli")
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def _find_local_model(self) -> Optional[str]:
        """Locates the local GGUF model for money-maker viral analysis."""
        project_root = Path(__file__).resolve().parent.parent
        possible_paths = [
            project_root / "models" / "qwen2.5-0.5b-instruct.gguf",
            project_root / "models" / "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            project_root / "models" / "qwen2.5-1.5b-instruct.gguf"
        ]
        for p in possible_paths:
            if p.exists() and p.stat().st_size > 10_000_000:
                return str(p)
        return None

    def detect_clips(
        self,
        words: List[WordTimestamp],
        api_key: Optional[str] = None,
        max_clips: int = 4,
        min_clips: int = 4,
        use_local_ai: bool = True
    ) -> List[DetectedClip]:
        """
        Detects top clips, guaranteeing at least `min_clips` (default: 4).
        Applies local AI enrichment for high-CTR 'money maker' titles and retention hooks.
        """
        if not words:
            return []

        # Enforce minimum guarantee
        min_clips = max(4, min_clips)
        max_clips = max(min_clips, max_clips)

        # 1. Base candidate selection via ViralCutter heuristic engine
        clips = self._detect_via_heuristics(words, max_clips=max_clips, min_clips=min_clips)

        # 2. Local AI "Money Maker" Virality Enrichment
        if use_local_ai and self.llama_cli_path and self.local_model_path and clips:
            try:
                clips = self._enrich_with_local_ai(clips)
            except Exception as e:
                print(f"[HookDetector] Local AI enrichment warning: {e}")

        return clips

    def _detect_via_heuristics(
        self,
        words: List[WordTimestamp],
        max_clips: int = 4,
        min_clips: int = 4
    ) -> List[DetectedClip]:
        """
        Multi-pass ViralCutter candidate generator:
        - Pass 1: Strict non-overlapping top scoring windows.
        - Pass 2: Relaxed overlap fill to guarantee min_clips.
        - Pass 3: Quantile time partitioning fallback ensuring min_clips is ALWAYS met.
        """
        total_duration = words[-1].end if words else 0.0

        # Adjust window constraints dynamically based on video length
        if total_duration < 45.0:
            target_clip_length = max(10.0, total_duration * 0.45)
            min_dur = max(8.0, min(self.profile.min_clip_duration, total_duration * 0.25))
            max_dur = max(min_dur + 5.0, min(self.profile.max_clip_duration, total_duration))
            step_seconds = max(1.5, total_duration / 20.0)
        else:
            target_clip_length = 36.0  # Sweet spot for shorts completion rate
            min_dur = min(self.profile.min_clip_duration, 25.0)
            max_dur = self.profile.max_clip_duration
            step_seconds = max(2.5, min(6.0, total_duration / 25.0))

        # Scan sliding candidate windows
        candidates = []
        current_start = 0.0

        while current_start + min_dur <= total_duration:
            # Words inside candidate duration range
            window_words = [w for w in words if current_start <= w.start <= current_start + max_dur]
            if len(window_words) < 5:
                current_start += step_seconds
                continue

            # Look for natural sentence endpoints
            best_end_idx = len(window_words) - 1
            for idx, w in enumerate(window_words):
                dur = w.end - current_start
                if dur >= min_dur and any(w.word.endswith(p) for p in [".", "!", "?", ","]):
                    if dur >= target_clip_length or idx >= 15:
                        best_end_idx = idx
                        break

            clip_words = window_words[: best_end_idx + 1]
            clip_dur = clip_words[-1].end - clip_words[0].start
            if clip_dur >= min_dur:
                score, hook_summary = self._score_clip_window(clip_words)
                candidates.append((score, clip_words[0].start, clip_words[-1].end, clip_words, hook_summary))

            current_start += step_seconds

        # Sort candidates by virality score descending
        candidates.sort(key=lambda x: x[0], reverse=True)
        selected_raw: List[Dict[str, Any]] = []

        # --- PASS 1: Strict Non-Overlapping Selection ---
        for score, start_s, end_s, c_words, hook in candidates:
            overlaps = False
            for existing in selected_raw:
                overlap_start = max(start_s, existing["start"])
                overlap_end = min(end_s, existing["end"])
                overlap_len = max(0.0, overlap_end - overlap_start)
                if overlap_len > 10.0 or abs(start_s - existing["start"]) < 8.0:
                    overlaps = True
                    break

            if not overlaps:
                selected_raw.append({
                    "score": score,
                    "start": start_s,
                    "end": end_s,
                    "words": c_words,
                    "hook": hook
                })
                if len(selected_raw) >= max_clips:
                    break

        # --- PASS 2: Relaxed Overlap (Fill up to min_clips) ---
        if len(selected_raw) < min_clips:
            for score, start_s, end_s, c_words, hook in candidates:
                too_close = False
                for existing in selected_raw:
                    if abs(start_s - existing["start"]) < 3.5:
                        too_close = True
                        break
                    overlap_start = max(start_s, existing["start"])
                    overlap_end = min(end_s, existing["end"])
                    overlap_len = max(0.0, overlap_end - overlap_start)
                    dur = end_s - start_s
                    if dur > 0 and (overlap_len / dur) > 0.70:
                        too_close = True
                        break

                if not too_close:
                    selected_raw.append({
                        "score": score,
                        "start": start_s,
                        "end": end_s,
                        "words": c_words,
                        "hook": hook
                    })
                    if len(selected_raw) >= min_clips:
                        break

        # --- PASS 3: Quantile Time Partitioning Failsafe (Guarantee at least min_clips) ---
        if len(selected_raw) < min_clips and words:
            slice_dur = total_duration / float(min_clips)
            for i in range(min_clips):
                if len(selected_raw) >= min_clips:
                    break

                target_start = i * slice_dur
                target_end = min(total_duration, target_start + max(slice_dur * 1.25, min_dur))
                slice_words = [w for w in words if target_start <= w.start <= target_end]
                if not slice_words:
                    w_start = int(i * len(words) / min_clips)
                    w_end = min(len(words), int((i + 1) * len(words) / min_clips) + 4)
                    slice_words = words[w_start:w_end]

                if slice_words and not any(abs(existing["start"] - slice_words[0].start) < 0.8 for existing in selected_raw):
                    score, hook_summary = self._score_clip_window(slice_words)
                    selected_raw.append({
                        "score": score,
                        "start": slice_words[0].start,
                        "end": slice_words[-1].end,
                        "words": slice_words,
                        "hook": hook_summary
                    })

        # If STILL under min_clips (e.g. very short clips or identical timestamps), partition word chunks directly
        if len(selected_raw) < min_clips and words:
            n_words = len(words)
            step = max(1, n_words // min_clips)
            for i in range(min_clips):
                if len(selected_raw) >= min_clips:
                    break
                w_start_idx = i * step
                w_end_idx = min(n_words, (i + 1) * step + max(2, step // 2))
                chunk_words = words[w_start_idx:w_end_idx]
                if not chunk_words:
                    chunk_words = words
                if not any(abs(existing["start"] - chunk_words[0].start) < 0.1 for existing in selected_raw):
                    score, hook_summary = self._score_clip_window(chunk_words)
                    selected_raw.append({
                        "score": score,
                        "start": chunk_words[0].start,
                        "end": chunk_words[-1].end,
                        "words": chunk_words,
                        "hook": hook_summary
                    })

        # Build DetectedClip objects
        selected_clips: List[DetectedClip] = []
        for idx, item in enumerate(selected_raw[:max_clips]):
            c_words = item["words"]
            start_s = item["start"]
            end_s = item["end"]
            score = item["score"]
            hook = item["hook"]

            first_sentence = " ".join(w.word for w in c_words[:10])
            clean_title = re.sub(r"[^\w\s]", "", first_sentence).strip()
            if len(clean_title) > 42:
                clean_title = clean_title[:42] + "..."

            selected_clips.append(
                DetectedClip(
                    id=f"clip_{idx + 1}",
                    title=clean_title.title(),
                    hook=hook,
                    start_seconds=start_s,
                    end_seconds=end_s,
                    duration=end_s - start_s,
                    virality_score=min(98, max(75, int(score))),
                    reasoning=f"High speech momentum ({len(c_words)} words in {int(end_s - start_s)}s) following ViralCutter standards.",
                    words=c_words,
                    suggested_title=f"{clean_title.title()} 🔥 {' '.join(self.profile.target_hashtags[:3])}",
                    hashtags=self.profile.target_hashtags
                )
            )

        return selected_clips

    def _score_clip_window(self, words: List[WordTimestamp]) -> (float, str):
        """
        Calculates a retention virality score based on words, speed, and hook keywords.
        Enforces ViralCutter Standards:
        - Rule 1: No Garbage Starts (penalize fillers & low-energy greetings)
        - Rule 2: Standalone Test (penalize dangling context/pronouns)
        - Rule 3: Narrative Arc & Clean Ending (reward terminal punctuation, penalize mid-conjunction cuts)
        """
        if not words:
            return 0.0, ""

        full_text = " ".join(w.word.lower() for w in words)
        first_5s_words = [w for w in words if w.start <= words[0].start + 4.5]
        first_5s_text = " ".join(w.word.lower() for w in first_5s_words)
        first_3_words = [w.word.lower().strip(".,!?") for w in words[:3]]
        first_3_text = " ".join(first_3_words)

        score = 72.0

        # ViralCutter Rule 1: No "Garbage" Starts
        if any(f in first_3_words for f in ["um", "uh"]):
            score -= 15.0
        elif first_3_words and first_3_words[0] in ["so", "like", "and", "well"]:
            score -= 10.0

        low_energy_intros = ["hi guys", "welcome back", "hello everyone", "today we", "in this video", "hey guys"]
        if any(intro in first_5s_text for intro in low_energy_intros):
            score -= 18.0

        # ViralCutter Rule 2: Standalone Test (Dangling pronouns & dependent clauses)
        dangling_openers = ["thats why", "that is why", "and so", "because of", "which means", "so he", "so she", "so they"]
        if any(dang in first_3_text for dang in dangling_openers):
            score -= 12.0

        # Hook words in first 5s (increases retention by 200%)
        hook_triggers = ["why", "how", "what", "never", "secret", "shocking", "stop", "biggest", "insane", "problem", "actually", "listen", "truth", "watch", "nobody"]
        for trigger in hook_triggers:
            if trigger in first_5s_text:
                score += 5.5

        # ViralCutter Rule 3: Narrative Arc - Satisfying Conclusion (No mid-sentence cutoffs)
        last_word = words[-1].word.strip()
        last_clean = last_word.lower().strip(".,!?")
        incomplete_tail_words = ["and", "or", "but", "with", "to", "because", "if", "that", "than", "so", "as", "the", "a"]
        if last_clean in incomplete_tail_words:
            score -= 14.0
        elif any(last_word.endswith(p) for p in [".", "!", "?"]):
            score += 5.0  # Clean punchline/conclusion ending

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

        hook_quote = " ".join(w.word for w in words[:12]) + "..."
        return min(99.0, max(45.0, score)), hook_quote

    def _enrich_with_local_ai(self, clips: List[DetectedClip]) -> List[DetectedClip]:
        """
        Runs local Apple Silicon Metal accelerated Qwen-0.5B via llama-cli to generate
        high-CTR 'Money Maker' titles, retention hooks, and virality scores.
        """
        print(f"[HookDetector] 🤖 Running Local AI ({Path(self.local_model_path).name}) on {len(clips)} candidate clips...")

        for clip in clips:
            transcript = " ".join(w.word for w in clip.words)
            if len(transcript) > 500:
                transcript = transcript[:500] + "..."

            prompt = (
                "<|im_start|>system\n"
                "You are an elite YouTube Shorts & TikTok growth editor. Output ONLY a valid JSON object, nothing else.\n"
                "<|im_end|>\n"
                "<|im_start|>user\n"
                f"Niche: {self.profile.niche} ({self.profile.name})\n"
                f"Transcript: \"{transcript}\"\n\n"
                "Create a viral Money Maker package with curiosity gap, emojis, and high CTR:\n"
                '{"title": "<punchy viral title with emoji>", "hook": "<first 3s hook>", "score": 95, "money_maker_reason": "<1 sentence why viewers watch till end>"}\n'
                "<|im_end|>\n"
                "<|im_start|>assistant\n"
                "{"
            )

            cmd = [
                self.llama_cli_path,
                "-m", self.local_model_path,
                "--simple-io",
                "--log-disable",
                "-st",
                "--no-display-prompt",
                "--repeat-penalty", "1.15",
                "--temp", "0.7",
                "-n", "120",
                "-p", prompt
            ]

            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                raw_out = proc.stdout
                assistant_section = raw_out.split("<|im_start|>assistant")[-1] if "<|im_start|>assistant" in raw_out else raw_out

                # Extract first valid JSON object in assistant section
                json_match = re.search(r"\{[\s\S]*?\}", assistant_section)
                ai_data = None
                if json_match:
                    try:
                        ai_data = json.loads(json_match.group(0))
                    except Exception:
                        pass

                if not ai_data:
                    # Fallback check across all candidate braces
                    for candidate_str in reversed(re.findall(r"\{[^{}]*\}", raw_out)):
                        try:
                            parsed = json.loads(candidate_str)
                            if "title" in parsed and parsed["title"] not in ["...", "<punchy viral title with emoji>"]:
                                ai_data = parsed
                                break
                        except Exception:
                            continue

                if ai_data:
                    title = str(ai_data.get("title", "")).strip("\"' ")
                    hook = str(ai_data.get("hook", "")).strip("\"' ")
                    try:
                        score = int(ai_data.get("score", clip.virality_score))
                    except Exception:
                        score = clip.virality_score
                    reason = str(ai_data.get("money_maker_reason", "")).strip("\"' ")

                    # Sanitize any accidental @ mentions
                    title = re.sub(r"@\w+", "", title).strip()
                    hook = re.sub(r"@\w+", "", hook).strip()

                    if title and not title.startswith("<"):
                        clip.title = title
                        clip.suggested_title = f"{title} {' '.join(self.profile.target_hashtags[:3])}"
                    if hook and hook != "..." and not hook.startswith("<"):
                        clip.hook = hook
                    if 50 <= score <= 100:
                        clip.virality_score = score
                    if reason and reason != "..." and not reason.startswith("<"):
                        clip.reasoning = f"🤖 AI Money Maker Analysis: {reason}"
                    clip.is_ai_enriched = True
                    print(f"[HookDetector] ✨ Local AI optimized {clip.id}: \"{clip.title}\" (Score: {clip.virality_score})")
            except Exception as e:
                print(f"[HookDetector] Local AI warning on {clip.id}: {e}")

        return clips

    def _detect_via_ai(
        self,
        words: List[WordTimestamp],
        api_key: str,
        max_clips: int
    ) -> List[DetectedClip]:
        """Placeholder for cloud LLM hook scoring."""
        return []
