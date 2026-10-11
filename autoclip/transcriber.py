from typing import List, Optional
from pathlib import Path
from autoclip.subtitle_generator import WordTimestamp


class AudioTranscriber:
    """
    Transcribes audio into word-level timestamps using Whisper or reads existing transcripts.
    """

    def __init__(self, model_size: str = "base"):
        self.model_size = model_size

    def transcribe(self, audio_path: Path) -> List[WordTimestamp]:
        """
        Attempts local faster-whisper or openai-whisper transcription.
        If whisper library is not installed, parses companion transcript or raises informative instructions.
        """
        try:
            from faster_whisper import WhisperModel
            print(f"[Transcriber] Loading faster-whisper ({self.model_size})...")
            model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
            segments, info = model.transcribe(str(audio_path), word_timestamps=True)

            words: List[WordTimestamp] = []
            for segment in segments:
                if segment.words:
                    for w in segment.words:
                        words.append(
                            WordTimestamp(
                                word=w.word.strip(),
                                start=w.start,
                                end=w.end
                            )
                        )
            return words
        except ImportError:
            pass

        try:
            import whisper
            print(f"[Transcriber] Loading openai-whisper ({self.model_size})...")
            model = whisper.load_model(self.model_size)
            result = model.transcribe(str(audio_path), word_timestamps=True)

            words: List[WordTimestamp] = []
            for seg in result.get("segments", []):
                for w in seg.get("words", []):
                    words.append(
                        WordTimestamp(
                            word=w.get("word", "").strip(),
                            start=w.get("start", 0.0),
                            end=w.get("end", 0.0)
                        )
                    )
            return words
        except ImportError:
            pass

        # Check for companion .srt or .vtt or .json transcript file next to audio
        companion_json = audio_path.with_suffix(".words.json")
        if companion_json.exists():
            import json
            data = json.loads(companion_json.read_text(encoding="utf-8"))
            return [
                WordTimestamp(word=item["word"], start=item["start"], end=item["end"])
                for item in data
            ]

        raise ImportError(
            "Whisper speech recognition library not installed. Run: pip install faster-whisper\n"
            "Alternatively, provide a pre-computed '.words.json' file alongside the audio."
        )
