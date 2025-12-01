# 🌙 DreamWeaver  
### A Multi-Agent, Gemini-Powered Interactive Story Engine

DreamWeaver is a multi-agent AI narrative engine that generates a persistent, evolving fantasy world based on player actions. Each turn, cooperating LLM-powered agents update regions, characters, quests, and world metrics—then produce a cinematic story moment and an ASCII-rendered world view.

This project is built as part of the Google AI Agents Capstone, demonstrating agent orchestration, structured AI output, memory, and generative reasoning using Gemini.

DreamWeaver is designed primarily as a single-player persistent world, but it supports multiple users sharing the same world. A small multiplayer demo is included in the kaggle notebbok for illustration only and is not required for core functionality.

---

## ✨ Features

### 🧠 Multi-Agent Architecture  
DreamWeaver simulates an AI storytelling team with specialized LLM-powered agents:

- Command Interpreter – Parses user intent  
- World Architect – Updates regions, exits, and world structure  
- Event Engine – Simulates dynamic events  
- Quest Master – Creates and updates quests  
- Dialogue Weaver – Generates NPC interactions  
- Story Conductor – Cinematic narration every turn  
- Visual Renderer – ASCII map + stat bars  
- Storage Service – Persistent world state (JSON)

### 🔄 Persistent World State  
The world evolves over time:

- Regions retain descriptions and paths  
- NPCs remember moods & locations  
- Quests update & progress  
- Stats change (chaos, magic, tension, health)  
- Player choices persist  

### 🔮 Powered by Gemini  
All generative steps are handled by Gemini with strict JSON prompting for deterministic structure.

---

## 📂 Project Structure

```text
dreamweaver_project/
│
├── dreamweaver/
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── world_architect.py
│   │   ├── event_engine.py
│   │   ├── story_conductor.py
│   │   ├── command_interpreter.py
│   │   ├── dialogue_weaver.py
│   │   └── quest_master.py
│   │
│   ├── world/
│   │   ├── models.py
│   │   └── utils.py
│   │
│   ├── services/
│   │   ├── storage.py
│   │   └── rendering.py
│   │
│   └── config.py
│
├── storage/                     (runtime world-state, ignored by Git)
├── flask_app.py                 (optional Flask API server)
├── requirements.txt
└── README.md
```
---

# 🧭 How to Run DreamWeaver (Two Methods)

DreamWeaver can run in two environments:  
Locally via Flask API, or in a Kaggle Notebook.

---

## 🔹 Method 1 — Run Locally via Flask API

1. Install dependencies  
```text
pip install -r requirements.txt
```
2. Set your Gemini API key  
Mac/Linux:  
```text
export GOOGLE_API_KEY="your-key-here"  
```
Windows:  
```text
setx GOOGLE_API_KEY "your-key-here"
```

3. Start the Flask server  
```text
python flask_app.py
```

You should see:  
* Running on http://127.0.0.1:5000/

4. Send a POST request (ctrl+click on link) 
Endpoint:  
http://127.0.0.1:5000/turn

Example JSON body:
{
  "user_id": "lexi",
  "world_id": "demo_world",
  "message": "explore the area"
}

Best For:
- Local development  
- Integrating UI/frontends  
- Building API-based games  
- Deployment workflows  
- Long-term campaigns
- Multiplayers interacting with one/multiple world
---

## 🔹 Method 2 — Run in Kaggle Notebook (Recommended for Judges)

1. Load project files:
```
PROJECT_ROOT = "/kaggle/input/dreamweaver_project"
sys.path.append(PROJECT_ROOT)
```

2. Load Gemini key from Kaggle Secrets:
```
from kaggle_secrets import UserSecretsClient
import os
GOOGLE_API_KEY = UserSecretsClient().get_secret("GOOGLE_API_KEY")
os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY
```

3. Initialize orchestrator:
```
from dreamweaver.agents.orchestrator import DreamWeaverOrchestrator
import nest_asyncio
nest_asyncio.apply()
orch = DreamWeaverOrchestrator()
```

4. Run a story turn:
```
await orch.handle_turn(
    user_id="lexi",
    world_id="demo_world",
    user_message="explore the area",
    seed_prompt_if_new="Create a small world."
)
```

Best For:
- Clean demo  
- Zero installation  
- Perfect for reviewers
- Testing multiple scenarios quickly

---

☁️ Kaggle Persistence Note (Important)

Kaggle has no persistent storage between sessions.

DreamWeaver saves worlds into:
```
/kaggle/working/dreamweaver/storage/
```
This folder is deleted every time the notebook runtime restarts.

✔ Kaggle = Always fresh world

✔ Local machine = Persistent evolving world

This is intentional for reproducible evaluation.

If you want persistent worlds, run locally.

A clearly documented section in the notebook explains this behavior.

---

## 🧪 Kaggle Notebook Demo

The demo includes:
- Model setup + Gemini key
- Loading the DreamWeaver project  
- Running multiple story turns  
- ASCII visual map output  
- Quests + events + NPC conversations  
- World-state JSON snapshot for transparency
- Optional multiplayer example

Kaggle notebook: https://www.kaggle.com/code/alekyaramani/dreamweaver

---

## 🚀 Running Directly in Python (Manual)
```
from dreamweaver.agents.orchestrator import DreamWeaverOrchestrator
orch = DreamWeaverOrchestrator()

await orch.handle_turn(
    user_id="demo",
    world_id="world1",
    user_message="explore the area",
    seed_prompt_if_new="Create a small demo world."
)
```

---

## 🛠 Capstone Concepts Demonstrated

DreamWeaver fulfills multiple required features:

- Multi-Agent System (6+ interconnected agents)  
- Sequential orchestration pipeline  
- Custom tools (storage, rendering, interpreter)  
- Long-term memory (persistent world JSON files)  
- Context engineering (strict JSON prompting)  
- Observability (logs + monitored world state)  
- Gemini integration  
- Optional deployment via Flask API  

---

## 📜 License
Educational and demonstration use only (Google AI Agents Capstone).

---

## 💬 Contact
Alekya (Lexi)  
GitHub: https://github.com/Lexi-cod

---

# ⭐ Ready for Review

DreamWeaver includes:
- Full multi-agent engine  
- Persistent world simulation  
- Dynamic quests & events  
- Cinematic narration  
- Kaggle demo notebook  
- Local API mode  
- Clean documentation  

This repository is fully prepared for capstone evaluation.  
Enjoy exploring the world of DreamWeaver! 🌙✨

