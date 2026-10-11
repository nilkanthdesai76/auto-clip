import http.server
import socketserver
import json
import urllib.parse
import sys
import os
import re
import mimetypes
import shutil
from pathlib import Path
from typing import Dict, Any, List

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclip.config import CHANNEL_PROFILES, OUTPUT_DIR, TEMP_DIR
from autoclip.classifier import classify_video_metadata
from autoclip.audio_extractor import MediaExtractor
from autoclip.hook_detector import HookDetector, DetectedClip
from autoclip.subtitle_generator import WordTimestamp, group_words_into_short_phrases, build_ass_subtitle_file
from autoclip.video_engine import VideoEngine
from autoclip.pipeline import AutoClipPipeline

PORT = 7860

# Cache parsed transcripts in memory for fast rendering
TRANSCRIPT_CACHE: Dict[str, List[WordTimestamp]] = {}


def extract_video_id(url: str) -> str:
    """Extracts YouTube 11-char video ID or generates a sanitized alphanumeric slug."""
    m = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
    if m:
        return m.group(1)
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", url).strip("_")
    return clean[-16:] if clean else "video"


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AutoClip — AI Multi-Channel Shorts Studio</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #09090b;
      --card-bg: #131318;
      --card-hover: #191922;
      --border: #24242d;
      --border-active: #3b82f6;
      --accent: #e10600;
      --text: #f4f4f5;
      --text-muted: #9494a0;
      --radius: 16px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', sans-serif;
      padding: 32px 20px;
      line-height: 1.5;
    }
    .container { max-width: 1140px; margin: 0 auto; }
    
    header {
      margin-bottom: 28px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 20px;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      flex-wrap: wrap;
      gap: 16px;
    }
    .header-left .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 12px;
      border-radius: 9999px;
      background: rgba(225, 6, 0, 0.12);
      color: #ff4d4d;
      border: 1px solid rgba(225, 6, 0, 0.3);
      margin-bottom: 10px;
    }
    h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.8px; }
    .subtitle { color: var(--text-muted); font-size: 14px; margin-top: 4px; }

    /* Top Input Hub */
    .input-panel {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 24px;
      margin-bottom: 28px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.3);
    }
    .url-row {
      display: flex;
      gap: 12px;
      align-items: stretch;
      margin-bottom: 16px;
    }
    .url-input {
      flex: 1;
      background: #060608;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 18px;
      color: #fff;
      font-size: 15px;
      font-family: inherit;
      outline: none;
      transition: border-color 0.2s;
    }
    .url-input:focus { border-color: var(--border-active); }
    
    button {
      cursor: pointer;
      font-family: inherit;
      font-weight: 600;
      font-size: 14px;
      border: none;
      border-radius: 12px;
      transition: all 0.2s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }
    .btn-inspect {
      padding: 0 24px;
      background: linear-gradient(135deg, #2563eb, #1d4ed8);
      color: #fff;
      white-space: nowrap;
    }
    .btn-inspect:hover { filter: brightness(1.15); transform: translateY(-1px); }
    
    .quick-samples {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 12px;
      color: var(--text-muted);
    }
    .sample-pill {
      background: rgba(255,255,255,0.06);
      padding: 4px 10px;
      border-radius: 6px;
      cursor: pointer;
      color: #e4e4e7;
    }
    .sample-pill:hover { background: rgba(255,255,255,0.12); }

    /* Video Metadata Card with AI Auto-Detection */
    .meta-card {
      display: none;
      background: #0d0d12;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
      margin-top: 18px;
      gap: 18px;
    }
    .meta-card.visible { display: flex; }
    .meta-thumb {
      width: 180px;
      height: 101px;
      object-fit: cover;
      border-radius: 10px;
      border: 1px solid var(--border);
    }
    .meta-info { flex: 1; }
    .meta-title { font-size: 16px; font-weight: 700; color: #fff; margin-bottom: 4px; }
    .meta-channel { font-size: 13px; color: var(--text-muted); margin-bottom: 10px; }
    .auto-detect-box {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #10b981;
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 700;
      font-family: 'JetBrains Mono', monospace;
    }
    .detect-reason { font-size: 12px; color: var(--text-muted); margin-top: 6px; }

    /* Channel Profile Selector */
    .section-title {
      font-size: 16px;
      font-weight: 700;
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .profile-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
      margin-bottom: 28px;
    }
    .profile-card {
      background: var(--card-bg);
      border: 2px solid var(--border);
      border-radius: var(--radius);
      padding: 18px;
      cursor: pointer;
      transition: all 0.2s ease;
      position: relative;
    }
    .profile-card:hover { border-color: rgba(255, 255, 255, 0.25); }
    .profile-card.active {
      border-color: var(--card-accent, #e10600);
      background: #171720;
      box-shadow: 0 0 25px rgba(0, 0, 0, 0.5);
    }
    .profile-icon { font-size: 26px; margin-bottom: 8px; }
    .profile-name { font-weight: 700; font-size: 15px; }
    .profile-handle { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-muted); margin-bottom: 8px; }
    .profile-desc { font-size: 12px; color: var(--text-muted); line-height: 1.4; }
    .profile-auto-tag {
      position: absolute;
      top: 14px;
      right: 14px;
      background: #10b981;
      color: #000;
      font-size: 10px;
      font-weight: 800;
      padding: 2px 7px;
      border-radius: 9999px;
      display: none;
    }
    .profile-card.auto-selected .profile-auto-tag { display: inline-block; }

    /* Portrait Framing Selector */
    .layout-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
      margin-bottom: 28px;
    }
    .layout-card {
      background: var(--card-bg);
      border: 2px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      cursor: pointer;
      transition: all 0.2s ease;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .layout-card:hover { border-color: rgba(255,255,255,0.25); }
    .layout-card.active {
      border-color: #3b82f6;
      background: #151828;
      box-shadow: 0 0 20px rgba(59, 130, 246, 0.2);
    }
    .layout-card-header { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 14px; color: #fff; }
    .layout-desc { font-size: 12px; color: var(--text-muted); line-height: 1.4; }

    /* Action Row */
    .action-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      flex-wrap: wrap;
      gap: 12px;
    }
    .btn-detect {
      padding: 14px 28px;
      background: var(--accent);
      color: #fff;
      font-size: 15px;
      font-weight: 700;
      box-shadow: 0 4px 15px rgba(225, 6, 0, 0.3);
    }
    .btn-detect:hover { filter: brightness(1.15); transform: translateY(-1px); }
    .status-text { font-size: 13px; color: var(--text-muted); }

    /* Clips Grid */
    .clips-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
      gap: 20px;
    }
    .clip-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      display: flex;
      flex-direction: column;
      transition: all 0.2s ease;
    }
    .clip-card:hover { border-color: rgba(255,255,255,0.2); }
    .clip-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 12px; }
    .clip-title { font-weight: 700; font-size: 15px; line-height: 1.3; }
    .score-badge {
      font-family: 'JetBrains Mono', monospace;
      font-weight: 800;
      font-size: 11px;
      padding: 4px 8px;
      border-radius: 6px;
      background: rgba(255,255,255,0.08);
      color: #10b981;
      white-space: nowrap;
    }
    .clip-meta { font-size: 12px; color: var(--text-muted); margin-bottom: 12px; }
    .clip-hook {
      background: #08080c;
      border-left: 3px solid var(--card-accent, #e10600);
      padding: 10px 12px;
      border-radius: 0 8px 8px 0;
      font-size: 13px;
      color: #d4d4d8;
      margin-bottom: 18px;
      font-style: italic;
      line-height: 1.4;
    }
    
    /* Video Player & Render Box */
    .player-box {
      margin-top: 12px;
      border-radius: 12px;
      overflow: hidden;
      background: #000;
      display: none;
      flex-direction: column;
      align-items: center;
      padding: 12px;
      border: 1px solid var(--border);
    }
    .player-box.visible { display: flex; }
    video.preview-player {
      width: 100%;
      max-height: 480px;
      border-radius: 8px;
      outline: none;
      box-shadow: 0 4px 20px rgba(0,0,0,0.6);
    }
    .video-actions {
      display: flex;
      gap: 10px;
      width: 100%;
      margin-top: 12px;
    }
    .btn-download {
      flex: 1;
      padding: 10px 14px;
      background: #2563eb;
      color: #fff;
      font-size: 13px;
      font-weight: 700;
      border-radius: 8px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-decoration: none;
      border: 1px solid rgba(255, 255, 255, 0.15);
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
      transition: all 0.2s ease;
    }
    .btn-download:hover {
      background: #1d4ed8;
      box-shadow: 0 4px 14px rgba(37, 99, 235, 0.5);
      transform: translateY(-1px);
    }
    .btn-copy {
      padding: 10px 14px;
      background: #18181b;
      border: 1px solid var(--border);
      color: #a1a1aa;
      font-size: 12px;
    }
    .btn-copy:hover { color: #fff; border-color: #52525b; }

    .btn-render-action {
      margin-top: auto;
      padding: 12px 18px;
      background: #1d4ed8;
      color: #fff;
      font-weight: 700;
      font-size: 13px;
      border-radius: 10px;
    }
    .btn-render-action:hover { filter: brightness(1.15); }
    .btn-render-action:disabled { opacity: 0.5; cursor: not-allowed; }

    /* Progress overlay */
    .progress-bar-container {
      width: 100%;
      height: 6px;
      background: #27272a;
      border-radius: 3px;
      margin-top: 10px;
      overflow: hidden;
      display: none;
    }
    .progress-bar-fill {
      height: 100%;
      width: 0%;
      background: #3b82f6;
      transition: width 0.3s;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="header-left">
        <div class="badge">🎬 AutoClip AI v1.2</div>
        <h1>Multi-Channel YouTube Shorts Studio</h1>
        <p class="subtitle">Auto-categorization, high-speed transcript analysis, and dual-canvas 9:16 vertical render with burned karaoke subtitles.</p>
      </div>
    </header>

    <!-- 1. Video Input Hub -->
    <div class="input-panel">
      <div class="section-title">
        <span>1. Source Video URL & Auto-Categorization</span>
      </div>
      <div class="url-row">
        <input type="text" id="videoUrl" class="url-input" placeholder="Paste YouTube Video URL (e.g., https://www.youtube.com/watch?v=saNK6uUZRyQ)" value="https://www.youtube.com/watch?v=ofZbJdPaH3A" oninput="handleUrlInput()" onpaste="setTimeout(handleUrlInput, 50)" />
        <button class="btn-inspect" onclick="inspectVideo()">🔍 Auto-Detect Category</button>
      </div>

      <div class="quick-samples">
        <span>Quick Samples:</span>
        <span class="sample-pill" onclick="loadSample('https://www.youtube.com/watch?v=ofZbJdPaH3A')">🏎️ F1 Singapore GP</span>
        <span class="sample-pill" onclick="loadSample('https://www.youtube.com/watch?v=30v646536')">💻 Apple Silicon M4 Benchmarks</span>
        <span class="sample-pill" onclick="loadSample('https://www.youtube.com/watch?v=400998822')">🎙️ Alex Hormozi Mindset</span>
      </div>

      <!-- Video Preview & Auto-Detection Card -->
      <div class="meta-card" id="metaCard">
        <img id="metaThumb" class="meta-thumb" src="" alt="Thumbnail" />
        <div class="meta-info">
          <div id="metaTitle" class="meta-title">Video Title</div>
          <div id="metaChannel" class="meta-channel">Channel Name • Duration</div>
          <div class="auto-detect-box" id="autoDetectBadge">
            <span>🤖 AI CATEGORY: <strong id="detectedCategoryLabel">FORMULA 1</strong> (99% Match)</span>
          </div>
          <div class="detect-reason" id="detectReasonText">Matched F1 keywords across channel and tags.</div>
        </div>
      </div>
    </div>

    <!-- 2. Channel Profiles -->
    <div class="section-title">
      <span>2. Target YouTube Channel Branding</span>
      <span style="font-size: 12px; color: var(--text-muted); font-weight: normal;">(Auto-switches to detected category, or manually override)</span>
    </div>
    <div class="profile-grid" id="profileGrid"></div>

    <!-- 3. Portrait Framing Mode -->
    <div class="section-title">
      <span>3. 9:16 Portrait Framing Mode</span>
      <span style="font-size: 12px; color: var(--text-muted); font-weight: normal;">(Choose how your video is formatted for vertical mobile viewing)</span>
    </div>
    <div class="layout-grid" id="layoutGrid">
      <div class="layout-card active" id="layout_crop_fill" onclick="selectLayout('crop_fill')">
        <div class="layout-card-header">
          <span>📱</span>
          <span>Full Portrait Fill (Recommended)</span>
        </div>
        <div class="layout-desc">100% Edge-to-edge vertical screen coverage. No blurred bars. Maximizes mobile viewer engagement and retention.</div>
      </div>
      <div class="layout-card" id="layout_split_screen" onclick="selectLayout('split_screen')">
        <div class="layout-card-header">
          <span>🥞</span>
          <span>Split-Screen Dual Stack</span>
        </div>
        <div class="layout-desc">Top 50% zoomed close-up + Bottom 50% full view. Ideal for action, gaming, reaction & commentary.</div>
      </div>
      <div class="layout-card" id="layout_fit_blur" onclick="selectLayout('fit_blur')">
        <div class="layout-card-header">
          <span>🪟</span>
          <span>Ambient Blurred Fit</span>
        </div>
        <div class="layout-desc">Preserves entire 16:9 aspect ratio in the center with dynamic blurred background glow.</div>
      </div>
    </div>

    <!-- Action & Status -->
    <div class="action-row">
      <button class="btn-detect" id="btnDetect" onclick="detectViralHooks()">⚡ Scan & Detect Viral Hooks</button>
      <div class="status-text" id="statusMessage">Paste a URL above and click Auto-Detect or Scan.</div>
    </div>

    <!-- 3. Candidate Shorts -->
    <div class="section-title">
      <span>3. Candidate Viral Shorts & Video Playback</span>
    </div>
    <div class="clips-grid" id="clipsGrid">
      <div style="color: #71717a; font-size: 14px; grid-column: 1 / -1; padding: 20px 0;">
        No clips scanned yet. Click 'Scan & Detect Viral Hooks' to discover the best 30–60s moments.
      </div>
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
    let autoDetectedId = null;
    let selectedLayoutMode = "crop_fill";
    let currentClips = [];

    function selectLayout(mode) {
      selectedLayoutMode = mode;
      document.querySelectorAll(".layout-card").forEach(c => c.classList.remove("active"));
      const card = document.getElementById(`layout_${mode}`);
      if (card) card.classList.add("active");
      const status = document.getElementById("statusMessage");
      const label = mode === "crop_fill" ? "Full Portrait Fill (100% Screen)" : (mode === "split_screen" ? "Split-Screen Dual Stack" : "Ambient Blurred Fit");
      status.innerText = `Framing layout set to: ${label}`;
    }

    function renderProfiles() {
      const container = document.getElementById("profileGrid");
      container.innerHTML = PROFILES.map(p => `
        <div class="profile-card ${p.id === selectedProfileId ? 'active' : ''} ${p.id === autoDetectedId ? 'auto-selected' : ''}" 
             style="--card-accent: ${p.color}" 
             onclick="selectProfile('${p.id}')">
          <span class="profile-auto-tag">AUTO DETECTED</span>
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

    function loadSample(url) {
      document.getElementById("videoUrl").value = url;
      inspectVideo();
    }

    let currentInspectedUrl = "";
    let urlDebounceTimer = null;

    function handleUrlInput() {
      const url = document.getElementById("videoUrl").value.trim();
      if (!url || url === currentInspectedUrl) return;

      // Clear previous clips and player immediately so user never sees old video data
      currentClips = [];
      const grid = document.getElementById("clipsGrid");
      grid.innerHTML = '<div style="color: #a1a1aa; font-size: 14px; grid-column: 1 / -1; padding: 24px 0; text-align: center;">🔗 New video URL entered. Click <strong>⚡ Scan & Detect Viral Hooks</strong> to analyze new moments.</div>';
      
      const status = document.getElementById("statusMessage");
      status.innerText = "New video URL entered. Auto-detecting category in a moment...";

      clearTimeout(urlDebounceTimer);
      urlDebounceTimer = setTimeout(() => {
        if (url && (url.includes("youtube.com") || url.includes("youtu.be"))) {
          inspectVideo();
        }
      }, 700);
    }

    async function inspectVideo() {
      const url = document.getElementById("videoUrl").value.trim();
      if (!url) return;
      currentInspectedUrl = url;
      const status = document.getElementById("statusMessage");
      status.innerText = "Analyzing video metadata and classifying category...";

      try {
        const res = await fetch(`/api/inspect?url=${encodeURIComponent(url)}`);
        const data = await res.json();
        if (data.error) {
          status.innerText = "Error: " + data.error;
          return;
        }

        // Show metadata card
        const card = document.getElementById("metaCard");
        card.classList.add("visible");
        document.getElementById("metaTitle").innerText = data.metadata.title;
        document.getElementById("metaChannel").innerText = `${data.metadata.channel} • ${Math.round(data.metadata.duration / 60)} min • ${(data.metadata.view_count || 0).toLocaleString()} views`;
        if (data.metadata.thumbnail) {
          document.getElementById("metaThumb").src = data.metadata.thumbnail;
        }

        // Set auto detection
        autoDetectedId = data.detected_niche;
        document.getElementById("detectedCategoryLabel").innerText = data.detected_niche.toUpperCase();
        document.getElementById("detectReasonText").innerText = data.reasoning;
        
        // Auto select channel profile
        selectProfile(data.detected_niche);
        status.innerText = `Auto-detected as ${data.detected_niche.toUpperCase()} (${data.confidence}% confidence). Ready to scan hooks!`;
      } catch (err) {
        status.innerText = "Inspection error: " + err.message;
      }
    }

    async function detectViralHooks() {
      const url = document.getElementById("videoUrl").value.trim();
      if (!url) {
        alert("Please enter a YouTube video URL first.");
        return;
      }
      const status = document.getElementById("statusMessage");
      const grid = document.getElementById("clipsGrid");

      // 1. Sync metadata and channel niche if URL wasn't inspected yet
      if (url !== currentInspectedUrl) {
        status.innerText = "Syncing video metadata for new link...";
        await inspectVideo();
      }

      // 2. Clear previous clips and show real-time progress
      currentClips = [];
      grid.innerHTML = '<div style="color: #60a5fa; font-size: 14px; grid-column: 1 / -1; padding: 32px 0; text-align: center;">⚡ Extracting subtitles & calculating virality scores for this video...</div>';
      status.innerText = `Extracting subtitles and scoring viral moments for ${selectedProfileId.toUpperCase()} channel...`;

      try {
        const res = await fetch(`/api/detect?url=${encodeURIComponent(url)}&profile=${selectedProfileId}&force=1`);
        const data = await res.json();
        if (data.error) {
          status.innerText = "Error: " + data.error;
          grid.innerHTML = `<div style="color: #ef4444; font-size: 14px; grid-column: 1 / -1; padding: 24px 0;">❌ ${data.error}</div>`;
          return;
        }
        currentClips = data.clips || [];
        renderClips(currentClips);
        status.innerText = `Found ${currentClips.length} high-virality moments for ${selectedProfileId.toUpperCase()} channel!`;
      } catch (err) {
        status.innerText = "Detection error: " + err.message;
        grid.innerHTML = `<div style="color: #ef4444; font-size: 14px; grid-column: 1 / -1; padding: 24px 0;">Detection error: ${err.message}</div>`;
      }
    }

    function triggerDownload(event, clipId, videoUrl) {
      let targetUrl = videoUrl;
      if (!targetUrl) {
        const vid = document.getElementById(`vid_${clipId}`);
        targetUrl = vid ? vid.getAttribute("src") : "";
      }
      if (!targetUrl) {
        if (event) event.preventDefault();
        alert("Please render the video first before downloading.");
        return;
      }

      // Ensure ?download=1 is appended to signal attachment download
      const cleanUrl = targetUrl.split("?")[0];
      const filename = cleanUrl.split("/").pop() || `${clipId}.mp4`;
      const downloadEndpoint = `${cleanUrl}?download=1`;

      const status = document.getElementById("statusMessage");
      if (status) status.innerText = `📥 Downloading ${filename} directly to your Mac...`;

      // Direct navigation to attachment endpoint triggers immediate browser file download
      window.location.href = downloadEndpoint;
      if (event) event.preventDefault();
    }

    function renderClips(clips) {
      const grid = document.getElementById("clipsGrid");
      if (!clips || clips.length === 0) {
        grid.innerHTML = '<div style="color: #71717a; font-size: 14px;">No clips available.</div>';
        return;
      }

      grid.innerHTML = clips.map((c, idx) => {
        const isRendered = Boolean(c.rendered_url);
        const videoSrc = c.rendered_url || "";
        const downloadUrl = isRendered ? `${c.rendered_url}?download=1` : "#";
        const filename = isRendered ? c.rendered_url.split("/").pop() : `${c.id}.mp4`;
        const sizeBadge = c.file_size_mb ? ` • ${c.file_size_mb} MB` : "";

        return `
        <div class="clip-card" id="card_${c.id}" style="--card-accent: ${c.color || '#e10600'}">
          <div class="clip-header">
            <div class="clip-title">${c.title}</div>
            <div class="score-badge">🔥 ${c.virality_score}/100</div>
          </div>
          <div class="clip-meta">⏱️ ${c.formatted_time_range || c.duration + 's'} • ${c.hashtags ? c.hashtags.slice(0, 3).join(' ') : '#Shorts'}${sizeBadge}</div>
          <div class="clip-hook"><strong>Hook:</strong> "${c.hook}"</div>

          <!-- Video Player Box (shown once rendered) -->
          <div class="player-box ${isRendered ? 'visible' : ''}" id="player_${c.id}">
            <video class="preview-player" id="vid_${c.id}" controls playsinline src="${videoSrc}"></video>
            <div class="video-actions">
              <a id="download_${c.id}" class="btn-download" href="${downloadUrl}" download="${filename}" onclick="triggerDownload(event, '${c.id}', '${videoSrc}')">
                ⬇️ Download MP4 ${c.file_size_mb ? '(' + c.file_size_mb + 'MB)' : ''}
              </a>
              <button class="btn-copy" onclick="copyMeta('${c.id}')">📋 Copy Meta</button>
            </div>
          </div>

          <div class="progress-bar-container" id="prog_${c.id}">
            <div class="progress-bar-fill" id="fill_${c.id}"></div>
          </div>

          <button class="btn-render-action" id="btn_render_${c.id}" onclick="renderClip('${c.id}', ${idx})" style="${isRendered ? 'background: #10b981;' : ''}">
            ${isRendered ? '🔄 Re-Render 9:16 Short' : '🎬 Render 9:16 Short (Video + Audio)'}
          </button>
        </div>
      `;
      }).join("");
    }

    async function renderClip(clipId, clipIdx) {
      const clip = currentClips[clipIdx];
      const btn = document.getElementById(`btn_render_${clipId}`);
      const prog = document.getElementById(`prog_${clipId}`);
      const fill = document.getElementById(`fill_${clipId}`);
      const status = document.getElementById("statusMessage");

      btn.disabled = true;
      btn.innerText = "⏳ Rendering 9:16 Short (FFmpeg + Audio)...";
      prog.style.display = "block";
      fill.style.width = "40%";
      status.innerText = `Rendering ${clip.title} with burned karaoke subtitles and full audio...`;

      try {
        const url = document.getElementById("videoUrl").value.trim();
        const res = await fetch("/api/render-clip", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: url,
            profile: selectedProfileId,
            clip_id: clip.id,
            start_seconds: clip.start_seconds,
            duration: clip.duration,
            words: clip.words || [],
            layout_mode: selectedLayoutMode
          })
        });

        const data = await res.json();
        fill.style.width = "100%";

        if (data.status === "success") {
          btn.innerText = "🔄 Re-Render 9:16 Short";
          btn.disabled = false;
          btn.style.background = "#10b981";
          
          // Display Video Player & Wire Up Instant Download
          const playerBox = document.getElementById(`player_${clipId}`);
          const vid = document.getElementById(`vid_${clipId}`);
          const dl = document.getElementById(`download_${clipId}`);
          const filename = data.video_url.split("/").pop();

          playerBox.classList.add("visible");
          vid.src = data.video_url;
          vid.load();
          
          dl.href = `${data.video_url}?download=1`;
          dl.setAttribute("download", filename);
          dl.innerHTML = `⬇️ Download MP4 (${data.file_size_mb} MB)`;
          dl.onclick = (e) => triggerDownload(e, clipId, data.video_url);

          // Update clip in local state
          clip.rendered_url = data.video_url;
          clip.file_size_mb = data.file_size_mb;

          status.innerText = `Render complete (${data.file_size_mb} MB)! Click 'Download MP4' to save to your Mac.`;
        } else {
          btn.innerText = "❌ Render Failed";
          btn.disabled = false;
          status.innerText = "Render error: " + (data.error || "Unknown error");
        }
      } catch (err) {
        btn.innerText = "❌ Render Error";
        btn.disabled = false;
        status.innerText = "Render request failed: " + err.message;
      }
    }

    function copyMeta(clipId) {
      const clip = currentClips.find(c => c.id === clipId);
      if (!clip) return;
      const text = `${clip.title}\n\n${clip.hook}\n\nSubscribe to ${clip.handle || '@AutoClip'}!\n\n${(clip.hashtags || []).join(' ')}`;
      navigator.clipboard.writeText(text);
      alert("Copied YouTube Shorts title and description to clipboard!");
    }

    renderProfiles();
    // Auto inspect on load
    inspectVideo();
  </script>
</body>
</html>
"""


class AutoClipServerHandler(http.server.SimpleHTTPRequestHandler):

    def end_headers(self):
        # Enable CORS and Range headers
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        elif parsed.path == "/api/inspect":
            url = params.get("url", [""])[0]
            if not url:
                self._send_json({"error": "No URL provided"}, status=400)
                return

            pipeline = AutoClipPipeline()
            try:
                res = pipeline.inspect_and_classify(url)
                self._send_json({
                    "metadata": res["metadata"],
                    "detected_niche": res["detected_niche"],
                    "confidence": res["confidence"],
                    "reasoning": res["reasoning"],
                    "profile_id": res["profile"].id
                })
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            return

        elif parsed.path == "/api/detect":
            url = params.get("url", [""])[0]
            profile_id = params.get("profile", ["f1"])[0]
            force_refresh = "force" in params or params.get("refresh", ["0"])[0] == "1"

            if force_refresh and url in TRANSCRIPT_CACHE:
                del TRANSCRIPT_CACHE[url]

            profile = CHANNEL_PROFILES.get(profile_id, CHANNEL_PROFILES["f1"])
            vid_id = extract_video_id(url)

            words = None
            extractor = MediaExtractor()

            # 1. Check in-memory cache
            if not force_refresh and url in TRANSCRIPT_CACHE:
                words = TRANSCRIPT_CACHE[url]
            elif url.startswith("http://") or url.startswith("https://"):
                try:
                    words = extractor.fetch_youtube_captions(url, TEMP_DIR)
                    if words:
                        TRANSCRIPT_CACHE[url] = words
                except Exception as e:
                    print(f"[Server] Caption fetch error: {e}")

            # 2. Check local companion words.json
            if not words and not url.startswith("http"):
                local_path = Path(url)
                comp = local_path.with_suffix(".words.json")
                if comp.exists():
                    data = json.loads(comp.read_text(encoding="utf-8"))
                    words = [WordTimestamp(w["word"], w["start"], w["end"]) for w in data]

            # 3. Fallback mock if completely offline
            if not words:
                mock_words = [
                    WordTimestamp("Unbelievable", 0.0, 0.7),
                    WordTimestamp("action", 0.7, 1.2),
                    WordTimestamp("and", 1.2, 1.4),
                    WordTimestamp("drama", 1.4, 1.9),
                    WordTimestamp("in", 1.9, 2.1),
                    WordTimestamp("today's", 2.1, 2.6),
                    WordTimestamp("session!", 2.6, 3.4),
                ]
                for i in range(4, 30):
                    mock_words.append(WordTimestamp(f"segment{i}", float(i), float(i) + 0.8))
                words = mock_words

            detector = HookDetector(profile)
            clips = detector.detect_clips(words, max_clips=4)

            # Store words in cache for render and check if clips are already generated FOR THIS VIDEO
            response_clips = []
            for c in clips:
                expected_file = OUTPUT_DIR / profile.niche / f"{vid_id}_{c.id}_{profile.niche}.mp4"
                has_rendered = expected_file.exists() and expected_file.stat().st_size > 0
                rendered_url = f"/videos/{profile.niche}/{expected_file.name}" if has_rendered else None
                file_size_mb = round(expected_file.stat().st_size / (1024 * 1024), 2) if has_rendered else None

                response_clips.append({
                    "id": c.id,
                    "title": c.title,
                    "hook": c.hook,
                    "start_seconds": c.start_seconds,
                    "end_seconds": c.end_seconds,
                    "duration": round(c.duration, 1),
                    "virality_score": c.virality_score,
                    "hashtags": c.hashtags,
                    "color": profile.highlight_color,
                    "formatted_time_range": c.formatted_time_range,
                    "handle": profile.handle,
                    "words": [{"word": w.word, "start": w.start, "end": w.end} for w in c.words],
                    "rendered_url": rendered_url,
                    "file_size_mb": file_size_mb
                })

            self._send_json({"profile": profile.id, "video_id": vid_id, "clips": response_clips})
            return

        elif parsed.path.startswith("/videos/"):
            # Serve rendered MP4 files from output directory
            rel_path = parsed.path.replace("/videos/", "")
            file_path = OUTPUT_DIR / rel_path
            is_download = "download" in params or params.get("dl", ["0"])[0] == "1"
            if file_path.exists() and file_path.is_file():
                self._stream_video_file(file_path, as_attachment=is_download)
            else:
                self.send_error(404, "Video file not found")
            return

        elif parsed.path == "/api/download":
            # Force-download endpoint for any rendered short
            file_param = params.get("file", [""])[0]
            if not file_param:
                self.send_error(400, "Missing file parameter")
                return
            target_path = (OUTPUT_DIR / file_param.lstrip("/")).resolve()
            if str(target_path).startswith(str(OUTPUT_DIR.resolve())) and target_path.exists() and target_path.is_file():
                self._stream_video_file(target_path, as_attachment=True)
            else:
                self.send_error(404, "Video file not found")
            return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/render-clip":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:
                self._send_json({"error": "Invalid JSON body"}, status=400)
                return

            url = data.get("url", "")
            profile_id = data.get("profile", "f1")
            clip_id = data.get("clip_id", "clip_1")
            start_seconds = float(data.get("start_seconds", 0.0))
            duration = float(data.get("duration", 25.0))
            raw_words = data.get("words", [])

            words = [WordTimestamp(w["word"], w["start"], w["end"]) for w in raw_words]

            profile = CHANNEL_PROFILES.get(profile_id, CHANNEL_PROFILES["f1"])
            extractor = MediaExtractor()
            video_engine = VideoEngine()

            channel_output_dir = OUTPUT_DIR / profile.niche
            channel_output_dir.mkdir(parents=True, exist_ok=True)
            vid_id = extract_video_id(url)
            out_mp4 = channel_output_dir / f"{vid_id}_{clip_id}_{profile.niche}.mp4"

            try:
                # 1. Download or resolve video file
                if url.startswith("http://") or url.startswith("https://"):
                    video_path = extractor.download_youtube_video(url, TEMP_DIR / "downloads")
                else:
                    video_path = Path(url)

                # 2. Build .ass subtitles
                sub_path = TEMP_DIR / f"{vid_id}_{clip_id}_subtitles.ass"
                phrases = group_words_into_short_phrases(words)
                rebased_phrases = []
                for p in phrases:
                    rebased_words = [
                        WordTimestamp(w.word, max(0.0, w.start - start_seconds), max(0.0, w.end - start_seconds))
                        for w in p.words
                    ]
                    rebased_phrases.append(
                        p.__class__(
                            words=rebased_words,
                            start=max(0.0, p.start - start_seconds),
                            end=max(0.0, p.end - start_seconds)
                        )
                    )

                build_ass_subtitle_file(rebased_phrases, sub_path, profile)

                layout_mode = data.get("layout_mode", "crop_fill")

                # 3. Render 9:16 vertical short
                rendered_path = video_engine.render_short(
                    input_video_path=video_path,
                    start_seconds=start_seconds,
                    duration=duration,
                    subtitle_ass_path=sub_path,
                    output_mp4_path=out_mp4,
                    profile=profile,
                    layout_mode=layout_mode
                )

                # Return accessible URL
                video_url = f"/videos/{profile.niche}/{out_mp4.name}"
                self._send_json({
                    "status": "success",
                    "video_url": video_url,
                    "output_path": str(rendered_path),
                    "file_size_mb": round(rendered_path.stat().st_size / (1024 * 1024), 2)
                })
            except Exception as e:
                print(f"[Server] Render error: {e}")
                self._send_json({"error": str(e)}, status=500)
            return

        self.send_error(404, "Endpoint not found")

    def _stream_video_file(self, file_path: Path, as_attachment: bool = False):
        """Streams MP4 file with byte-range support, or forces browser download as attachment."""
        file_size = file_path.stat().st_size
        range_header = self.headers.get("Range")

        # Force download attachment mode
        if as_attachment:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            with open(file_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
            return

        if range_header:
            # Parse 'Range: bytes=start-end'
            range_match = re.search(r"bytes=(\d+)-(\d*)", range_header)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                length = end - start + 1

                self.send_response(206)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

                with open(file_path, "rb") as f:
                    f.seek(start)
                    self.wfile.write(f.read(length))
                return

        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(file_path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def _send_json(self, data: Any, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))


def run_server(port: int = PORT):
    # Enable address reuse so server restarts cleanly
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), AutoClipServerHandler) as httpd:
        print(f"[AutoClip Studio] Running at http://localhost:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    run_server()
