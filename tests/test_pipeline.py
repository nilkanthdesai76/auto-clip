import unittest
import json
from pathlib import Path
from autoclip.config import CHANNEL_PROFILES, TEMP_DIR, OUTPUT_DIR
from autoclip.subtitle_generator import (
    WordTimestamp,
    group_words_into_short_phrases,
    build_ass_subtitle_file
)
from autoclip.hook_detector import HookDetector
from autoclip.video_engine import VideoEngine


class TestAutoClipPipeline(unittest.TestCase):

    def test_channel_profiles_configured(self):
        """Verify all 4 niche channels are configured with distinct branding."""
        expected_niches = ["f1", "tech", "podcast", "gaming"]
        for niche in expected_niches:
            self.assertIn(niche, CHANNEL_PROFILES)
            profile = CHANNEL_PROFILES[niche]
            self.assertIsNotNone(profile.name)
            self.assertIsNotNone(profile.primary_color)
            self.assertIsNotNone(profile.highlight_color)
            self.assertTrue(profile.min_clip_duration < profile.max_clip_duration)

    def test_ass_subtitle_generation(self):
        """Verify ASS karaoke format is syntactically valid."""
        profile = CHANNEL_PROFILES["f1"]
        words = [
            WordTimestamp("Max", 0.0, 0.4),
            WordTimestamp("Verstappen", 0.4, 0.9),
            WordTimestamp("overtakes", 0.9, 1.4),
            WordTimestamp("on", 1.4, 1.6),
            WordTimestamp("the", 1.6, 1.8),
            WordTimestamp("outside!", 1.8, 2.5),
        ]
        phrases = group_words_into_short_phrases(words, max_words_per_phrase=3)
        self.assertEqual(len(phrases), 2)

        out_ass = TEMP_DIR / "test_subtitles.ass"
        build_ass_subtitle_file(phrases, out_ass, profile)

        self.assertTrue(out_ass.exists())
        content = out_ass.read_text(encoding="utf-8")
        self.assertIn("[Script Info]", content)
        self.assertIn("Style: Default", content)
        self.assertIn("Dialogue: 0,", content)
        self.assertIn("\\fscx112", content)  # Word scale-up animation tag
        self.assertIn(profile.ass_highlight_color, content)  # Active word highlight color
        self.assertIn("VERSTAPPEN", content)

    def test_hook_detector(self):
        """Verify algorithmic scoring prioritizes high-energy niche keywords."""
        profile = CHANNEL_PROFILES["f1"]
        detector = HookDetector(profile)

        # 30-second speech sample with F1 keywords
        words = [
            WordTimestamp("Unbelievable", 0.0, 0.6),
            WordTimestamp("overtake", 0.6, 1.1),
            WordTimestamp("by", 1.1, 1.3),
            WordTimestamp("Ferrari", 1.3, 1.8),
            WordTimestamp("into", 1.8, 2.1),
            WordTimestamp("turn", 2.1, 2.4),
            WordTimestamp("one", 2.4, 2.7),
            WordTimestamp("at", 2.7, 2.9),
            WordTimestamp("Monza!", 2.9, 3.5),
        ]
        # Pad with normal words to reach min duration (25s)
        for i in range(4, 28):
            words.append(WordTimestamp(f"lap{i}", float(i), float(i) + 0.8))

        clips = detector.detect_clips(words, max_clips=2)
        self.assertGreater(len(clips), 0)
        top_clip = clips[0]
        self.assertGreaterEqual(top_clip.virality_score, 50)
        self.assertIn("Monza", top_clip.hook)


if __name__ == "__main__":
    unittest.main()
