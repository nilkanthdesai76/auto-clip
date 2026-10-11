from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path


@dataclass
class ChannelProfile:
    id: str
    name: str
    niche: str
    handle: str
    description: str
    primary_color: str       # Hex format, e.g. "#FFEB3B"
    highlight_color: str     # Hex format, e.g. "#FF1744"
    ass_primary_color: str   # ASS subtitle format &H00BBGGRR&
    ass_highlight_color: str # ASS subtitle format &H00BBGGRR&
    font_name: str
    font_size: int
    layout_mode: str         # "blurred_stack", "crop_center", "split_screen"
    min_clip_duration: int   # seconds
    max_clip_duration: int   # seconds
    target_hashtags: List[str]
    system_prompt: str


CHANNEL_PROFILES: Dict[str, ChannelProfile] = {
    "f1": ChannelProfile(
        id="f1",
        name="F1 Apex Telemetry & Moments",
        niche="formula1",
        handle="@F1ApexMoments",
        description="High-energy Formula 1 radio banter, track controversies, technical tire debriefs, and dramatic overtakes.",
        primary_color="#FFF500",
        highlight_color="#E10600",
        ass_primary_color="&H0000F5FF&",     # Speed Yellow
        ass_highlight_color="&H000006E1&",   # F1 Racing Red
        font_name="Arial Black",
        font_size=52,
        layout_mode="crop_fill",
        min_clip_duration=25,
        max_clip_duration=58,
        target_hashtags=["#F1", "#Formula1", "#Shorts", "#Racing", "#Motorsport"],
        system_prompt=(
            "You are an expert Formula 1 social media editor. Analyze this race/interview transcript. "
            "Identify moments with intense radio drama, fiery debates, technical car insights, "
            "controversial stewarding decisions, or humorous driver banter. "
            "Prioritize moments with a 3-second hook that immediately grips racing fans."
        )
    ),
    "tech": ChannelProfile(
        id="tech",
        name="Silicon & Code Lab",
        niche="tech",
        handle="@SiliconCodeLab",
        description="Shocking hardware benchmarks, Apple Silicon insights, coding breakthroughs, and developer culture.",
        primary_color="#FFFFFF",
        highlight_color="#00F0FF",
        ass_primary_color="&H00FFFFFF&",     # Crisp White
        ass_highlight_color="&H00FFF000&",   # Cyber Cyan
        font_name="Arial Black",
        font_size=50,
        layout_mode="crop_fill",
        min_clip_duration=25,
        max_clip_duration=55,
        target_hashtags=["#Tech", "#AppleSilicon", "#Coding", "#Software", "#Shorts", "#Developer"],
        system_prompt=(
            "You are a top tech YouTube Shorts strategist. Analyze this transcript for shocking hardware benchmarks, "
            "architectural breakthroughs, surprising developer truths, and contrarian software engineering takes. "
            "The hook must challenge conventional wisdom in the first 3 seconds."
        )
    ),
    "podcast": ChannelProfile(
        id="podcast",
        name="Mindset & Business Vault",
        niche="podcast",
        handle="@MindsetVault",
        description="High-retention business wisdom, psychological insights, founder stories, and counter-intuitive advice.",
        primary_color="#FFFFFF",
        highlight_color="#FFD700",
        ass_primary_color="&H00FFFFFF&",     # Clean White
        ass_highlight_color="&H0000D7FF&",   # Hormozi Gold
        font_name="Arial Black",
        font_size=52,
        layout_mode="crop_fill",
        min_clip_duration=30,
        max_clip_duration=58,
        target_hashtags=["#Podcasts", "#Success", "#Mindset", "#Business", "#Shorts", "#Discipline"],
        system_prompt=(
            "You are an elite short-form editor for top business & philosophy podcasts. "
            "Extract self-contained, emotionally resonant insights where a speaker reveals a hard truth, "
            "practical life strategy, or unforgettable story. The first sentence must be an irresistible hook."
        )
    ),
    "gaming": ChannelProfile(
        id="gaming",
        name="Retro & Clutch Gaming",
        niche="gaming",
        handle="@ClutchRetroGaming",
        description="High-energy game clutches, hilarious fails, retro gaming nostalgia, and viral reactions.",
        primary_color="#FFFFFF",
        highlight_color="#BD00FF",
        ass_primary_color="&H00FFFFFF&",     # White
        ass_highlight_color="&H00FF00BD&",   # Neon Violet
        font_name="Arial Black",
        font_size=54,
        layout_mode="crop_fill",
        min_clip_duration=20,
        max_clip_duration=45,
        target_hashtags=["#Gaming", "#Clutch", "#Gamer", "#Shorts", "#RetroGaming", "#FunnyMoments"],
        system_prompt=(
            "You are a viral gaming clip editor. Look for sudden plot twists, hilarious reactions, "
            "unbelievable clutch saves, or nostalgic gaming trivia. Prioritize punchy, fast-paced moments."
        )
    )
}


DEFAULT_PROFILE = "f1"

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"
