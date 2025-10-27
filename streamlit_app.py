# Avatharam-2.2
# Ver-5.3
# Change log (Ver-5):
# - After Speak/Stop, immediately transcribe captured audio to text (LOCAL ASR)
# - Overwrite the edit textbox content with the transcript
# - Keep all other code exactly as-is

import json
import os
import time
from pathlib import Path
from typing import Optional

import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Avatharam-2", layout="centered")
st.text("by Krish Ambady")
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
# OPENAI_API_KEY is optional now (only used for ChatGPT1 text, not for ASR)

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
ss.setdefault("Name", "Friend")
ss.setdefault("gpt_query", "")

# ---------------- Debug helper ----------------

def debug(msg: str):
    ss.debug_buf.append(str(msg))
    if len(ss.debug_buf) > 1000:
        ss.debug_buf[:] = ss.debug_buf[-1000:]

# ---------------- HTTP helpers ----------------

def _post_xapi(url, payload=None):
    r = requests.post(url, headers=HEADERS_XAPI, data=json.dumps(payload or {}), timeout=60)
    raw = r.text
    try:
        body = r.json()
    except Exception:
        body = {"_raw": raw}
    debug(f"[POST x-api] {url} -> {r.status_code}")
    if r.status_code >= 400:
        debug(raw)
        r.raise_for_status()
    return r.status_code, body


def _post_bearer(url, token, payload=None):
    r = requests.post(url, headers=_headers_bearer(token), data=json.dumps(payload or {}), timeout=60)
    raw = r.text
    try:
        body = r.json()
    except Exception:
        body = {"_raw": raw}
    debug(f"[POST bearer] {url} -> {r.status_code}")
    if r.status_code >= 400:
        debug(raw)
        r.raise_for_status()
    return r.status_code, body

# ---------------- HeyGen helpers ----------------

