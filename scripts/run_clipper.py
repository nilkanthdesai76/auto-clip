#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclip.config import CHANNEL_PROFILES
from autoclip.pipeline import AutoClipPipeline


def main():
    parser = argparse.ArgumentParser(description="AutoClip: AI-Powered Multi-Channel YouTube Shorts Generator")
    parser.add_argument("--url", "-u", required=True, help="YouTube URL or local video filepath")
    parser.add_argument("--channel", "-c", default="f1", choices=list(CHANNEL_PROFILES.keys()), help="Target channel profile niche (default: f1)")
    parser.add_argument("--max-clips", "-m", type=int, default=3, help="Maximum number of candidate shorts to generate (default: 3)")
    parser.add_argument("--api-key", "-k", default=None, help="Optional LLM API key for advanced hook detection")

    args = parser.parse_args()

    pipeline = AutoClipPipeline(profile_id=args.channel)
    results = pipeline.process_video(video_input=args.url, max_clips=args.max_clips, api_key=args.api_key)

    print("\n================ SUCCESS ================")
    print(f"Generated {len(results)} shorts for channel '{args.channel}':")
    for r in results:
        print(f" - [{r['clip_id']}] {r['youtube_title']} ({r['duration_seconds']}s) -> {r['video_file']}")
    print("=========================================\n")


if __name__ == "__main__":
    main()
