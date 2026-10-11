from dataclasses import dataclass
from typing import List
from pathlib import Path
from autoclip.config import ChannelProfile


@dataclass
class WordTimestamp:
    word: str
    start: float  # seconds
    end: float    # seconds


@dataclass
class SubtitlePhrase:
    words: List[WordTimestamp]
    start: float
    end: float

    @property
    def text(self) -> str:
        return " ".join(w.word for w in self.words)


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp: H:MM:SS.cc"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"


def build_ass_subtitle_file(
    phrases: List[SubtitlePhrase],
    output_path: Path,
    profile: ChannelProfile,
    play_res_x: int = 1080,
    play_res_y: int = 1920
) -> Path:
    """
    Generates an Advanced SubStation Alpha (.ass) file with modern YouTube Shorts karaoke styling:
    - Bold uppercase typography
    - Thick dark outline & shadow
    - Active word highlighted in channel accent color
    - Positioned at vertical 70% (safe zone above YouTube Shorts description and controls)
    """
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{profile.font_name},{profile.font_size},{profile.ass_primary_color},&H000000FF&,&H00000000&,&H80000000&,1,0,0,0,100,100,2,0,1,6,3,2,60,60,540,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    for phrase in phrases:
        if not phrase.words:
            continue
        
        # Split phrase into word-level highlighted events
        for i, active_word in enumerate(phrase.words):
            event_start = format_ass_time(active_word.start)
            event_end = format_ass_time(active_word.end)

            # Build line text where active word is highlighted
            formatted_words = []
            for j, w in enumerate(phrase.words):
                clean_word = w.word.strip().upper()
                if j == i:
                    # Highlighted active word with subtle scale bump
                    formatted_words.append(f"{{\\c{profile.ass_highlight_color}\\fscx112\\fscy112}}{clean_word}{{\\c{profile.ass_primary_color}\\fscx100\\fscy100}}")
                else:
                    formatted_words.append(clean_word)

            dialogue_line = " ".join(formatted_words)
            events.append(f"Dialogue: 0,{event_start},{event_end},Default,,0,0,0,,{dialogue_line}")

    content = header + "\n".join(events) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def group_words_into_short_phrases(
    words: List[WordTimestamp],
    max_words_per_phrase: int = 3,
    max_pause_seconds: float = 0.4
) -> List[SubtitlePhrase]:
    """
    Groups rapid continuous words into punchy 2-4 word phrases optimized for YouTube Shorts retention.
    """
    if not words:
        return []

    phrases: List[SubtitlePhrase] = []
    current_chunk: List[WordTimestamp] = []

    for word in words:
        if not current_chunk:
            current_chunk.append(word)
            continue

        prev_word = current_chunk[-1]
        pause = word.start - prev_word.end

        # Break on punctuation, long pause, or max word threshold
        has_punctuation = any(prev_word.word.endswith(p) for p in [".", "!", "?", ","])
        if len(current_chunk) >= max_words_per_phrase or pause > max_pause_seconds or has_punctuation:
            phrases.append(
                SubtitlePhrase(
                    words=current_chunk,
                    start=current_chunk[0].start,
                    end=current_chunk[-1].end
                )
            )
            current_chunk = [word]
        else:
            current_chunk.append(word)

    if current_chunk:
        phrases.append(
            SubtitlePhrase(
                words=current_chunk,
                start=current_chunk[0].start,
                end=current_chunk[-1].end
            )
        )

    return phrases
