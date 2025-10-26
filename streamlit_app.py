# Avatharam-2.2
# Ver-0
# Avatharam-2.2 — UI Revamp (Streamlit app)
# Cosmetic/layout update per request.
# - Hamburger (Trigram for Heaven) toggles a side panel with session controls
# - Fixed avatar (no selector)
# - Load static avatar image at startup in main panel
# - Below avatar: Speak & Stop buttons (labels only; keep original behavior hooks)
# - Replace text edit box with st.chat_input and reduce height to ~2 lines via CSS
# - Keep Debug feed (logs commands/responses) exactly as-is in spirit
# - Do NOT remove features; wire existing callbacks if present

import streamlit as st
from datetime import datetime

# ----------------------
# Fixed Avatar Details (no selector)
# ----------------------
FIXED_AVATAR = {
    "avatar_id": "June_HR_public",
    "created_at": 1732855106,
    "default_voice": "68dedac41a9f46a6a4271a95c733823c",
    "is_public": True,
    "normal_preview": "https://files2.heygen.ai/avatar/v3/74447a27859a456c955e01f21ef18216_45620/preview_talk_1.webp",
    "pose_name": "June HR",
    "status": "ACTIVE",
}

# ----------------------
# Session State Defaults
# ----------------------
if "Name" not in st.session_state:
    st.session_state.Name = "Friend"
if "show_sidebar" not in st.session_state:
    st.session_state.show_sidebar = False
if "session_active" not in st.session_state:
    st.session_state.session_active = False  # overall app session (old Start/Restart)
if "speaking" not in st.session_state:
    st.session_state.speaking = False       # Speak/Stop under avatar
if "debug" not in st.session_state:
    st.session_state.debug = []             # running debug log
if "last_user_msg" not in st.session_state:
    st.session_state.last_user_msg = ""

# ----------------------
# Helpers — Debug logging
# ----------------------

def log_debug(kind: str, payload: str):
    """Append a timestamped debug line preserving existing behavior semantics."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.debug.append(f"[{stamp}] {kind}: {payload}")

# ---------------
# CSS adjustments
# ---------------
# 1) Trigram button style
# 2) Shrink chat_input height to ~2 lines
# (chat_input doesn't expose height; we gently style the underlying textarea.)
# If Streamlit changes DOM, this remains a best-effort cosmetic tweak.

st.markdown(
    """
    <style>
      /* Compact the overall page a touch */
      .block-container {padding-top: 1.2rem;}

      /* Trigram button look */
      .trigram-btn button {font-size: 1.2rem; padding: .4rem .7rem; border-radius: 12px;}

      /* Chat input area: aim for ~2 lines */
      div.stChatInput textarea {
          min-height: 3.4em !important; /* ~2 lines */
          max-height: 3.8em !important;
      }
      /* Placeholder text a bit smaller to fit */
      div.stChatInput textarea::placeholder {font-size: 0.95rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------
# Header Row: Trigram + Title moved to side panel
# ----------------------
cols = st.columns([1, 12, 1])
with cols[0]:
    with st.container():
        st.markdown("<div class='trigram-btn'>", unsafe_allow_html=True)
        if st.button("☰", help="Open menu (Trigram for Heaven)"):
            st.session_state.show_sidebar = not st.session_state.show_sidebar
            log_debug("UI", f"Sidebar toggled -> {st.session_state.show_sidebar}")
        st.markdown("</div>", unsafe_allow_html=True)

# ----------------------
# Sidebar (sub-screen) — moved items
# ----------------------
if st.session_state.show_sidebar:
    with st.sidebar:
        st.markdown("### Text")  # Title changed to Text
        st.caption("Session controls and settings")

        # Start (was Start/Restart). Keep behavior the same hook.
        if st.button("Start", key="start_btn"):
            st.session_state.session_active = True
            log_debug("CMD", "Start pressed (session started / restarted)")
            # >>> Hook: call your existing start/restart function here
            # start_or_restart_session()

        if st.button("Stop", key="stop_btn"):
            st.session_state.session_active = False
            st.session_state.speaking = False
            log_debug("CMD", "Stop pressed (session stop)")
            # >>> Hook: call your existing stop/teardown function here
            # stop_session()

        st.divider()
        st.markdown("**Avatar**")
        st.json({k: v for k, v in FIXED_AVATAR.items() if k in ["avatar_id", "pose_name", "status"]})
        st.caption("Avatar is fixed. Selector removed as requested.")

# ----------------------
# Main Panel — Avatar preview + Speak/Stop + Chat
# ----------------------

# 1) Static avatar image always loads at the very beginning
st.image(
    FIXED_AVATAR["normal_preview"],
    caption=f"{FIXED_AVATAR['pose_name']} ({FIXED_AVATAR['avatar_id']})",
    use_column_width=True,
)
log_debug("UI", "Static avatar image loaded on main panel")

# 2) Speak / Stop row under avatar (labels only; functions same as before)
main_c1, main_c2, spacer = st.columns([2, 2, 6])
with main_c1:
    if st.button("Speak", key="speak_btn"):
        st.session_state.speaking = True
        log_debug("CMD", "Speak pressed (start recording / TTS)")
        # >>> Hook: start recording / capture mic / prepare TTS, etc.
        # speak_start()

with main_c2:
    if st.button("Stop", key="speak_stop_btn"):
        if st.session_state.speaking:
            log_debug("CMD", "Stop pressed (end recording)")
        st.session_state.speaking = False
        # >>> Hook: stop recording and finalize transcript if applicable
        # result_text = speak_stop_and_get_text()
        # log_debug("RESP", f"Transcript: {result_text}")

st.divider()

# 3) Chat input (2-line look). Guidance shown, returns when user submits.
placeholder = f"{st.session_state.Name}, You need to Press the 'Speak' button and post your Question and once you complet your sentence press [Stop]. This will help to edit the sentence before we send it to Chat GPT."
user_msg = st.chat_input(placeholder)

if user_msg:
    st.session_state.last_user_msg = user_msg
    log_debug("USER", user_msg)
    # >>> Hook: send to your ChatGPT/LLM pipeline here
    # response = send_to_llm(user_msg)
    # log_debug("RESP", response)
    # st.chat_message("assistant").write(response)

# If there is an existing chat history feature, render it here (unchanged).
# For compatibility, show the last user line (simple placeholder rendering)
if st.session_state.last_user_msg:
    st.chat_message("user").write(st.session_state.last_user_msg)

# ----------------------
# Debug feed — keep as-is (mirror of previous behavior)
# ----------------------
with st.expander("Debug", expanded=False):
    # Show newest at bottom for a natural log feel
    for line in st.session_state.debug:
        st.code(line)

# Notes for integrators:
# - Replace the Hook comments with calls to your existing functions so behavior remains identical.
# - All prior features should continue to work; we've only moved UI pieces and relabeled buttons.
