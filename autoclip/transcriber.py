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
        # 1. Native whisper-cli (whisper.cpp) with Apple Silicon Metal acceleration
        import shutil
        import subprocess
        import json
        import re

        whisper_bin = shutil.which("whisper-cli") or "/opt/homebrew/bin/whisper-cli"
        if Path(whisper_bin).exists():
            models_dir = Path(__file__).resolve().parent.parent / "models"
            model_path = models_dir / "ggml-tiny.en.bin"
            if not model_path.exists():
                model_path = models_dir / "ggml-base.en.bin"

            if model_path.exists():
                print(f"[Transcriber] Transcribing with native Apple Silicon Metal whisper-cli ({model_path.name})...")
                out_base = audio_path.parent / f"{audio_path.stem}_whisper_out"
                out_json = audio_path.parent / f"{audio_path.stem}_whisper_out.json"
                cmd = [
                    str(whisper_bin),
                    "-m", str(model_path),
                    "-f", str(audio_path),
                    "-ojf",
                    "-of", str(out_base),
                    "-l", "en"
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if out_json.exists():
                    try:
                        data = json.loads(out_json.read_text(encoding="utf-8"))
                        words: List[WordTimestamp] = []
                        for tr in data.get("transcription", []):
                            tokens = tr.get("tokens", [])
                            for tok in tokens:
                                raw_text = tok.get("text", "")
                                # Filter special tokens like [_BEG_], [_TT_...], etc.
                                if not raw_text or raw_text.startswith("[_"):
                                    continue
                                clean_word = raw_text.strip()
                                if not clean_word:
                                    continue
                                offsets = tok.get("offsets", {})
                                w_start = offsets.get("from", 0) / 1000.0
                                w_end = offsets.get("to", 0) / 1000.0
                                if w_end <= w_start:
                                    w_end = w_start + 0.35
                                words.append(WordTimestamp(word=clean_word, start=round(w_start, 2), end=round(w_end, 2)))
                        if words:
                            print(f"[Transcriber] Transcribed {len(words)} words using native whisper-cli.")
                            return words
                    except Exception as e:
                        print(f"[Transcriber] Error parsing whisper-cli output: {e}")

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
