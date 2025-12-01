import json
import time
import asyncio
from typing import List, Tuple, Optional, Dict

from google import genai
from google.genai import types

from dreamweaver.config import GOOGLE_API_KEY, MODEL_NAME, SESSION_TIMEOUT_SECONDS
from dreamweaver.world.models import (
    WorldState,
    WorldMetrics,
    Region,
    Character,
    PlayerState,
    Event,
    Action,
    Quest,
)
from dreamweaver.services.storage import load_world, save_world
from dreamweaver.agents.command_interpreter import command_interpreter
from dreamweaver.agents.world_architect import world_architect
from dreamweaver.agents.event_engine import event_engine
from dreamweaver.agents.story_conductor import story_conductor
from dreamweaver.agents.visual_renderer import render_turn
from dreamweaver.agents.dialogue_weaver import dialogue_weaver
from dreamweaver.agents.quest_master import quest_master
from dreamweaver.world.models import WorldState

_client = genai.Client(api_key=GOOGLE_API_KEY)


async def _call_agent_json(instruction: str, input_obj: dict) -> dict:
    """
    Call Gemini with a given instruction and JSON-like input,
    expecting a pure-JSON response that we can json.loads().
    Uses the sync generate_content() under the hood via run_in_executor.
    """
    text = (
        "You are an internal sub-agent in the DreamWeaver system.\n"
        "Follow the SYSTEM INSTRUCTION below and respond with ONLY valid JSON. "
        "No explanations, no extra text.\n\n"
        "SYSTEM INSTRUCTION:\n"
        f"{instruction}\n\n"
        "INPUT JSON:\n"
        f"{json.dumps(input_obj, ensure_ascii=False, indent=2)}\n\n"
        "Return ONLY JSON."
    )
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=text)],
    )

    loop = asyncio.get_event_loop()

    def _call_sync():
        return _client.models.generate_content(
            model=MODEL_NAME,
            contents=[content],
        )

    resp = await loop.run_in_executor(None, _call_sync)

    out_text = ""
    if hasattr(resp, "text") and resp.text:
        out_text = resp.text
    else:
        if getattr(resp, "candidates", None):
            cand = resp.candidates[0]
            if cand.content.parts:
                part = cand.content.parts[0]
                if hasattr(part, "text") and part.text:
                    out_text = part.text

    out_text = out_text.strip()
    if out_text.startswith("```"):
        out_text = out_text.strip("`")
        if out_text.lower().startswith("json"):
            out_text = out_text[4:].strip()

    try:
        return json.loads(out_text)
    except Exception:
        return {}


