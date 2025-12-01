import threading
import asyncio
from typing import Dict, Optional

from flask import Flask, request, jsonify, Response

from dreamweaver.agents.orchestrator import DreamWeaverOrchestrator
from dreamweaver.services.storage import list_world_ids, load_world, save_world

app = Flask(__name__)

# Single orchestrator instance
orch = DreamWeaverOrchestrator()

# Per-world locks so concurrent players don't corrupt state
_world_locks: Dict[str, threading.Lock] = {}


def get_world_lock(world_id: str) -> threading.Lock:
    lock = _world_locks.get(world_id)
    if lock is None:
        lock = threading.Lock()
        _world_locks[world_id] = lock
    return lock


def run_async(coro):
    """
    Helper to run async orchestrator calls from Flask's sync routes.
    """
    return asyncio.run(coro)


# --------------------- API endpoints --------------------- #
@app.post("/api/chat")
def api_chat():
    """
    Append a chat message to the world's chat_log.
    Payload:
    {
      "user_id": "...",
      "world_id": "...",
      "message": "..."
    }
    """
    data = request.get_json(force=True) or {}
    user_id = data.get("user_id", "").strip()
    world_id = data.get("world_id", "").strip()
    message = (data.get("message") or "").strip()

    if not user_id or not world_id or not message:
        return jsonify({"error": "user_id, world_id, and message are required"}), 400

    ws = load_world(world_id)
    if ws is None:
        return jsonify({"error": "world does not exist"}), 404

    # Make sure chat_log exists
    if not hasattr(ws, "chat_log") or ws.chat_log is None:
        ws.chat_log = []

    entry = f"{user_id}: {message}"
    ws.chat_log.append(entry)
    # Keep last 200 messages to avoid unbounded growth
    if len(ws.chat_log) > 200:
        ws.chat_log = ws.chat_log[-200:]

    save_world(ws)
    return jsonify({"status": "ok"})


@app.get("/api/chat_history")
def api_chat_history():
    """
    Return the chat history for a world.
    Query:
      /api/chat_history?world_id=lion_world
    """
    world_id = request.args.get("world_id", "").strip()
    if not world_id:
        return jsonify({"error": "world_id is required"}), 400

    ws = load_world(world_id)
    if ws is None:
        return jsonify({"world_id": world_id, "chat": []})

    if not hasattr(ws, "chat_log") or ws.chat_log is None:
        ws.chat_log = []

    return jsonify({"world_id": world_id, "chat": ws.chat_log})

@app.get("/api/worlds")
def api_worlds():
    """
    List all existing world_ids. We treat worlds starting with 'priv_'
    as private, but still return them here; the frontend can decide
    whether to show them publicly.
    """
    world_ids = list_world_ids()
    return jsonify({"worlds": world_ids})

@app.get("/api/players")
def api_players():
    """
    Return a list of active players for a given world_id.
    Query param:
      /api/players?world_id=lion_world
    """
    world_id = request.args.get("world_id", "").strip()
    if not world_id:
        return jsonify({"error": "world_id is required"}), 400

    ws = load_world(world_id)
    if ws is None:
        return jsonify({"world_id": world_id, "players": []})

    # Adjust fields to match your PlayerState dataclass
    players = []
    for user_id, last_ts in ws.active_players.items():
        pstate = ws.players.get(user_id)
        # If PlayerState has role/title/etc, you can include them here
        players.append({
            "user_id": user_id,
            "role": getattr(pstate, "char_class", "wanderer") if pstate else "wanderer",
            "character_name": getattr(pstate, "name", user_id) if pstate else user_id,
        })

    return jsonify({"world_id": world_id, "players": players})

@app.post("/api/action")
def api_action():
    data = request.get_json(force=True) or {}
    user_id = data.get("user_id", "").strip()
    world_id = data.get("world_id", "").strip()
    message = data.get("message", "") or "WAIT"
    seed_prompt_if_new = data.get("seed_prompt_if_new")

    if not user_id or not world_id:
        return jsonify({"error": "user_id and world_id are required"}), 400

    lock = get_world_lock(world_id)
    with lock:
        try:
            run_async(
                orch.apply_action_only(
                    user_id=user_id,
                    world_id=world_id,
                    user_message=message,
                    seed_prompt_if_new=seed_prompt_if_new,
                )
            )
        except Exception as e:
            # Log full traceback to your terminal
            import traceback
            traceback.print_exc()
            # Return error to frontend
            return jsonify({"error": f"server error: {type(e).__name__}: {e}"}), 500

    return jsonify({"status": "ok"})

