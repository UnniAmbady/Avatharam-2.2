# Avatharam-2.2
# Ver-7.3
# All features from Ver-7.2 retained
# Button styling improved using scoped CSS (generic + section specific)
# Record/Stop centered, Instruction (blue) & ChatGPT (purple) styled consistently

import atexit
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

# =========================================================
# UNIVERSAL STYLES
# =========================================================
st.markdown(
    """
<style>
/* General button reset */
.stButton>button {
    font-size: 1rem !important;
    font-weight: 500 !important;
    border-radius: 12px !important;
    height: 3em !important;
    min-width: 8em !important;
    border: none !important;
    margin: .25rem !important;
}

/* Mic section (Speak / Stop) */
#microw {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 0.6rem;
    margin-bottom: 1rem;
}
#microw button:nth-child(1) {
    background-color: #d32f2f !important;  /* red */
    color: white !important;
}
#microw button:nth-child(2) {
    background-color: #8bc34a !important;  /* light green */
    color: #111 !important;
}

/* Instruction and ChatGPT buttons */
#actionrow {
    display: flex;
    justify-content: center;
    gap: 1rem;
    margin-top: 1.2rem;
}
#actionrow button {
    flex: 1;
    font-size: 1.1rem;
    height: 3em;
}
#actionrow button:first-child {
    background-color: #007bff !important; /* blue */
    color: white !important;
}
#actionrow button:last-child {
    background-color: #4b0082 !important; /* dark purple */
    color: white !important;
}

/* Edit box tweaks for mobile spacing */
textarea {
    border-radius: 10px !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# FIXED AVATAR / CONFIG
# =========================================================
FIXED_AVATAR = {
    "avatar_id": "June_HR_public",
    "default_voice": "68dedac41a9f46a6a4271a95c733823c",
    "normal_preview": "https://files2.heygen.ai/avatar/v3/74447a27859a456c955e01f21ef18216_45620/preview_talk_1.webp",
    "pose_name": "June HR",
}

# API Keys
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

# =========================================================
# SESSION STATE / LOGGER
# =========================================================
ss = st.session_state
defaults = {
    "session_id": None, "session_token": None, "offer_sdp": None, "rtc_config": None,
    "show_sidebar": False, "gpt_query": "Hello, welcome.",
    "voice_ready": False, "voice_inserted_once": False,
    "bgm_should_play": True, "auto_started": False
}
for k, v in defaults.items():
    ss.setdefault(k, v)

def debug(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# =========================================================
# HELPER FUNCTIONS (HeyGen + ASR simplified)
# =========================================================
def _post_xapi(url, payload=None):
    r = requests.post(url, headers=HEADERS_XAPI, data=json.dumps(payload or {}), timeout=60)
    body = {}
    try: body = r.json()
    except: body["_raw"] = r.text
    if r.status_code >= 400:
        debug(f"[POST {url}] error {r.status_code}: {r.text}")
        r.raise_for_status()
    return r.status_code, body

def _post_bearer(url, token, payload=None):
    r = requests.post(url, headers=_headers_bearer(token), data=json.dumps(payload or {}), timeout=60)
    body = {}
    try: body = r.json()
    except: body["_raw"] = r.text
    if r.status_code >= 400:
        debug(f"[POST bearer] {url} -> {r.status_code}")
    return r.status_code, body

def new_session(avatar_id, voice_id=None):
    payload = {"avatar_id": avatar_id}
    if voice_id: payload["voice_id"] = voice_id
    _, body = _post_xapi(API_STREAM_NEW, payload)
    data = body.get("data") or {}
    sid = data.get("session_id")
    offer_sdp = (data.get("offer") or data.get("sdp") or {}).get("sdp")
    ice = data.get("ice_servers2") or data.get("ice_servers") or [{"urls": ["stun:stun.l.google.com:19302"]}]
    return {"session_id": sid, "offer_sdp": offer_sdp, "rtc_config": {"iceServers": ice}}

def create_session_token(session_id):
    _, b = _post_xapi(API_CREATE_TOKEN, {"session_id": session_id})
    return (b.get("data") or {}).get("token") or (b.get("data") or {}).get("access_token")

def send_text_to_avatar(sid, tok, text):
    debug(f"[avatar] speak {len(text)} chars")
    _post_bearer(API_STREAM_TASK, tok, {"session_id": sid, "task_type": "repeat", "task_mode": "sync", "text": text})

def stop_session(sid, tok):
    if not (sid and tok): return
    _post_bearer(API_STREAM_STOP, tok, {"session_id": sid})
    debug("[stop] session stopped")

@atexit.register
def _cleanup(): stop_session(ss.get("session_id"), ss.get("session_token"))

# =========================================================
# AUTO-START LOGIC
# =========================================================
if not ss.auto_started:
    try:
        debug("[auto-start] init")
        created = new_session(FIXED_AVATAR["avatar_id"], FIXED_AVATAR["default_voice"])
        ss.session_id, ss.offer_sdp, ss.rtc_config = created["session_id"], created["offer_sdp"], created["rtc_config"]
        ss.session_token = create_session_token(ss.session_id)
        ss.auto_started = True
        debug("[auto-start] session ready")
    except Exception as e:
        debug(f"[auto-start] fail {e}")

# =========================================================
# VIEWER + MIC + ACTION ROW
# =========================================================
viewer_path = Path(__file__).parent / "viewer.html"
viewer_loaded = ss.session_id and ss.session_token and ss.offer_sdp

if viewer_loaded and viewer_path.exists():
    html = (
        viewer_path.read_text()
        .replace("__SESSION_TOKEN__", ss.session_token)
        .replace("__AVATAR_NAME__", FIXED_AVATAR["pose_name"])
        .replace("__SESSION_ID__", ss.session_id)
        .replace("__OFFER_SDP__", json.dumps(ss.offer_sdp)[1:-1])
        .replace("__RTC_CONFIG__", json.dumps(ss.rtc_config or {}))
    )
    components.html(html, height=340, scrolling=False)

# ---------------- Mic recorder centered ----------------
try:
    from streamlit_mic_recorder import mic_recorder
    _HAS_MIC = True
except Exception:
    _HAS_MIC = False
    mic_recorder = None

st.markdown("<div id='microw'>", unsafe_allow_html=True)
if _HAS_MIC:
    audio = mic_recorder(start_prompt="Speak", stop_prompt="Stop", just_once=True, key="mic_main")
else:
    st.warning("Mic recorder not installed.")
st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Buttons Row ----------------
st.markdown("<div id='actionrow'>", unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1:
    if st.button("Instruction", use_container_width=True):
        if ss.session_id and ss.session_token:
            send_text_to_avatar(
                ss.session_id, ss.session_token,
                "To speak to me, press the record button, pause a second and then speak. Once you have spoken press the [Stop] button."
            )
with col2:
    if st.button("ChatGPT", use_container_width=True):
        text = ss.get("gpt_query", "").strip()
        if text:
            debug("[chatgpt] submit")
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are a clear, concise assistant."},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.6, "max_tokens": 600,
            }
            r = requests.post(url, headers=headers, data=json.dumps(payload))
            reply = (r.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
            if reply:
                ss.gpt_query = f"{text}\n\nAssistant: {reply}"
                send_text_to_avatar(ss.session_id, ss.session_token, reply)
st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Edit box ----------------
ss.gpt_query = st.text_area(
    "Type or edit your message here...",
    value=ss.get("gpt_query", "Hello, welcome."),
    height=140,
    label_visibility="collapsed",
    key="txt_edit_gpt_query",
)

