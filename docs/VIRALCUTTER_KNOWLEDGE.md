# 🧠 ViralCutter Knowledge Base & Standards Integration

This document captures the architecture, algorithms, prompting strategies, and virality scoring rules from [RafaelGodoyEbert/ViralCutter](https://github.com/RafaelGodoyEbert/ViralCutter) (an open-source local alternative to Opus Clip) and specifies how they are integrated into AutoClip.

---

## 1. The "ViralCutter Standard" for Virality & Narrative Arc

Viral short-form content (YouTube Shorts, TikTok, Instagram Reels) requires strict editorial rules to maintain viewer retention:

### Rule 1: No "Garbage" Starts
- **Zero Filler Words**: Segments must never start with hesitation sounds or filler conjunctions: `"Um"`, `"Uh"`, `"So..."`, `"And then"`, `"Like"`, `"You know"`, `"Well"`.
- **Zero Low-Energy Intros**: Discard greetings or slow warmups like `"Hi guys, welcome back"`, `"Today we are going to look at"`, `"In this video"`.
- **Mandatory 0–3s Hook**: Every selected clip must begin directly with a provocative question, a shocking statement, a counter-intuitive observation, or high speech velocity that immediately arrests viewer attention.

### Rule 2: The Standalone Test
- **Complete Contextual Independence**: A clip must make 100% sense to a random viewer with zero prior context.
- **No Dangling Pronouns / Dependent Clauses**: Openers like *"That's why he said that"*, *"And so they went back"*, or *"Because of that reason"* fail the test and are penalized or discarded unless context is expanded.

### Rule 3: Narrative Arc & Sentence Integrity
- **Start (0–3s)**: Hook.
- **Middle (3–45s)**: Value / Story / Conflict / Pacing.
- **End**: Satisfying punchline or conclusion. **Never cut mid-sentence**, mid-clause, or on an unfinished preposition/conjunction (`"and"`, `"but"`, `"with"`, `"because"`). Clips must terminate cleanly on a punctuation boundary (`.`, `!`, `?`).

### Rule 4: Duration Math
- Short-form sweet spot: **25 to 58 seconds**.
- Completion rate drops sharply after 60 seconds; under 20 seconds often lacks narrative closure.

---

## 2. Hardware-Accelerated Video Encoding

Video rendering performance is crucial for local video processing. AutoClip adopts ViralCutter's multi-platform encoder detection hierarchy:

| Platform | Encoder | Preset / Options | Benefit |
| :--- | :--- | :--- | :--- |
| **macOS (Apple Silicon & Intel)** | `h264_videotoolbox` | `-b:v 8M -pix_fmt yuv420p` | Hardware Media Engine; 5x–10x faster than CPU, low heat |
| **NVIDIA GPU** | `h264_nvenc` | `-preset p4 -cq 22` | Dedicated NVENC chip |
| **AMD GPU** | `h264_amf` | `-quality speed` | AMD AMF hardware encoder |
| **Intel GPU** | `h264_qsv` | `-preset veryfast` | Intel Quick Sync Video |
| **CPU Fallback** | `libx264` | `-preset fast -crf 20` | Universal fallback if GPU is unavailable |

### Implementation in AutoClip
`VideoEngine.get_best_encoder()` tests the FFmpeg binary environment and applies hardware acceleration (such as `h264_videotoolbox` on macOS), with an automatic fallback to `libx264` if any codec/filter incompatibility arises.

---

## 3. Subtitle Studio & Karaoke ASS Typography

Short-form mobile viewers read captions while watching. Following Hormozi and ViralCutter best practices:

- **Karaoke Highlight**: Spoken word highlighted in real-time (`\fscx112\fscy112` subtle zoom + channel accent color) against a clean background text color.
- **Grouping**: 2 to 4 words per visual chunk (prevents overwhelming the viewer).
- **Safe Zone Alignment**: Captions are anchored at vertical 70% (`MarginV=540` on 1080×1920 canvas) to avoid collision with:
  - YouTube Shorts description, title, and channel badge.
  - Right-side like, comment, share, and remix buttons.
  - Bottom progress scrub bar.
- **Font & Stroke**: Heavy sans-serif bold typefaces (`Arial Black`, `Montserrat ExtraBold`) with thick black outline (`Outline=6`) and drop shadow (`Shadow=3`) to ensure readability on any video background.

---

## 4. YouTube Acquisition & Browser Cookie Fallback

YouTube frequently blocks cloud or automated scraper IPs with bot-check walls or HTTP 403 errors.
ViralCutter addresses this by passing local browser session cookies to `yt-dlp`:

```python
browsers = ["chrome", "brave", "safari", "edge", "firefox"]
for browser in browsers:
    run_ytdlp(["--cookies-from-browser", browser])
```

AutoClip implements this multi-browser cookie fallback in `MediaExtractor.download_youtube_video()`, ensuring reliable downloads even when direct requests are restricted.

---

## 5. Description & Metadata Cleanliness

Per user requirement:
- Descriptions must not include extraneous "Follow @" or "Subscribe to @" promotion lines.
- The output description focuses purely on the hook text and niche hashtags:
  ```
  {clip.hook}

  #Hashtag1 #Hashtag2 #Hashtag3
  ```
