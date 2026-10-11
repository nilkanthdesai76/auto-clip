import unittest
from autoclip.classifier import classify_video_metadata


class TestClassifier(unittest.TestCase):

    def test_formula_1_detection(self):
        meta = {
            "title": "Qualifying Highlights | 2026 Singapore Grand Prix",
            "channel": "FORMULA 1",
            "categories": ["Sports"],
            "tags": ["F1", "Formula One", "Grand Prix", "Verstappen", "Ferrari"]
        }
        niche, confidence, reason = classify_video_metadata(meta)
        self.assertEqual(niche, "f1")
        self.assertGreaterEqual(confidence, 90)

    def test_tech_detection(self):
        meta = {
            "title": "M4 Max MacBook Pro Full In-Depth Review & Xcode Benchmarks",
            "channel": "Marques Brownlee",
            "categories": ["Science & Technology"],
            "tags": ["Apple Silicon", "MacBook", "Hardware", "M4"]
        }
        niche, confidence, reason = classify_video_metadata(meta)
        self.assertEqual(niche, "tech")
        self.assertGreaterEqual(confidence, 85)

    def test_podcast_detection(self):
        meta = {
            "title": "Alex Hormozi: How to Make $100M with Zero Capital",
            "channel": "The School of Greatness",
            "categories": ["Education"],
            "tags": ["Podcast", "Mindset", "Wealth", "Business", "Habits"]
        }
        niche, confidence, reason = classify_video_metadata(meta)
        self.assertEqual(niche, "podcast")
        self.assertGreaterEqual(confidence, 85)

    def test_gaming_detection(self):
        meta = {
            "title": "UNREAL 1v4 Clutch in Valorant Radiant Lobby",
            "channel": "Shroud",
            "categories": ["Gaming"],
            "tags": ["Gaming", "Valorant", "Clutch", "FPS", "Esports"]
        }
        niche, confidence, reason = classify_video_metadata(meta)
        self.assertEqual(niche, "gaming")
        self.assertGreaterEqual(confidence, 85)


if __name__ == "__main__":
    unittest.main()