@app.get("/api/state")
def api_state():
    """
    Return the current 'live' view of a world for a given user.
    Query params:
      /api/state?user_id=...&world_id=...
    """
    user_id = request.args.get("user_id", "").strip()
    world_id = request.args.get("world_id", "").strip()

    if not user_id or not world_id:
        return jsonify({"error": "user_id and world_id are required"}), 400

    lock = get_world_lock(world_id)
    with lock:
        output = run_async(
            orch.get_state_view(
                user_id=user_id,
                world_id=world_id,
            )
        )

    return jsonify(
        {
            "user_id": user_id,
            "world_id": world_id,
            "output": output,
        }
    )

@app.post("/api/turn")
def api_turn():
    """
    Play a single turn:
    Payload JSON:
    {
      "user_id": "...",
      "world_id": "...",
      "message": "...",
      "seed_prompt_if_new": "..." | null
    }
    """
    data = request.get_json(force=True) or {}
    user_id = data.get("user_id", "").strip()
    world_id = data.get("world_id", "").strip()
    message = data.get("message", "") or "WAIT"
    seed_prompt_if_new = data.get("seed_prompt_if_new")

    if not user_id or not world_id:
        return jsonify({"error": "user_id and world_id are required"}), 400

    lock = get_world_lock(world_id)
    with lock:
        # 1) apply the turn (updates world, story_log, last_scene_text, etc.)
        _ = run_async(
            orch.handle_turn(
                user_id=user_id,
                world_id=world_id,
                user_message=message,
                seed_prompt_if_new=seed_prompt_if_new,
            )
        )
        # 2) fetch the structured view (map + story) after the update
        output = run_async(
            orch.get_state_view(
                user_id=user_id,
                world_id=world_id,
            )
        )

    return jsonify(
        {
            "user_id": user_id,
            "world_id": world_id,
            "output": output,
        }
    )



@app.post("/api/leave")
def api_leave():
    """
    Mark a user as having left a given world.
    """
    data = request.get_json(force=True) or {}
    user_id = data.get("user_id", "").strip()
    world_id = data.get("world_id", "").strip()

    if not user_id or not world_id:
        return jsonify({"error": "user_id and world_id are required"}), 400

    lock = get_world_lock(world_id)
    with lock:
        run_async(orch.leave_world(user_id=user_id, world_id=world_id))

    return jsonify({"status": "ok"})


# --------------------- Frontend (HTML) --------------------- #