def new_session(avatar_id: str, voice_id: Optional[str] = None):
    payload = {"avatar_id": avatar_id}
    if voice_id:
        payload["voice_id"] = voice_id
    _, body = _post_xapi(API_STREAM_NEW, payload)
    data = body.get("data") or {}
    sid = data.get("session_id")
    offer_sdp = (data.get("offer") or data.get("sdp") or {}).get("sdp")
    ice2 = data.get("ice_servers2")
    ice1 = data.get("ice_servers")
    if isinstance(ice2, list) and ice2:
        rtc_config = {"iceServers": ice2}
    elif isinstance(ice1, list) and ice1:
        rtc_config = {"iceServers": ice1}
    else:
        rtc_config = {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
    if not sid or not offer_sdp:
        raise RuntimeError(f"Missing session_id or offer in response: {body}")
    return {"session_id": sid, "offer_sdp": offer_sdp, "rtc_config": rtc_config}


def create_session_token(session_id: str) -> str:
    _, body = _post_xapi(API_CREATE_TOKEN, {"session_id": session_id})
    tok = (body.get("data") or {}).get("token") or (body.get("data") or {}).get("access_token")
    if not tok:
        raise RuntimeError(f"Missing token in response: {body}")
    return tok


def send_text_to_avatar(session_id: str, session_token: str, text: str):
    debug(f"[avatar] speak {len(text)} chars")
    _post_bearer(
        API_STREAM_TASK,
        session_token,
        {
            "session_id": session_id,
            "task_type": "repeat",
            "task_mode": "sync",
            "text": text,
        },
    )


def stop_session(session_id: Optional[str], session_token: Optional[str]):
    if not (session_id and session_token):
        return
    try:
        _post_bearer(API_STREAM_STOP, session_token, {"session_id": session_id})
    except Exception as e:
        debug(f"[stop_session] {e}")

# ---------------- Local ASR helper (UPDATED in Ver-5) ----------------
# We avoid OpenAI for transcription. Try faster-whisper (tiny) locally.
# Falls back to Vosk iff a model path is provided via VOSK_MODEL_PATH.

def _save_bytes_tmp(b: bytes, suffix: str) -> str:
    p = Path(st.experimental_get_query_params().get("tmpdir", [str(Path.cwd())])[0])
    # Use Streamlit's cache dir if available
    try:
        p = Path(st.runtime.scriptrunner.script_run_context.get_script_run_ctx().session_data.script_path).parent
    except Exception:
        pass
    tmp = Path("/tmp") if Path("/tmp").exists() else p
    f = tmp / f"audio_{int(time.time()*1000)}{suffix}"
    f.write_bytes(b)
    return str(f)


def transcribe_local(audio_bytes: bytes, mime: str) -> str:
    # Write to an appropriate temp file extension that whisper can read
    ext = ".wav" if "wav" in mime else ".mp3" if "mp3" in mime else ".webm" if "webm" in mime else ".ogg"
    fpath = _save_bytes_tmp(audio_bytes, ext)
    # Try faster-whisper
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("tiny", device="auto", compute_type="int8")
        segments, info = model.transcribe(fpath, beam_size=1, language="en")
        txt = " ".join(s.text.strip() for s in segments).strip()
        if txt:
            return txt
    except Exception as e:
        st.session_state.debug_buf.append(f"[local asr] faster-whisper error: {repr(e)}")
    # Try Vosk only if model path provided
    try:
        import json as _json
        from vosk import Model, KaldiRecognizer
        model_path = os.getenv("VOSK_MODEL_PATH")
        if model_path and Path(model_path).exists():
            import subprocess
            # Convert to 16k mono wav using ffmpeg if available; otherwise skip
            outwav = fpath if fpath.endswith(".wav") else fpath + ".wav"
            try:
                subprocess.run(["ffmpeg", "-y", "-i", fpath, "-ar", "16000", "-ac", "1", outwav], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                outwav = fpath  # hope it's already wav
            import wave
            wf = wave.open(outwav, "rb")
            rec = KaldiRecognizer(Model(model_path), wf.getframerate())
            rec.SetWords(True)
            result = []
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    j = _json.loads(rec.Result())
                    result.append(j.get("text", ""))
            j = _json.loads(rec.FinalResult())
            result.append(j.get("text", ""))
            txt = " ".join(x.strip() for x in result if x).strip()
            if txt:
                return txt
    except Exception as e:
        st.session_state.debug_buf.append(f"[local asr] vosk error: {repr(e)}")
        return ""
        txt = " ".join(s.text.strip() for s in segments).strip()
        if txt:
            return txt
    except Exception as e:
        st.session_state.debug_buf.append(f"[local asr] faster-whisper error: {repr(e)}")
    # Try Vosk only if model path provided
    try:
        import json as _json
        from vosk import Model, KaldiRecognizer
        model_path = os.getenv("VOSK_MODEL_PATH")
        if model_path and Path(model_path).exists():
            import subprocess
            # Convert to 16k mono wav using ffmpeg if available; otherwise skip
            outwav = fpath if fpath.endswith(".wav") else fpath + ".wav"
            try:
                subprocess.run(["ffmpeg", "-y", "-i", fpath, "-ar", "16000", "-ac", "1", outwav], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                outwav = fpath  # hope it's already wav
            import wave
            wf = wave.open(outwav, "rb")
            rec = KaldiRecognizer(Model(model_path), wf.getframerate())
            rec.SetWords(True)
            result = []
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    j = _json.loads(rec.Result())
                    result.append(j.get("text", ""))
            j = _json.loads(rec.FinalResult())
            result.append(j.get("text", ""))
            txt = " ".join(x.strip() for x in result if x).strip()
            if txt:
                return txt
    except Exception as e:
        st.session_state.debug_buf.append(f"[local asr] vosk error: {repr(e)}")
    return ""

# ---------------- Header: Trigram ----------------
cols = st.columns([1, 12, 1])
with cols[0]:
    if st.button("☰", key="btn_trigram_main", help="Open menu (Trigram for Heaven)"):
        ss.show_sidebar = not ss.show_sidebar
        debug(f"[ui] sidebar -> {ss.show_sidebar}")

# ---------------- Sidebar (Start/Stop) ----------------
if ss.show_sidebar:
    with st.sidebar:
        st.markdown("### Text")
        if st.button("Start", key="btn_start_sidebar"):
            if ss.session_id and ss.session_token:
                stop_session(ss.session_id, ss.session_token)
                time.sleep(0.2)
            debug("Step 1: streaming.new")
            created = new_session(FIXED_AVATAR["avatar_id"], FIXED_AVATAR.get("default_voice"))
            sid, offer_sdp, rtc_config = created["session_id"], created["offer_sdp"], created["rtc_config"]
            debug("Step 2: streaming.create_token")
            tok = create_session_token(sid)
            debug("Step 3: sleep 1.0s before viewer")
            time.sleep(1.0)
            ss.session_id, ss.session_token = sid, tok
            ss.offer_sdp, ss.rtc_config = offer_sdp, rtc_config
            debug(f"[ready] session_id={sid[:8]}…")
        if st.button("Stop", key="btn_stop_sidebar"):
            stop_session(ss.session_id, ss.session_token)
            ss.session_id = None
            ss.session_token = None
            ss.offer_sdp = None
            ss.rtc_config = None
            debug("[stopped] session cleared")

# ---------------- Main viewer area ----------------
viewer_path = Path(__file__).parent / "viewer.html"
viewer_loaded = ss.session_id and ss.session_token and ss.offer_sdp

def _image_compat(url: str, caption: str = ""):
    try:
        st.image(url, caption=caption, use_container_width=True)
    except TypeError:
        try:
            st.image(url, caption=caption, use_column_width=True)
        except TypeError:
            st.image(url, caption=caption)

if viewer_loaded and viewer_path.exists():
    html = (
        viewer_path.read_text(encoding="utf-8")
        .replace("__SESSION_TOKEN__", ss.session_token)
        .replace("__AVATAR_NAME__", FIXED_AVATAR["pose_name"])
        .replace("__SESSION_ID__", ss.session_id)
        .replace("__OFFER_SDP__", json.dumps(ss.offer_sdp)[1:-1])
        .replace("__RTC_CONFIG__", json.dumps(ss.rtc_config or {}))
    )
    components.html(html, height=340, scrolling=False)
else:
    _image_compat(
        FIXED_AVATAR["normal_preview"],
        caption=f"{FIXED_AVATAR['pose_name']} ({FIXED_AVATAR['avatar_id']})",
    )

# ---------------- Voice recorder (A/B) ----------------
try:
    from streamlit_mic_recorder import mic_recorder
    _HAS_MIC = True
except Exception:
    mic_recorder = None  # type: ignore
    _HAS_MIC = False

# Flags to avoid rerun loops after capture
ss.setdefault("voice_ready", False)            # mic produced audio this cycle
ss.setdefault("voice_inserted_once", False)    # we already pushed transcript into edit box

# Simple header sniffer to set correct MIME for st.audio (fixes 0:00/0:00 & iOS error)

def sniff_mime(b: bytes) -> str:
    """Best-effort content sniffing to choose the right audio MIME.
    Avoids hard-coding 'audio/wav' which breaks iOS/Chrome WebM/OGG.
    Uses ASCII-only byte escapes to stay Python-safe.
    """
    try:
        if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE":
            return "audio/wav"
        # MP3: ID3 tag or MPEG frame sync 0xFFEx
        if b.startswith(b"ID3") or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0):
            return "audio/mpeg"
        # OGG
        if b.startswith(b"OggS"):
            return "audio/ogg"
        # EBML header for WebM: 0x1A 0x45 0xDF 0xA3
        if len(b) >= 4 and b[:4] == b"Eß£":
            return "audio/webm"
    except Exception:
        pass
    return "audio/wav"  # safe default

wav_bytes: Optional[bytes] = None
mime: str = "audio/wav"
if _HAS_MIC:
    audio = mic_recorder(
        start_prompt="Speak",
        stop_prompt="Stop",
        just_once=True,                 # prevent continuous byte streams after Stop
        use_container_width=False,
        key="mic_recorder_main",
        # DO NOT force format; let browser choose (fixes iPhone Safari)
    )
    if isinstance(audio, dict) and audio.get("bytes"):
        wav_bytes = audio["bytes"]
        mime = sniff_mime(wav_bytes)
        ss.voice_ready = True
        debug(f"[mic] received {len(wav_bytes)} bytes, mime={mime}")
    elif isinstance(audio, (bytes, bytearray)) and audio:
        wav_bytes = bytes(audio)
        mime = sniff_mime(wav_bytes)
        ss.voice_ready = True
        debug(f"[mic] received {len(wav_bytes)} bytes (raw), mime={mime}")
    else:
        debug("[mic] waiting for recording…")
else:
    st.warning("`streamlit-mic-recorder` is not installed.")

if ss.voice_ready and wav_bytes:
    # 1) TRANSCRIBE FIRST → edit box should show immediately
    if not ss.voice_inserted_once:
        transcript_text = ""
        try:
            transcript_text = transcribe_local(wav_bytes, mime)
        except Exception as e:
            debug(f"[voice→text error] {repr(e)}")
        if not transcript_text:
            transcript_text = "(no speech recognized)"
        ss.gpt_query = transcript_text  # overwrite any existing text
        ss.voice_inserted_once = True
        debug(f"[voice→editbox] {len(transcript_text)} chars; proceeding to soundbar")
    # 2) THEN render the soundbar (so iOS/PC both see duration)
    st.audio(wav_bytes, format=mime, autoplay=False)

# Reset voice_ready flag after we've had a chance to render the audio bar once
if ss.voice_ready and ss.voice_inserted_once:
    ss.voice_ready = False

# ---------------- Actions row (Test-1 + ChatGPT1) ----------------
col1, col2 = st.columns(2, gap="small")
with col1:
    if st.button("Test-1", key="btn_test1_main", use_container_width=True):
        if not (ss.session_id and ss.session_token and ss.offer_sdp):
            st.warning("Start a session first.")
        else:
            send_text_to_avatar(ss.session_id, ss.session_token, "Hello. Welcome to the test demonstration.")
with col2:
    if st.button("ChatGPT1", key="btn_chatgpt1_main", use_container_width=True):
        user_text = (ss.get("gpt_query") or "").strip()
        if not user_text:
            debug("[chatgpt] empty user text; skipping")
        else:
            debug(f"[user→gpt] {len(user_text)} chars")
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-4o-mini",  # use an available model in your account
                "messages": [
                    {"role": "system", "content": "You are a clear, concise assistant."},
                    {"role": "user", "content": user_text},
                ],
                "temperature": 0.6,
                "max_tokens": 600,
            }
            try:
                r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
                debug(f"[openai] status {r.status_code}")
                body = r.json()
                reply = (body.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                if reply:
                    prev = (ss.get("gpt_query") or "").rstrip()
                    joiner = "\n\n" if prev else ""
                    ss.gpt_query = f"{prev}{joiner}Assistant: {reply}"
                    if ss.session_id and ss.session_token:
                        send_text_to_avatar(ss.session_id, ss.session_token, reply)
                else:
                    debug(f"[openai] empty reply: {body}")
            except Exception as e:
                st.error("ChatGPT call failed. See Debug for details.")
                debug(f"[openai error] {repr(e)}")

# ---------------- Edit box (F) under buttons ----------------
ss.gpt_query = st.text_area(
    "Edit message",
    value=ss.get("gpt_query", ""),
    height=140,
    label_visibility="collapsed",
    key="txt_edit_gpt_query",
)

# ---------------- Reply panel (read-only) ----------------
if ss.get("last_reply"):
    st.subheader("ChatGPT Reply (read-only)")
    st.text_area("", value=ss.last_reply, height=160, label_visibility="collapsed", key="txt_reply_ro")

# ---------------- Debug (last) ----------------
st.text_area("Debug", value="\n".join(ss.debug_buf), height=220, disabled=True, key="txt_debug_ro")
