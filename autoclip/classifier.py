import re
from typing import Dict, Any, Tuple
from autoclip.config import CHANNEL_PROFILES, ChannelProfile


KEYWORD_SETS = {
    "f1": [
        "f1", "formula 1", "formula one", "grand prix", "racing", "gp",
        "verstappen", "hamilton", "leclerc", "norris", "piastri", "russell",
        "alonso", "sainz", "ferrari", "red bull", "mercedes", "mclaren",
        "aston martin", "overtake", "pit stop", "drs", "telemetry", "monza",
        "silverstone", "spa", "singapore", "qualifying", "pole position",
        "fia", "motorsport", "paddock"
    ],
    "tech": [
        "python", "javascript", "typescript", "swift", "rust", "c++",
        "programming", "coding", "developer", "software", "web dev",
        "apple silicon", "m1", "m2", "m3", "m4", "macbook", "linux", "terminal",
        "github", "ai", "artificial intelligence", "llm", "chatgpt", "claude",
        "deep learning", "neural network", "machine learning", "hardware", "benchmark"
    ],
    "podcast": [
        "podcast", "interview", "mindset", "habits", "discipline", "motivation",
        "success", "productivity", "psychology", "wealth", "money", "investing",
        "business", "founder", "startup", "ceo", "hormozi", "huberman", "rogan",
        "lex fridman", "life advice", "stoic", "philosophy"
    ],
    "gaming": [
        "gameplay", "gaming", "game", "speedrun", "clutch", "montage", "fps",
        "ps5", "xbox", "nintendo", "pc gaming", "steam", "switch", "esports",
        "minecraft", "gta", "fortnite", "valorant", "call of duty", "elden ring",
        "zelda", "boss fight", "unreal engine"
    ]
}


def classify_video_metadata(metadata: Dict[str, Any]) -> Tuple[str, int, str]:
    """
    Analyzes YouTube video metadata (title, channel, tags, description, categories)
    and automatically identifies the optimal channel profile.

    Returns:
        (profile_id, confidence_percentage, reasoning_text)
    """
    title = metadata.get("title", "").lower()
    channel = metadata.get("channel", "").lower()
    description = metadata.get("description", "").lower()[:1000]
    tags = [t.lower() for t in metadata.get("tags", [])]
    categories = [c.lower() for c in metadata.get("categories", [])]

    corpus = f"{title} {channel} {' '.join(tags)} {' '.join(categories)} {description}"

    scores: Dict[str, int] = {k: 0 for k in CHANNEL_PROFILES.keys()}

    for niche, keywords in KEYWORD_SETS.items():
        for kw in keywords:
            # Title match = high weight
            if kw in title:
                scores[niche] += 5
            # Channel name match = high weight
            if kw in channel:
                scores[niche] += 6
            # Tags match = medium weight
            if any(kw == t or kw in t for t in tags):
                scores[niche] += 3
            # Description match = low weight
            if kw in description:
                scores[niche] += 1

    # Check category hints
    if any("sport" in c for c in categories):
        scores["f1"] += 2
    if any("gaming" in c for c in categories):
        scores["gaming"] += 6
    if any("science" in c or "technology" in c for c in categories):
        scores["tech"] += 4

    best_niche = max(scores, key=scores.get)
    best_score = scores[best_niche]
    total_score = sum(scores.values())

    if best_score == 0 or total_score == 0:
        # Default to podcast/interview or general
        return "podcast", 50, "General conversational content detected."

    confidence = min(99, int((best_score / max(1, total_score)) * 100))
    # If high absolute score, boost confidence
    if best_score >= 15:
        confidence = max(confidence, 90)
    elif best_score >= 8:
        confidence = max(confidence, 78)

    matched_kw = [kw for kw in KEYWORD_SETS[best_niche] if kw in title or kw in channel or any(kw in t for t in tags)][:4]
    reasoning = f"Matched {best_niche.upper()} indicators ({', '.join(matched_kw)}) across channel and title metadata."

    return best_niche, confidence, reasoning