@app.get("/")
def index() -> Response:
    """
    Serve a simple single-page HTML UI.
    - Ask for user_id
    - Ask for world_id
    - Option to create/join public or private worlds
    - Shows story output and lets the user send actions
    """
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8" />
        <title>DreamWeaver Multiplayer</title>
        <style>
            html, body {
                height: 100%;
            }
            :root {
                --bg-main: #050816;
                --bg-panel: #020617;
                --bg-panel-soft: #020617;
                --accent: #4f46e5;
                --accent-soft: rgba(79, 70, 229, 0.4);
                --border-subtle: #111827;
                --text-main: #f9fafb;
                --text-muted: #9ca3af;
            }
            body {
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: radial-gradient(circle at top, #1f2937 0%, #020617 45%, #000000 100%);
                color: var(--text-main);
                margin: 0;
                padding: 0;
                display: flex;
                flex-direction: column;
                height: 100vh;
                overflow: hidden;       /* ⬅️ prevent whole-page scroll */
            }
            
            /* Slight animated shimmer in the background */
            body::before {
                content: "";
                position: fixed;
                inset: 0;
                background: radial-gradient(circle at 10% 0%, rgba(56, 189, 248, 0.12), transparent 55%),
                            radial-gradient(circle at 90% 100%, rgba(129, 140, 248, 0.18), transparent 55%);
                mix-blend-mode: screen;
                opacity: 0.7;
                pointer-events: none;
                z-index: -1;
            }
            header {
                padding: 12px 16px;
                background: #020617;
                border-bottom: 1px solid #1f2937;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }
            header h1 {
                margin: 0;
                font-size: 1.2rem;
                letter-spacing: 0.06em;
            }
            header span {
                font-size: 0.8rem;
                opacity: 0.8;
            }
            main {
                display: grid;
                grid-template-columns: 280px 1fr 220px;
                gap: 12px;
                padding: 12px;
                flex: 1;
                box-sizing: border-box;
                overflow: hidden;       /* ⬅️ grid itself doesn’t scroll */
            }
            .panel {
                background: radial-gradient(circle at top left, rgba(79, 70, 229, 0.16), var(--bg-panel-soft) 55%);
                border-radius: 12px;
                padding: 12px;
                border: 1px solid var(--border-subtle);
                box-shadow: 0 18px 45px rgba(15, 23, 42, 0.9);
                display: flex;
                flex-direction: column;
                min-height: 0;
                overflow-y: auto;
                transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease, background 0.2s ease;
            }
            .panel:hover {
                transform: translateY(-2px);
                border-color: var(--accent-soft);
                box-shadow: 0 24px 60px rgba(15, 23, 42, 0.95);
            }
            .panel h2 {
                margin-top: 0;
                font-size: 1rem;
                margin-bottom: 8px;
            }
            label {
                font-size: 0.8rem;
                display: block;
                margin-top: 8px;
                margin-bottom: 4px;
                opacity: 0.9;
            }
            input[type="text"], textarea, select {
                width: 100%;
                padding: 7px 9px;
                border-radius: 9px;
                border: 1px solid #1f2937;
                background: #020617;
                color: var(--text-main);
                font-size: 0.9rem;
                box-sizing: border-box;
                outline: none;
                transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
            }
            
            input[type="text"]:focus,
            textarea:focus,
            select:focus {
                border-color: var(--accent);
                box-shadow: 0 0 0 1px rgba(79, 70, 229, 0.7);
                background: #020617ee;
            }
            textarea {
                min-height: 60px;
                resize: vertical;
            }
            button {
                margin-top: 8px;
                padding: 8px 10px;
                border-radius: 999px;
                border: none;
                font-size: 0.85rem;
                cursor: pointer;
                background: linear-gradient(135deg, #4f46e5, #6366f1);
                color: white;
                transition: transform 0.08s ease, box-shadow 0.15s ease, filter 0.1s ease;
                box-shadow: 0 8px 20px rgba(79, 70, 229, 0.45);
            }
            button.secondary {
                background: #111827;
                color: #e5e7eb;
                border: 1px solid #374151;
                box-shadow: 0 4px 12px rgba(15, 23, 42, 0.8);
            }
            button:hover:not(:disabled) {
                transform: translateY(-1px);
                filter: brightness(1.05);
            }
            button:active:not(:disabled) {
                transform: translateY(0);
                filter: brightness(0.95);
            }
            
            button:disabled {
                opacity: 0.5;
                cursor: default;
                box-shadow: none;
            }
            #world-list {
                font-size: 0.8rem;
                max-height: 140px;
                overflow-y: auto;
                border-radius: 8px;
                border: 1px solid #111827;
                padding: 6px 8px;
                background: #020617;
            }
            #world-list div {
                padding: 2px 0;
                cursor: pointer;
                border-radius: 6px;
                transition: background 0.12s ease, transform 0.08s ease;
            }
            #world-list div:hover {
                background: rgba(55, 65, 81, 0.6);
                transform: translateY(-1px);
            }
            #story-panel {
                display: flex;
                flex-direction: column;
                height: 100%;
            }
            /* Floating chat panel (can be shown/hidden) */
            #chat-panel {
                position: fixed;
                right: 12px;
                bottom: 12px;
                width: 320px;
                height: 360px;
                z-index: 50;
                display: none;  /* hidden until toggled on */
                flex-direction: column;
            }

            #chat-panel.visible {
                display: flex;
            }

            #chat-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 6px;
            }

            #chat-messages {
                flex: 1;
                min-height: 0;
                overflow-y: auto;
                font-size: 0.8rem;
                background: #020617;
                border-radius: 8px;
                padding: 6px;
                border: 1px solid #111827;
                white-space: pre-wrap;
            }

            #chat-input-row {
                display: flex;
                gap: 4px;
                margin-top: 6px;
            }

            #chat-input-row input {
                flex: 1;
            }

                        #story-container {
                position: relative;
                flex: 1;
                min-height: 0;
                box-sizing: border-box;
                background: #020617;
                border-radius: 12px;
                padding: 10px;
                border: 1px solid #111827;
                font-family: "JetBrains Mono", "Fira Code", monospace;
                font-size: 0.85rem;
                overflow: hidden;
            }

            #map-output {
                position: absolute;
                top: 8px;
                right: 8px;
                max-width: 45%;
                white-space: pre;
                font-size: 0.75rem;
                background: rgba(15, 23, 42, 0.95);
                border-radius: 8px;
                padding: 6px 8px;
                border: 1px solid #1f2937;
                box-shadow: 0 8px 20px rgba(15, 23, 42, 0.8);
            }

            #story-output {
                position: relative;
                height: 100%;
                overflow-y: auto;
                white-space: pre-wrap;
                padding-right: 48%; /* leave room so text doesn't go under map */
            }

            #story-container::before {
                content: "";
                position: absolute;
                inset: 0;
                background-image:
                    linear-gradient(to right, rgba(31, 41, 55, 0.16) 1px, transparent 1px),
                    linear-gradient(to bottom, rgba(31, 41, 55, 0.16) 1px, transparent 1px);
                background-size: 22px 22px;
                opacity: 0.35;
                pointer-events: none;
            }

            .chat-input-area {
                display: flex;
                gap: 8px;
                margin-top: 8px;
            }
            .chat-input-area input {
                flex: 1;
            }
            /* Typing / status line */
            #status-line {
                margin-top: 4px;
                font-size: 0.75rem;
                min-height: 1em;
                color: var(--text-muted);
            }

            /* "DreamWeaver is thinking…" pulse */
            .status-active {
                animation: statusPulse 1.4s ease-in-out infinite;
            }

            @keyframes statusPulse {
                0%, 100% { opacity: 0.55; }
                50% { opacity: 1; }
            }
            .pill {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                padding: 2px 8px;
                border-radius: 999px;
                font-size: 0.75rem;
                background: radial-gradient(circle at top left, rgba(56,189,248,0.3), rgba(15,23,42,0.9));
                border: 1px solid rgba(148, 163, 184, 0.5);
                box-shadow: 0 0 20px rgba(56, 189, 248, 0.45);
            }
            .status-dot {
                width: 8px;
                height: 8px;
                border-radius: 999px;
                background: #22c55e;
                box-shadow: 0 0 14px rgba(34, 197, 94, 0.9);
            }
            small {
                opacity: 0.8;
            }
            #online-panel {
                display: flex;
                flex-direction: column;
                height: 100%;
            }

            #online-list {
                list-style: none;
                padding-left: 0;
                margin-top: 8px;
                font-size: 0.85rem;
                flex: 1;
                min-height: 0;
                overflow-y: auto;
            }
            
            #online-list li {
                padding: 4px 6px;
                border-radius: 6px;
                margin-bottom: 2px;
                background: rgba(15, 23, 42, 0.9);
            }
            
                        .panel::-webkit-scrollbar,
            #story-output::-webkit-scrollbar,
            #online-list::-webkit-scrollbar {
                width: 6px;
            }

            .panel::-webkit-scrollbar-thumb,
            #story-output::-webkit-scrollbar-thumb,
            #online-list::-webkit-scrollbar-thumb {
                background: rgba(255,255,255,0.15);
                border-radius: 10px;
                border: 2px solid transparent;
                background-clip: content-box;
            }

            .panel::-webkit-scrollbar-thumb:hover,
            #story-output::-webkit-scrollbar-thumb:hover,
            #online-list::-webkit-scrollbar-thumb:hover {
                background: rgba(255,255,255,0.25);
            }

            .panel::-webkit-scrollbar-track,
            #story-output::-webkit-scrollbar-track,
            #online-list::-webkit-scrollbar-track {
                background: transparent;
            }
            
            .panel,
            #story-output,
            #online-list {
                scrollbar-width: thin;
                scrollbar-color: #64748b #020617;
            }



        </style>
    </head>
    <body>
        <header>
            <div>
                <h1>DreamWeaver</h1>
                <span>Multiplayer AI-driven story world</span>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
                <button id="btn-toggle-chat" class="secondary" style="padding:4px 10px; font-size:0.8rem;">
                    💬 Chat
                </button>
                <div id="session-pill" class="pill" style="display:none;">
                    <div class="status-dot"></div>
                    <span id="session-label"></span>
                </div>
            </div>
        </header>

        <main>
            <section class="panel">
                <h2>Player & World</h2>

                <label for="user-id">Your player ID</label>
                <input id="user-id" type="text" placeholder="e.g. lexi" />

                <label for="mode">Mode</label>
                <select id="mode">
                    <option value="create">Create new world</option>
                    <option value="public">Join public world</option>
                    <option value="private">Join private world</option>
                </select>

                <div id="create-world-block">
                    <label for="world-id">New world ID</label>
                    <input id="world-id" type="text" placeholder="e.g. whale_city" />

                    <label for="visibility">World visibility</label>
                    <select id="visibility">
                        <option value="public">Public</option>
                        <option value="private">Private</option>
                    </select>

                    <label for="seed-prompt">Seed prompt (for new worlds)</label>
                    <textarea id="seed-prompt">A floating city built on the back of a glass whale with baby dragons nesting in its ribs.</textarea>
                    <small>Private worlds are hidden from the list and only joinable by exact ID. We use world IDs starting with "priv_" as private.</small>
                </div>

                <div id="public-world-block" style="display:none;">
                    <button id="btn-refresh-worlds" class="secondary">Refresh public world list</button>
                    <label>Public worlds (click to select)</label>
                    <div id="world-list">
                        <div style="opacity:0.7;">Click "Refresh public world list" to load.</div>
                    </div>
                </div>

                <div id="private-world-block" style="display:none;">
                    <label for="private-world-id">Private world ID</label>
                    <input id="private-world-id" type="text" placeholder="Ask the creator for the world ID (starts with 'priv_')" />
                </div>

                <button id="btn-enter" style="width:100%;">🚪 Enter world</button>
                <button id="btn-leave" class="secondary" style="width:100%; margin-top:4px;">🚫 Leave current world</button>
            </section>

            <section id="story-panel" class="panel">
                <h2>Story</h2>

                <div id="story-container">
                    <div id="map-output"></div>
                    <div id="story-output"></div>
                </div>

                <div class="chat-input-area">
                    <input id="message-input" type="text" placeholder="Type what you want to do..." />
                    <button id="btn-send">Send</button>
                </div>
                <div id="status-line">
                    <span id="status-text"></span>
                </div>
            </section>

            
            <section id="online-panel" class="panel">
                <h2>Online Players</h2>
                <ul id="online-list">
                    <li>lexi (you)</li>
                    <!-- later you can populate this dynamically -->
                </ul>
            </section>

        </main>
        
        <div id="chat-panel" class="panel">
            <div id="chat-header">
                <h2 style="margin:0; font-size:0.9rem;">World Chat</h2>
                <button id="btn-close-chat" class="secondary" style="padding:2px 8px; font-size:0.75rem;">✕</button>
            </div>
            <div id="chat-messages"></div>
            <div id="chat-input-row">
                <input id="chat-input" type="text" placeholder="Type a message..." />
                <button id="btn-send-chat">Send</button>
            </div>
        </div>


        <script>
            const baseUrl = "";

            let currentUserId = null;
            let statePollTimer = null;
            let chatPollTimer = null;
            let currentWorldId = null;
            let currentSeedPrompt = null;
            let isBusy = false;

            const userIdInput = document.getElementById("user-id");
            const modeSelect = document.getElementById("mode");
            const worldIdInput = document.getElementById("world-id");
            const visibilitySelect = document.getElementById("visibility");
            const seedPromptInput = document.getElementById("seed-prompt");
            const privateWorldInput = document.getElementById("private-world-id");
            const worldListDiv = document.getElementById("world-list");

            const createBlock = document.getElementById("create-world-block");
            const publicBlock = document.getElementById("public-world-block");
            const privateBlock = document.getElementById("private-world-block");

            const btnRefreshWorlds = document.getElementById("btn-refresh-worlds");
            const btnEnter = document.getElementById("btn-enter");
            const btnLeave = document.getElementById("btn-leave");
            const btnSend = document.getElementById("btn-send");
            const msgInput = document.getElementById("message-input");
            const storyContainer = document.getElementById("story-container");
            const mapDiv = document.getElementById("map-output");
            const storyDiv = document.getElementById("story-output");
            const sessionPill = document.getElementById("session-pill");
            const sessionLabel = document.getElementById("session-label");
            const onlineList = document.getElementById("online-list");
            const statusText = document.getElementById("status-text");
            const statusLine = document.getElementById("status-line");
            const btnToggleChat = document.getElementById("btn-toggle-chat");
            const chatPanel = document.getElementById("chat-panel");
            const btnCloseChat = document.getElementById("btn-close-chat");
            const chatMessagesDiv = document.getElementById("chat-messages");
            const chatInput = document.getElementById("chat-input");
            const btnSendChat = document.getElementById("btn-send-chat");

            function setBusy(v) {
                isBusy = v;
                btnEnter.disabled = v;
                btnSend.disabled = v;
                
                if (v) {
                    statusText.textContent = "✨ DreamWeaver is thinking...";
                    statusLine.classList.add("status-active");
                } else {
                    statusText.textContent = "";
                    statusLine.classList.remove("status-active");
                }
            }
            function openChatPanel() {
                if (!currentWorldId) {
                    alert("Join or create a world first.");
                    return;
                }
                chatPanel.classList.add("visible");
            }

            function closeChatPanel() {
                chatPanel.classList.remove("visible");
            }

            btnToggleChat.addEventListener("click", openChatPanel);
            btnCloseChat.addEventListener("click", closeChatPanel);

            
            function renderChatMessages(messages) {
                if (!Array.isArray(messages)) return;
                chatMessagesDiv.textContent = "";
                messages.forEach(line => {
                    const div = document.createElement("div");
                    div.textContent = line;
                    chatMessagesDiv.appendChild(div);
                });
                chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
            }

            
            function appendOutput(text) {
                const ts = new Date().toLocaleTimeString();
                storyDiv.textContent += `\n[${ts}]\n${text}\n`;
                storyDiv.scrollTop = storyDiv.scrollHeight;
            }

            function appendUserCommand(cmd) {
                const ts = new Date().toLocaleTimeString();
                storyDiv.textContent += `\n[${ts}] You: ${cmd}\n`;
                storyDiv.scrollTop = storyDiv.scrollHeight;
            }

            function updateSessionPill() {
                if (currentUserId && currentWorldId) {
                    sessionPill.style.display = "inline-flex";
                    sessionLabel.textContent = currentUserId + " @ " + currentWorldId;
                } else {
                    sessionPill.style.display = "none";
                }
            }

            function updateModeUI() {
                const mode = modeSelect.value;
                if (mode === "create") {
                    createBlock.style.display = "block";
                    publicBlock.style.display = "none";
                    privateBlock.style.display = "none";
                } else if (mode === "public") {
                    createBlock.style.display = "none";
                    publicBlock.style.display = "block";
                    privateBlock.style.display = "none";
                } else {
                    createBlock.style.display = "none";
                    publicBlock.style.display = "none";
                    privateBlock.style.display = "block";
                }
            }

            modeSelect.addEventListener("change", updateModeUI);
            updateModeUI();

            async function fetchWorlds() {
                worldListDiv.innerHTML = "<div>Loading...</div>";
                try {
                    const res = await fetch(baseUrl + "/api/worlds");
                    if (!res.ok) throw new Error("Failed to fetch worlds");
                    const data = await res.json();
                    const allWorlds = data.worlds || [];
                    const publicWorlds = allWorlds.filter(w => !w.startsWith("priv_"));
                    if (publicWorlds.length === 0) {
                        worldListDiv.innerHTML = "<div style='opacity:0.7;'>No public worlds yet.</div>";
                        return;
                    }
                    worldListDiv.innerHTML = "";
                    publicWorlds.forEach(w => {
                        const div = document.createElement("div");
                        div.textContent = w;
                        div.onclick = () => {
                            worldIdInput.value = w;
                            currentWorldId = w;
                        };
                        worldListDiv.appendChild(div);
                    });
                } catch (err) {
                    console.error(err);
                    worldListDiv.innerHTML = "<div style='color:#f87171;'>Error loading worlds</div>";
                }
            }

            btnRefreshWorlds.onclick = fetchWorlds;
            
            async function pollChat() {
                if (!currentWorldId) return;
                try {
                    const url = baseUrl + "/api/chat_history?world_id=" + encodeURIComponent(currentWorldId);
                    const res = await fetch(url);
                    if (!res.ok) return;
                    const data = await res.json();
                    renderChatMessages(data.chat || []);
                } catch (err) {
                    console.error("Error polling chat", err);
                }
            }

            async function sendAction(message, maybeSeedPrompt) {
                if (!currentUserId || !currentWorldId) {
                    alert("Enter a world first.");
                    return;
                }
                setBusy(true);
                try {
                    const payload = {
                        user_id: currentUserId,
                        world_id: currentWorldId,
                        message: message || "WAIT",
                        seed_prompt_if_new: maybeSeedPrompt || null,
                    };
                    const res = await fetch(baseUrl + "/api/action", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    });
                    if (!res.ok) {
                        let msg = "Error: " + res.status + " " + res.statusText;
                        try {
                            const errData = await res.json();
                            if (errData.error) {
                                msg += " — " + errData.error;
                            }
                        } catch (_) {}
                        appendOutput(msg);
                        return;
                    }
        // We don't get the full story back here; just "ok".
        // The actual view will be updated by pollState().
                    await refreshOnlinePlayers();
        // Optionally force a fresh state fetch right after an action:
                    await pollState();
                } catch (err) {
                    console.error(err);
                    appendOutput("Network error talking to server.");
                } finally {
                    setBusy(false);
                }
            }
            
            
            async function sendTurn(message, maybeSeedPrompt) {
                if (!currentUserId || !currentWorldId) {
                    alert("Enter a world first.");
                    return;
                }
                setBusy(true);
                try {
                    const payload = {
                        user_id: currentUserId,
                        world_id: currentWorldId,
                        message: message || "WAIT",
                        seed_prompt_if_new: maybeSeedPrompt || null,
                    };
                    const res = await fetch(baseUrl + "/api/turn", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    });
                    if (!res.ok) {
                        let msg = "Error: " + res.status + " " + res.statusText;
                        try {
                            const errData = await res.json();
                            if (errData.error) {
                                msg += " — " + errData.error;
                            }
                        } catch (_) {}
                        appendOutput(msg);
                        return;
                    }

                                        const data = await res.json();
                    if (data.output) {
                        const view = data.output;
                        if (view.visual !== undefined && view.visual !== null) {
                            mapDiv.textContent = view.visual;
                        }
                        if (view.story !== undefined && view.story !== null) {
                            storyDiv.textContent = view.story;
                            storyDiv.scrollTop = storyDiv.scrollHeight;
                        }
                    }

                    await refreshOnlinePlayers();
                    // Keep other clients in sync
                    await pollState();

                } catch (err) {
                    console.error(err);
                    appendOutput("Network error talking to server (/api/turn).");
                } finally {
                    setBusy(false);
                }
            }



            async function callLeave() {
                if (!currentUserId || !currentWorldId) return;
                try {
                    await fetch(baseUrl + "/api/leave", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            user_id: currentUserId,
                            world_id: currentWorldId,
                        }),
                    });
                    appendOutput("You left world " + currentWorldId + ".");
                } catch (err) {
                    console.error(err);
                } finally {
                    currentWorldId = null;
                    updateSessionPill();
                    refreshOnlinePlayers();
                }
            }
            
            async function refreshOnlinePlayers() {
                if (!currentWorldId) {
                    onlineList.innerHTML = "<li style='opacity:0.7;'>No world joined.</li>";
                    return;
                }

                try {
                    const res = await fetch(baseUrl + "/api/players?world_id=" + encodeURIComponent(currentWorldId));
                    if (!res.ok) throw new Error("Failed to fetch players");
                    const data = await res.json();
                    const players = data.players || [];

                    if (players.length === 0) {
                        onlineList.innerHTML = "<li style='opacity:0.7;'>No active players.</li>";
                        return;
                    }

                    onlineList.innerHTML = "";
                    players.forEach(p => {
                        const li = document.createElement("li");
                        if (p.user_id === currentUserId) {
                            li.textContent = p.user_id + " (you)";
                        } else {
                            li.textContent = p.user_id;
                        }
                        onlineList.appendChild(li);
                    });
                } catch (err) {
                    console.error(err);
                    onlineList.innerHTML = "<li style='color:#f87171;'>Error loading players</li>";
                }
            }
            
            async function pollState() {
                if (!currentUserId || !currentWorldId) return;
                try {
                    const url = baseUrl + "/api/state?user_id="
                        + encodeURIComponent(currentUserId)
                        + "&world_id="
                        + encodeURIComponent(currentWorldId);

                    const res = await fetch(url);
                    if (!res.ok) return;
                    const data = await res.json();
                    if (data.output) {
                        const view = data.output;
                        if (view.visual !== undefined && view.visual !== null) {
                            mapDiv.textContent = view.visual;
                        }
                        if (view.story !== undefined && view.story !== null) {
                            storyDiv.textContent = view.story;
                            storyDiv.scrollTop = storyDiv.scrollHeight;
                        }
                    }
                } catch (err) {
                    console.error("Error polling state", err);
                }
            }

            
            async function sendChat() {
            if (!currentUserId || !currentWorldId) {
                alert("Enter a world first.");
                return;
            }
            const msg = (chatInput.value || "").trim();
            if (!msg) return;

            try {
                const payload = {
                    user_id: currentUserId,
                    world_id: currentWorldId,
                    message: msg,
                };
                const res = await fetch(baseUrl + "/api/chat", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                if (!res.ok) {
                    console.error("Chat error", res.status, res.statusText);
                    return;
                }
                chatInput.value = "";
                // refresh immediately instead of waiting 2s
                await pollChat();
            } catch (err) {
                console.error("Network error sending chat", err);
            }
        }

        btnSendChat.addEventListener("click", sendChat);
        chatInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendChat();
            }
        });


            // Start polling every 2s
            statePollTimer = setInterval(pollState, 2000);
            chatPollTimer = setInterval(pollChat, 2000);

            btnEnter.onclick = async () => {
                const uid = userIdInput.value.trim();
                if (!uid) {
                    alert("Please enter a player ID.");
                    return;
                }

                const mode = modeSelect.value;
                let wid = "";
                let seed = null;

                if (mode === "create") {
                    let baseId = worldIdInput.value.trim();
                    if (!baseId) {
                        alert("Please enter a world ID.");
                        return;
                    }
                    const visibility = visibilitySelect.value;
                    if (visibility === "private" && !baseId.startsWith("priv_")) {
                        wid = "priv_" + baseId;
                    } else {
                        wid = baseId;
                    }
                    seed = seedPromptInput.value.trim() || null;
                } else if (mode === "public") {
                    const chosen = worldIdInput.value.trim();
                    if (!chosen) {
                        alert("Click a public world or type its ID.");
                        return;
                    }
                    wid = chosen;
                } else {
                    const privId = privateWorldInput.value.trim();
                    if (!privId) {
                        alert("Enter a private world ID.");
                        return;
                    }
                    wid = privId;
                }

                currentUserId = uid;
                currentWorldId = wid;
                currentSeedPrompt = seed;
                updateSessionPill();
                mapDiv.textContent = "";
                storyDiv.textContent = "";
                appendOutput("Entering world '" + wid + "' as " + uid + "...");
                await sendTurn("ENTER_WORLD", seed);
                await refreshOnlinePlayers();

            };

            btnLeave.onclick = async () => {
                await callLeave();
            };

            btnSend.onclick = async () => {
                const txt = msgInput.value.trim();
                msgInput.value = "";
                const cmd = txt || "WAIT";
                appendUserCommand(cmd);
                await sendTurn(cmd, null);
            };


            msgInput.addEventListener("keydown", (e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    btnSend.click();
                }
            });

        </script>
    </body>
    </html>
    """
    return Response(html, mimetype="text/html")


if __name__ == "__main__":
    # For local dev: http://127.0.0.1:5000
    app.run(host="0.0.0.0", port=5000, debug=True)
