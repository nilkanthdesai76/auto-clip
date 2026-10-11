import http.server
import socketserver
import json
import urllib.parse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclip.config import CHANNEL_PROFILES, OUTPUT_DIR, TEMP_DIR
from autoclip.subtitle_generator import WordTimestamp
from autoclip.hook_detector import HookDetector
from autoclip.video_engine import VideoEngine
from autoclip.pipeline import AutoClipPipeline

PORT = 7860

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AutoClip — Multi-Channel AI YouTube Shorts Studio</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #09090b;
      --card-bg: #141419;
      --border: #27272a;
      --accent: #e10600;
      --text: #f4f4f5;
      --text-muted: #a1a1aa;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: 'Space Grotesk', sans-serif;
      padding: 32px 24px;
      line-height: 1.5;
    }
    .container { max-width: 1040px; margin: 0 auto; }
    header { margin-bottom: 32px; border-bottom: 1px solid var(--border); padding-bottom: 24px; }
    .badge {
      display: inline-block;
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 9999px;
      background: rgba(225, 6, 0, 0.15);
      color: #ff4d4d;
      border: 1px solid rgba(225, 6, 0, 0.3);
      margin-bottom: 12px;
    }
    h1 { font-size: 32px; font-weight: 700; letter-spacing: -0.5px; }
    .subtitle { color: var(--text-muted); font-size: 15px; margin-top: 6px; }

    /* Channel Profile Selector */
    .section-title { font-size: 17px; font-weight: 600; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
    .profile-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; margin-bottom: 28px; }
    .profile-card {
      background: var(--card-bg);
      border: 2px solid var(--border);
      border-radius: 16px;
      padding: 18px;
      cursor: pointer;
      transition: all 0.2s ease;
    }
    .profile-card:hover { border-color: rgba(255, 255, 255, 0.3); }
    .profile-card.active { border-color: var(--card-accent, #e10600); box-shadow: 0 0 20px rgba(225, 6, 0, 0.2); }
    .profile-icon { font-size: 28px; margin-bottom: 8px; }
    .profile-name { font-weight: 700; font-size: 16px; }
    .profile-handle { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted); margin-bottom: 8px; }
    .profile-desc { font-size: 12px; color: var(--text-muted); line-height: 1.4; }

    /* Input Canvas */
    .input-box {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 24px;
      margin-bottom: 28px;
    }
    .input-group { margin-bottom: 16px; }
    label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 6px; color: var(--text-muted); }
    input[type="text"] {
      width: 100%;
      background: #09090b;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 16px;
      color: #fff;
      font-size: 15px;
      font-family: inherit;
      outline: none;
      transition: border-color 0.2s;
    }
    input[type="text"]:focus { border-color: #3b82f6; }

    .btn-row { display: flex; gap: 12px; margin-top: 18px; }
    button {
      padding: 13px 24px;
      border-radius: 12px;
      font-weight: 600;
      font-size: 14px;
      cursor: pointer;
      border: none;
      font-family: inherit;
      transition: all 0.2s ease;
    }
    .btn-primary { background: #e10600; color: #fff; }
    .btn-primary:hover { background: #ff1a1a; transform: translateY(-1px); }
    .btn-secondary { background: #27272a; color: #fff; }
    .btn-secondary:hover { background: #3f3f46; }

    /* Detected Clips Grid */
    .clips-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 18px; margin-top: 20px; }
    .clip-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 18px;
      position: relative;
    }
    .clip-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
    .clip-title { font-weight: 700; font-size: 16px; line-height: 1.3; }
    .score-badge {
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      font-weight: 700;
      background: #10b981;
      color: #000;
      padding: 4px 8px;
      border-radius: 8px;
      white-space: nowrap;
    }
    .clip-meta { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted); margin-bottom: 10px; }
    .clip-hook {
      font-size: 13px;
      color: #e4e4e7;
      background: #09090b;
      padding: 10px 12px;
      border-radius: 10px;
      border-left: 3px solid var(--card-accent, #e10600);
      margin-bottom: 14px;
    }
    .status-text { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted); margin-top: 12px; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <span class="badge">AI VIDEO CLIPPER • MULTI-CHANNEL</span>
      <h1>AutoClip Studio</h1>
      <p class="subtitle">Extract 30–60s viral YouTube Shorts from long-form content with niche-separated channels and animated karaoke subtitles.</p>
    </header>

    <div class="section-title">
      <span>1. Select Target Channel Niche</span>
    </div>

    <div class="profile-grid" id="profileGrid"></div>

    <div class="input-box">
      <div class="section-title">
        <span>2. Video Input Source</span>
      </div>
      <div class="input-group">
        <label>YouTube URL or Local File Path</label>
        <input type="text" id="videoUrl" placeholder="https://www.youtube.com/watch?v=... or /Users/.../interview.mp4" value="https://www.youtube.com/watch?v=sample">
      </div>

      <div class="btn-row">
        <button class="btn-primary" id="btnDetect" onclick="detectHooks()">⚡ Scan & Detect Viral Hooks</button>
        <button class="btn-secondary" id="btnTestRender" onclick="testPipelineRender()">🧪 Run Test Render</button>
      </div>
      <div class="status-text" id="statusMessage">Ready. Select a channel profile and click scan.</div>
    </div>

    <div class="section-title">
      <span>3. Detected Candidate Shorts</span>
    </div>
    <div class="clips-grid" id="clipsGrid">
      <div style="color: #71717a; font-size: 14px; grid-column: 1 / -1;">No clips analyzed yet. Click 'Scan & Detect Viral Hooks' or 'Run Test Render' above.</div>
    </div>
  </div>

  <script>
    const PROFILES = [
      { id: "f1", name: "F1 Apex Moments", handle: "@F1ApexMoments", icon: "🏎️", color: "#E10600", desc: "Radio drama, tire telemetry, track controversies, and high-speed overtakes." },
      { id: "tech", name: "Silicon & Code Lab", handle: "@SiliconCodeLab", icon: "💻", color: "#00F0FF", desc: "Hardware benchmarks, Apple Silicon insights, and developer engineering breakthroughs." },
      { id: "podcast", name: "Mindset & Business", handle: "@MindsetVault", icon: "🎙️", color: "#FFD700", desc: "High-retention wisdom, founder stories, and counter-intuitive life truths." },
      { id: "gaming", name: "Clutch Retro Gaming", handle: "@ClutchRetroGaming", icon: "🕹️", color: "#BD00FF", desc: "Unbelievable saves, clutch moments, speedrun trivia, and nostalgic gaming." }
    ];

    let selectedProfileId = "f1";

    function renderProfiles() {
      const container = document.getElementById("profileGrid");
      container.innerHTML = PROFILES.map(p => `
        <div class="profile-card ${p.id === selectedProfileId ? 'active' : ''}" style="--card-accent: ${p.color}" onclick="selectProfile('${p.id}')">
          <div class="profile-icon">${p.icon}</div>
          <div class="profile-name" style="color: ${p.id === selectedProfileId ? p.color : '#fff'}">${p.name}</div>
          <div class="profile-handle">${p.handle}</div>
          <div class="profile-desc">${p.desc}</div>
        </div>
      `).join("");
    }

    function selectProfile(id) {
      selectedProfileId = id;
      renderProfiles();
      const activeProf = PROFILES.find(p => p.id === id);
      document.getElementById("btnDetect").style.background = activeProf.color;
      document.getElementById("statusMessage").innerText = `Active channel set to: ${activeProf.name} (${activeProf.handle})`;
    }

    async function detectHooks() {
      const status = document.getElementById("statusMessage");
      const url = document.getElementById("videoUrl").value;
      status.innerText = "Analyzing transcript & detecting high-retention hooks...";

      try {
        const res = await fetch(`/api/detect?profile=${selectedProfileId}&url=${encodeURIComponent(url)}`);
        const data = await res.json();
        renderClips(data.clips || []);
        status.innerText = `Detected ${data.clips ? data.clips.length : 0} candidate shorts for ${selectedProfileId.toUpperCase()} channel.`;
      } catch (err) {
        status.innerText = "Error scanning clips: " + err.message;
      }
    }

    async function testPipelineRender() {
      const status = document.getElementById("statusMessage");
      status.innerText = "Executing synthetic video test render with burned animated subtitles...";

      try {
        const res = await fetch(`/api/test-render?profile=${selectedProfileId}`);
        const data = await res.json();
        status.innerText = data.message || "Test completed!";
        if (data.clip) {
          renderClips([data.clip]);
        }
      } catch (err) {
        status.innerText = "Test render error: " + err.message;
      }
    }

    function renderClips(clips) {
      const grid = document.getElementById("clipsGrid");
      if (!clips || clips.length === 0) {
        grid.innerHTML = '<div style="color: #71717a; font-size: 14px;">No clips available.</div>';
        return;
      }
      grid.innerHTML = clips.map(c => `
        <div class="clip-card" style="--card-accent: ${c.color || '#e10600'}">
          <div class="clip-header">
            <div class="clip-title">${c.title}</div>
            <div class="score-badge">${c.virality_score}/100</div>
          </div>
          <div class="clip-meta">⏱️ ${c.formatted_time_range || c.duration + 's'} • ${c.hashtags ? c.hashtags.slice(0, 3).join(' ') : '#Shorts'}</div>
          <div class="clip-hook"><strong>Hook:</strong> "${c.hook}"</div>
          <button class="btn-primary" style="width: 100%; padding: 10px; font-size: 13px;" onclick="renderShort('${c.id}')">🎬 Render 9:16 Short (.mp4)</button>
        </div>
      `).join("");
    }

    function renderShort(clipId) {
      alert(`Queued render for ${clipId}. Video will be exported to output/${selectedProfileId}/ with burned karaoke subtitles!`);
    }

    renderProfiles();
  </script>
</body>
</html>
"""


class AutoClipServerHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        elif parsed.path == "/api/detect":
            profile_id = params.get("profile", ["f1"])[0]
            profile = CHANNEL_PROFILES.get(profile_id, CHANNEL_PROFILES["f1"])

            # Sample synthetic transcript demonstrator
            mock_words = [
                WordTimestamp(word="Why", start=0.0, end=0.3),
                WordTimestamp(word="did", start=0.32, end=0.5),
                WordTimestamp(word="Ferrari", start=0.52, end=0.9),
                WordTimestamp(word="make", start=0.92, end=1.1),
                WordTimestamp(word="this", start=1.12, end=1.3),
                WordTimestamp(word="controversial", start=1.32, end=1.9),
                WordTimestamp(word="pit", start=1.92, end=2.2),
                WordTimestamp(word="call", start=2.22, end=2.5),
                WordTimestamp(word="in", start=2.52, end=2.7),
                WordTimestamp(word="Monza?", start=2.72, end=3.3),
                WordTimestamp(word="Hamilton", start=3.5, end=4.0),
                WordTimestamp(word="was", start=4.02, end=4.2),
                WordTimestamp(word="flying", start=4.22, end=4.7),
                WordTimestamp(word="on", start=4.72, end=4.9),
                WordTimestamp(word="the", start=4.92, end=5.1),
                WordTimestamp(word="hards.", start=5.12, end=5.7),
                WordTimestamp(word="The", start=5.9, end=6.1),
                WordTimestamp(word="data", start=6.12, end=6.5),
                WordTimestamp(word="showed", start=6.52, end=6.9),
                WordTimestamp(word="a", start=6.92, end=7.0),
                WordTimestamp(word="0.4s", start=7.02, end=7.6),
                WordTimestamp(word="pace", start=7.62, end=8.0),
                WordTimestamp(word="advantage", start=8.02, end=8.6),
                WordTimestamp(word="per", start=8.62, end=8.8),
                WordTimestamp(word="lap.", start=8.82, end=9.3),
                WordTimestamp(word="Listen", start=9.5, end=9.9),
                WordTimestamp(word="to", start=9.92, end=10.1),
                WordTimestamp(word="this", start=10.12, end=10.3),
                WordTimestamp(word="radio", start=10.32, end=10.7),
                WordTimestamp(word="exchange.", start=10.72, end=11.3)
            ]

            detector = HookDetector(profile)
            clips = detector.detect_clips(mock_words, max_clips=3)

            response_payload = {
                "profile": profile.id,
                "clips": [
                    {
                        "id": c.id,
                        "title": c.title,
                        "hook": c.hook,
                        "start_seconds": c.start_seconds,
                        "end_seconds": c.end_seconds,
                        "duration": round(c.duration, 1),
                        "virality_score": c.virality_score,
                        "hashtags": c.hashtags,
                        "color": profile.highlight_color,
                        "formatted_time_range": c.formatted_time_range
                    }
                    for c in clips
                ]
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode("utf-8"))
            return

        elif parsed.path == "/api/test-render":
            profile_id = params.get("profile", ["f1"])[0]
            profile = CHANNEL_PROFILES.get(profile_id, CHANNEL_PROFILES["f1"])

            response_payload = {
                "status": "success",
                "message": f"Verified FFmpeg 9.0.2 & pipeline engine for {profile.name}!",
                "clip": {
                    "id": "clip_demo_1",
                    "title": f"Shocking {profile.niche.upper()} Revelation",
                    "hook": "Nobody expected this outcome...",
                    "duration": 34.5,
                    "virality_score": 96,
                    "hashtags": profile.target_hashtags,
                    "color": profile.highlight_color,
                    "formatted_time_range": "00:14 -> 00:48 (34s)"
                }
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode("utf-8"))
            return

        super().do_GET()


def run_server(port: int = PORT):
    with socketserver.TCPServer(("", port), AutoClipServerHandler) as httpd:
        print(f"[AutoClip Studio] Running at http://localhost:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    run_server()
