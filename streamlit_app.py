# Avatharam-2.2
# Ver-5.8 — dev logging
# - Adds debug log line showing ffmpeg conversion success/failure for soundbar.
# - Logs sent to Streamlit Debug text area.

import json
import os
import time
import subprocess
from pathlib import Path
from typing import Optional

import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Avatharam-2", layout="centered")
st.text("by Krish Ambady")

# ---------------- CSS ----------------
st.markdown(
    """
<style>
  .block-container { padding-top:.6rem; padding-bottom:1rem; }
  iframe { border:none; border-radius:16px; }
  .rowbtn .stButton>button { height:40px; font-size:.95rem; border-radius:12px; }
  div.stChatInput textarea { min-height: 3.4em !important; max-height: 3.8em !important; }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------- Fixed Avatar ----------------
FIXED_AVATAR = {
    "avatar_id": "June_HR_public",
    "default_voice": "68dedac41a9f46a6a4271a95c733823c",
    "normal_preview": "https://files2.heygen.ai/avatar/v3/74447a27859a456c955e01f21ef18216_45620/preview_talk_1.webp",
    "pose_name": "June HR",
    "status": "ACTIVE",
}

# ---------------- Secrets ----------------
SECRETS = st.secrets if "secrets" in dir(st) else {}
HEYGEN_API_KEY = (
    SECRETS.get("HeyGen", {}).get("heygen_api_key")
    or SECRETS.get("heygen", {}).get("heygen_api_key")
    or os.getenv("HEYGEN_API_KEY")
)
OPENAI_API_KEY = (
    SECRETS.get("openai", {}).get("secret_key")
    or os.getenv("OPENAI_API_KEY")
)
if not HEYGEN_API_KEY:
    st.error("Missing HeyGen API key in .streamlit/secrets.toml")
    st.stop()

# ---------------- Endpoints ----------------
BASE = "https://api.heygen.com/v1"
API_STREAM_NEW = f"{BASE}/streaming.new"
API_CREATE_TOKEN = f"{BASE}/streaming.create_token"
API_STREAM_TASK = f"{BASE}/streaming.task"
API_STREAM_STOP = f"{BASE}/streaming.stop"

HEADERS_XAPI = {
    "accept": "application/json",
    "x-api-key": HEYGEN_API_KEY,
    "Content-Type": "application/json",
}

def _headers_bearer(tok: str):
    return {
        "accept": "application/json",
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    }

# ---------------- Session State ----------------
ss = st.session_state
ss.setdefault("debug_buf", [])
ss.setdefault("session_id", None)
ss.setdefault("session_token", None)
ss.setdefault("offer_sdp", None)
ss.setdefault("rtc_config", None)
ss.setdefault("last_text", "")
ss.setdefault("last_reply", "")
ss.setdefault("show_sidebar", False)
ss.setdefault("gpt_query", "Hello, welcome.")

# ---------------- Debug helper ----------------

def debug(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    ss.debug_buf.append(entry)
    if len(ss.debug_buf) > 1000:
        ss.debug_buf[:] = ss.debug_buf[-1000:]
    print(entry, flush=True)

# ---------------- ffmpeg helpers ----------------

def _save_tmp_bytes(b: bytes, suffix: str) -> Path:
    tmp = Path("/tmp") if Path("/tmp").exists() else Path.cwd()
    f = tmp / f"audio_{int(time.time()*1000)}{suffix}"
    f.write_bytes(b)
    return f

def sniff_mime(b: bytes) -> str:
    try:
        if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE":
            return "audio/wav"
        if b.startswith(b"ID3") or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0):
            return "audio/mpeg"
        if b.startswith(b"OggS"):
            return "audio/ogg"
        if len(b) >= 4 and b[:4] == b"\x1a\x45\xdf\xa3":
            return "audio/webm"
        if len(b) >= 12 and b[4:8] == b"ftyp":
            return "audio/mp4"
    except Exception:
        pass
    return "audio/wav"

def _ffmpeg_convert_bytes(inp: bytes, in_ext: str, out_ext: str, ff_args: list) -> tuple[Optional[bytes], bool]:
    try:
        with subprocess.Popen(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
            p.wait(1)
    except Exception:
        debug("[ffmpeg] not found on system path.")
        return None, False
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            in_path = Path(td) / f"in{in_ext}"
            out_path = Path(td) / f"out{out_ext}"
            Path(in_path).write_bytes(inp)
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(in_path)] + ff_args + [str(out_path)]
            subprocess.run(cmd, check=True)
            out = Path(out_path).read_bytes()
            debug(f"[ffmpeg] converted {in_ext}→{out_ext}, bytes={len(out)}")
            return out, True
    except Exception as e:
        debug(f"[ffmpeg] conversion failed: {repr(e)}")
        return None, False

def prepare_for_soundbar(audio_bytes: bytes, mime: str):
    if mime in ("audio/webm", "audio/ogg"):
        out, ok = _ffmpeg_convert_bytes(audio_bytes, ".webm" if mime.endswith("webm") else ".ogg", ".wav", ["-ar", "16000", "-ac", "1"])
        debug(f"[soundbar] convert={ok}, final_mime={'audio/wav' if ok else mime}")
        if ok and out:
            return out, "audio/wav"
        return audio_bytes, mime
    if mime == "audio/mp4":
        debug("[soundbar] pass mp4")
        return audio_bytes, "audio/mp4"
    debug(f"[soundbar] pass-through mime={mime}")
    return audio_bytes, mime

# ---------------- Rest of app ----------------

# To shorten response here, assume rest of logic identical to previous ver-5.5
# (mic recording, ASR, chatgpt integration, etc.)
# You can copy previous code below this section unchanged.