class DreamWeaverOrchestrator:
    """
    Orchestrates the full multi-agent pipeline for a single user turn.
    This version does NOT use google-adk Runner.
    It calls Gemini directly with each agent's instruction.
    """

    def __init__(self):
        pass
    
    
    def _apply_stat_changes(self, player: PlayerState, deltas: Dict[str, float]) -> None:
        for name, delta in (deltas or {}).items():
            old = player.stats.get(name, 0.5)
            try:
                new = max(0.0, min(1.0, old + float(delta)))
            except Exception:
                new = old
            player.stats[name] = new

    async def handle_turn(
        self,
        user_id: str,
        world_id: str,
        user_message: str,
        seed_prompt_if_new: Optional[str] = None,
    ) -> str:
        world_state = await self._load_or_init_world_state(
            user_id=user_id,
            world_id=world_id,
            seed_prompt_if_new=seed_prompt_if_new or user_message or "Create a new world."
        )

        # Prune any players that have been idle too long
        self._prune_inactive_players(world_state)

        # Mark this user as active *now*
        world_state.active_players[user_id] = time.time()
        world_state.is_open = True
        
        # Log this command into shared history (for Recent actions)
        cmd_text = (user_message or "WAIT").strip()
        if cmd_text:
            entry = f"{user_id}: {cmd_text}"
            world_state.history_summaries.append(entry)
            # keep only the last 50 commands
            if len(world_state.history_summaries) > 50:
                world_state.history_summaries = world_state.history_summaries[-50:]


        # 1) Command Interpreter
        interpreter_input = {
            "user_message": user_message,
            "world_summary": self._summarize_world(world_state),
        }
        ci_result = await _call_agent_json(
            instruction=command_interpreter.instruction,
            input_obj=interpreter_input,
        )
        actions = self._parse_actions(ci_result)

        # 2) World update phase
        world_state, last_action_type, special_event, extra_notes = await self._update_world(
            world_state, user_id, actions
        )

                # 3) Story Conductor
        story_input = {
            "world_summary": self._summarize_world(world_state),
            "last_events": [e.__dict__ for e in world_state.last_events],
            "actions": [a.__dict__ for a in actions],
        }
        
        sc_result = await _call_agent_json(
            instruction=story_conductor.instruction,
            input_obj=story_input,
        )
        narration = sc_result.get("narration", "")
        suggested_actions = sc_result.get("suggested_actions", [])

        # 4) Visual rendering (ASCII map only)
        visual_block = render_turn(world_state, last_action_type, special_event)

        # 5) Build story-only text (no map)
        story_text = narration
        if extra_notes.strip():
            story_text += f"\n\n{extra_notes}"

        # Recent commands from all players
        if world_state.history_summaries:
            recent = world_state.history_summaries[-10:]
            story_text += "\n\nRecent actions:\n"
            for line in recent:
                story_text += f"- {line}\n"

        # Suggested actions
        story_text += "\n\nSuggested actions:\n"
        for i, act in enumerate(suggested_actions, start=1):
            story_text += f"  {i}) {act}\n"
        story_text += "Or type your own action."

        # Store story-only text so /api/state can reuse it
        world_state.last_scene_text = story_text

        # --- story arc logging (shared across all users in the world) ---
        if not hasattr(world_state, "story_log") or world_state.story_log is None:
            world_state.story_log = []

        world_state.story_log.append({
            "tick": world_state.tick,
            "user_id": user_id,
            "message": user_message,
            "text": story_text,      # story-only, no map
            "timestamp": time.time(),
        })
        # keep last 100 turns
        if len(world_state.story_log) > 100:
            world_state.story_log = world_state.story_log[-100:]

        # 6) Save updated world
        save_world(world_state)

        # Return combined string (map + story) for compatibility
        final = f"{visual_block}\n\n{story_text}"
        return final

    
    
    async def apply_action_only(
        self,
        user_id: str,
        world_id: str,
        user_message: str,
        seed_prompt_if_new: Optional[str] = None,
    ) -> None:
        """
        Apply a user action and update the world state without generating
        narration or a rendered turn. Used by /api/action for live-ish updates.
        """
        world_state = await self._load_or_init_world_state(
            user_id=user_id,
            world_id=world_id,
            seed_prompt_if_new=seed_prompt_if_new or user_message or "Create a new world.",
        )

        # Prune any players that have been idle too long
        self._prune_inactive_players(world_state)

        # Mark this user as active *now*
        world_state.active_players[user_id] = time.time()
        world_state.is_open = True

        # Log this command into shared history
        cmd_text = (user_message or "WAIT").strip()
        if cmd_text:
            entry = f"{user_id}: {cmd_text}"
            world_state.history_summaries.append(entry)
            if len(world_state.history_summaries) > 50:
                world_state.history_summaries = world_state.history_summaries[-50:]

        # 1) Command Interpreter
        interpreter_input = {
            "user_message": user_message,
            "world_summary": self._summarize_world(world_state),
        }
        ci_result = await _call_agent_json(
            instruction=command_interpreter.instruction,
            input_obj=interpreter_input,
        )
        actions = self._parse_actions(ci_result)

        # 2) World update phase (same helper as handle_turn)
        world_state, last_action_type, special_event, extra_notes = await self._update_world(
            world_state, user_id, actions
        )

        # We skip Story Conductor + Visual Renderer here.
        # The frontend will fetch the current state via get_state_view().
        save_world(world_state)
        
        
    async def get_state_view(
        self,
        user_id: str,
        world_id: str,
    ) -> dict:
        """
        Return a snapshot of the current world view for a user:
        {
          "visual": "<ASCII map>",
          "story": "<story text without map>"
        }
        Used by /api/state and /api/turn.
        """
        world_state = load_world(world_id)
        if world_state is None:
            return {
                "visual": "",
                "story": "This world does not exist yet. Create it by sending an action."
            }

        # Best-effort prune inactive players; we don't save here
        self._prune_inactive_players(world_state)

        # Render the current world as ASCII map
        visual_block = render_turn(world_state, last_action_type="LOOK", special_event=None)

        # Story-only text (already includes recent actions & suggestions)
        story = world_state.last_scene_text or ""

        return {
            "visual": visual_block,
            "story": story,
        }


    async def _load_or_init_world_state(
        self,
        user_id: str,
        world_id: str,
        seed_prompt_if_new: str,
    ) -> WorldState:
        ws = load_world(world_id)
        
        if ws is not None:
            # Add seed_prompt field if missing (for backward compatibility)
            if not hasattr(ws, "seed_prompt"):
                ws.seed_prompt = seed_prompt_if_new or "A mysterious world."
                
            # Patch old worlds missing chat_log
            if not hasattr(ws, "chat_log"):
                ws.chat_log = []
                
            # Patch old worlds missing story_log
            if not hasattr(ws, "story_log"):
                ws.story_log = []
        
        if ws is None:
            architect_input = {
                "mode": "NEW_WORLD",
                "seed_prompt": seed_prompt_if_new,
            }
            wa_result = await _call_agent_json(
                instruction=world_architect.instruction,
                input_obj=architect_input,
            )

            regions_dict = {}
            regions_list = wa_result.get("regions", [])
            if not regions_list:
                regions_list = [{
                    "id": "glass_whale_bay",
                    "name": "Glass Whale Bay",
                    "type": "bay",
                    "description": "A floating city built on the back of a shimmering glass whale.",
                    "neighbors": [],
                }]

            # inside _load_or_init_world_state, when building regions_dict

            for r in regions_list:
                neighbors = r.get("neighbors", [])
                # simple label: "path1", "path2", ...
                exits = {f"path{i+1}": nb for i, nb in enumerate(neighbors)}

                region = Region(
                    id=r["id"],
                    name=r.get("name", r["id"]),
                    description=r.get("description", ""),
                    type=r.get("type", "unknown"),
                    neighbors=neighbors,
                    biome=r.get("biome", "plains"),
                    known_to_player=True,
                    exits=exits,
                    local_quest_ids=r.get("local_quest_ids", []),
                    exit_flavor=r.get("exit_flavor", {}),
                )
                regions_dict[region.id] = region


            first_region_id = regions_list[0]["id"]

            metrics = WorldMetrics()
            history_summaries = wa_result.get("history_notes", [])

            ws = WorldState(
                world_id=world_id,
                seed_prompt=seed_prompt_if_new,
                tick=0,
                regions=regions_dict,
                characters={},
                players={},
                quests={},
                metrics=metrics,
                history_summaries=history_summaries,
                last_events=[],
                active_players={},
                last_scene_text=None,
                chat_log=[],
                story_log=[],
                world_size=wa_result.get("world_size", "medium"),
            )
            
            # --- NEW: load starter_quests into ws.quests if present ---
            starter_quests = wa_result.get("starter_quests", [])
            for q in starter_quests:
                try:
                    qid = q["id"]
                    quest_obj = Quest(
                        id=qid,
                        title=q.get("title", qid),
                        status=q.get("status", "open"),
                        summary=q.get("summary", ""),
                        related_regions=q.get("related_regions", []),
                        related_characters=q.get("related_characters", []),
                    )
                    ws.quests[qid] = quest_obj
                except Exception:
                    continue


            for c in wa_result.get("starter_characters", []):
                char = Character(
                    id=c["id"],
                    name=c.get("name", c["id"]),
                    role=c.get("role", "npc"),
                    location_region_id=c.get("location_region_id", first_region_id),
                    mood=c.get("mood", "neutral"),
                    loyalty=float(c.get("loyalty", 0.5)),
                    traits=c.get("traits", []),
                    memories=c.get("memories", []),
                )
                ws.characters[char.id] = char

        # Ensure player exists
        if user_id not in ws.players:
            first_region_id = next(iter(ws.regions.keys()))
            player = PlayerState(
                user_id=user_id,
                character_id=f"{user_id}_char",
                name=user_id,
                char_class="wanderer",
                location_region_id=first_region_id,
            )
            ws.players[user_id] = player

        return ws

    def _summarize_world(self, world_state: WorldState) -> str:
        player = next(iter(world_state.players.values()), None)
        if not player:
            return "No players in this world yet."

        region = world_state.regions.get(player.location_region_id)
        region_name = region.name if region else player.location_region_id

        metrics = world_state.metrics
        metric_line = (
            f"Metrics: health={metrics.world_health:.2f}, chaos={metrics.chaos_level:.2f}, "
            f"magic={metrics.magic_level:.2f}, tension={metrics.alliance_tension:.2f}."
        )

        known_regions = list(world_state.regions.values())[:5]
        region_names = ", ".join(r.name for r in known_regions)

        other_players = [
            p for p in world_state.players.values()
            if p.user_id != player.user_id
        ]
        if other_players:
            others = []
            for p in other_players:
                loc = p.location_region_id
                if loc in world_state.regions:
                    loc_name = world_state.regions[loc].name
                else:
                    loc_name = loc
                others.append(f"{p.name} ({p.char_class}) at {loc_name}")
            other_players_str = ", ".join(others)
        else:
            other_players_str = "none"

        history_snippets = " | ".join(world_state.history_summaries[-3:])

        return (
            f"Player: {player.name} ({player.char_class}) at {region_name}.\n"
            f"{metric_line}\n"
            f"Known regions: {region_names}.\n"
            f"Other players: {other_players_str}.\n"
            f"Recent history: {history_snippets if history_snippets else 'none'}.\n"
        )

    def _parse_actions(self, ci_result) -> List[Action]:
        actions = []
        raw_actions = ci_result.get("actions", [])
        for a in raw_actions:
            actions.append(
                Action(
                    type=a.get("type", "WAIT"),
                    target_region_id=a.get("target_region_id"),
                    target_character_id=a.get("target_character_id"),
                    params=a.get("params", {}) or {},
                )
            )
        if not actions:
            actions.append(Action(type="WAIT"))
        return actions

    async def leave_world(self, user_id: str, world_id: str) -> None:
        """
        Mark a user as having left the world. The world stays 'open' as long
        as at least one active player remains (and is within the timeout).
        When the last player leaves or times out, we mark is_open = False.
        """
        ws = load_world(world_id)
        if ws is None:
            return

        # First, prune anyone who has timed out
        self._prune_inactive_players(ws)

        # Then remove this user explicitly
        if user_id in ws.active_players:
            del ws.active_players[user_id]

        # If no one is active now, close the world
        if not ws.active_players:
            ws.is_open = False

        save_world(ws)

    async def _update_world(
        self,
        world_state: WorldState,
        user_id: str,
        actions: List[Action],
    ) -> Tuple[WorldState, str, Optional[str], str]:
        last_action_type = actions[-1].type if actions else "WAIT"
        special_event = None
        extra_notes_parts = []

        num_ticks = 1
        player = world_state.players[user_id]

        # --- 1) Immediate action effects + TALK handling ---
        talk_snippets = []
        for action in actions:
            if action.type == "MOVE" and action.target_region_id:
                if action.target_region_id in world_state.regions:
                    player.location_region_id = action.target_region_id

            elif action.type == "FAST_FORWARD":
                try:
                    days = int(action.params.get("days", 1))
                except Exception:
                    days = 1
                num_ticks = max(1, days)

            elif action.type == "TALK":
                # ---------------------------------------------------
                # 1) First: is this TALK aimed at another *real player*?
                # ---------------------------------------------------
                target_player = None
                if action.target_character_id:
                    for p in world_state.players.values():
                        # Match against player character_id, display name, or user_id
                        if action.target_character_id in (p.character_id, p.name, p.user_id):
                            target_player = p
                            break

                if target_player is not None:
                    # Do NOT puppet real players as NPCs.
                    if target_player.user_id in world_state.active_players:
                        snippet = (
                            f"You address {target_player.name} directly. "
                            "They are here and can respond on their own turn."
                        )
                    else:
                        snippet = (
                            f"You call out for {target_player.name}, but they don't seem to be around right now. "
                            "Maybe focus on the world and its quests until they return."
                        )

                    talk_snippets.append(snippet)

                    # Optional: also mirror this into world chat so it's visible to everyone
                    # (only if your WorldState has chat_log)
                    if hasattr(world_state, "chat_log") and isinstance(world_state.chat_log, list):
                        line = action.params.get("utterance") if isinstance(action.params, dict) else None
                        if line:
                            world_state.chat_log.append(f"{player.name} → {target_player.name}: {line}")
                            if len(world_state.chat_log) > 200:
                                world_state.chat_log = world_state.chat_log[-200:]

                    # Skip NPC dialogue_weaver for real players
                    continue

                # ---------------------------------------------------
                # 2) Otherwise: normal NPC TALK path (same as before)
                # ---------------------------------------------------
                npc = None
                if action.target_character_id and action.target_character_id in world_state.characters:
                    npc = world_state.characters[action.target_character_id]

                dw_input = {
                    "world_summary": self._summarize_world(world_state),
                    "player": {
                        "name": player.name,
                        "char_class": player.char_class,
                        "location_region_id": player.location_region_id,
                    },
                    "npc": None,
                    "action": {
                        "params": action.params,
                    },
                }

                if npc is not None:
                    dw_input["npc"] = {
                        "id": npc.id,
                        "name": npc.name,
                        "role": npc.role,
                        "mood": npc.mood,
                        "loyalty": npc.loyalty,
                    }

                dw_result = await _call_agent_json(
                    instruction=dialogue_weaver.instruction,
                    input_obj=dw_input,
                )

                dialogue_text = dw_result.get("dialogue", "")
                npc_reaction = dw_result.get("npc_reaction", "")
                world_effects = dw_result.get("world_effects", {}) or {}

                if dialogue_text:
                    snippet = "Conversation:\n" + dialogue_text
                    if npc_reaction:
                        snippet += "\n\nNPC reaction: " + npc_reaction
                    talk_snippets.append(snippet)

                if npc is not None:
                    if "npc_mood" in world_effects:
                        npc.mood = world_effects["npc_mood"]
                    if "npc_loyalty_delta" in world_effects:
                        try:
                            delta = float(world_effects["npc_loyalty_delta"])
                            npc.loyalty = max(0.0, min(1.0, npc.loyalty + delta))
                        except Exception:
                            pass

                ps_delta = world_effects.get("player_stats_delta", {}) or {}
                self._apply_stat_changes(player, ps_delta)



        if talk_snippets:
            extra_notes_parts.append("\n\n".join(talk_snippets))

        # --- 2) Event engine (time passage) ---
        ee_input = {
            "world_summary": self._summarize_world(world_state),
            "actions": [a.__dict__ for a in actions],
            "current_tick": world_state.tick,
            "num_ticks": num_ticks,
        }
        ee_result = await _call_agent_json(
            instruction=event_engine.instruction,
            input_obj=ee_input,
        )

        metrics_delta = ee_result.get("metrics_delta", {})
        m = world_state.metrics
        m.world_health = max(0.0, min(1.0, m.world_health + float(metrics_delta.get("world_health", 0.0))))
        m.chaos_level = max(0.0, min(1.0, m.chaos_level + float(metrics_delta.get("chaos_level", 0.0))))
        m.magic_level = max(0.0, min(1.0, m.magic_level + float(metrics_delta.get("magic_level", 0.0))))
        m.alliance_tension = max(0.0, min(1.0, m.alliance_tension + float(metrics_delta.get("alliance_tension", 0.0))))
        # NEW: allow event_engine to tweak player stats too
        ee_stats_delta = ee_result.get("player_stats_delta", {})
        self._apply_stat_changes(player, ee_stats_delta)


        world_state.last_events = []
        for e in ee_result.get("events", []):
            ev = Event(
                id=e["id"],
                type=e.get("type", "generic"),
                description=e.get("description", ""),
                tick=world_state.tick + num_ticks,
                affected_regions=e.get("affected_regions", []),
                impact=e.get("impact", {}),
            )
            world_state.last_events.append(ev)
            if ev.type in {"dragon_hatching", "boss_battle"}:
                special_event = ev.type

        world_state.tick += num_ticks

        # --- 3) Quest master (quests + quest notifications) ---
        qm_input = {
            "world_summary": self._summarize_world(world_state),
            "last_events": [e.__dict__ for e in world_state.last_events],
            "actions": [a.__dict__ for a in actions],
            "existing_quests": [q.__dict__ for q in world_state.quests.values()],
            "world_size": getattr(world_state, "world_size", "medium"),
        }
        qm_result = await _call_agent_json(
            instruction=quest_master.instruction,
            input_obj=qm_input,
        )

        quests_out = qm_result.get("quests", [])
        notifications = qm_result.get("notifications", []) or []

        if quests_out:
            new_quests = {}
            for q in quests_out:
                try:
                    qid = q["id"]
                    quest_obj = Quest(
                        id=qid,
                        title=q.get("title", qid),
                        status=q.get("status", "open"),
                        summary=q.get("summary", ""),
                        related_regions=q.get("related_regions", []),
                        related_characters=q.get("related_characters", []),
                    )
                    new_quests[qid] = quest_obj
                except Exception:
                    continue
            if new_quests:
                world_state.quests = new_quests

        if notifications:
            note_block = "Quest updates:\n" + "\n".join(f"- {n}" for n in notifications)
            extra_notes_parts.append(note_block)

        # ✅ NEW: allow quest_master to tweak stats, but qm_result is ALWAYS defined
        qm_stats_delta = qm_result.get("player_stats_delta", {}) if isinstance(qm_result, dict) else {}
        self._apply_stat_changes(player, qm_stats_delta)

        extra_notes = "\n\n".join(extra_notes_parts) if extra_notes_parts else ""

        return world_state, last_action_type, special_event, extra_notes


    def _prune_inactive_players(self, world_state: WorldState) -> None:
        """
        Remove players from active_players if they have been idle for longer
        than SESSION_TIMEOUT_SECONDS. If no active players remain, mark
        world_state.is_open = False.
        """
        now = time.time()
        to_remove = []

        for uid, last_ts in world_state.active_players.items():
            try:
                if now - float(last_ts) > SESSION_TIMEOUT_SECONDS:
                    to_remove.append(uid)
            except Exception:
                to_remove.append(uid)

        for uid in to_remove:
            del world_state.active_players[uid]

        if not world_state.active_players:
            world_state.is_open = False
