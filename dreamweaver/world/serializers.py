from dataclasses import asdict
from typing import Dict, Any

from .models import (
    WorldState,
    Region,
    Character,
    PlayerState,
    Quest,
    Event,
    WorldMetrics,
)


def world_state_to_dict(ws: WorldState) -> Dict[str, Any]:
    """
    Convert WorldState dataclass (with nested dataclasses) into a plain dict
    suitable for JSON storage.
    """
    return asdict(ws)


def world_state_from_dict(data: Dict[str, Any]) -> WorldState:
    """
    Reconstruct WorldState from a dict loaded from JSON.
    Handles older worlds that may not have new fields like seed_prompt,
    chat_log, story_log, world_size, or is_open.
    """

    # Rebuild regions
    regions = {
        rid: Region(**r)
        for rid, r in data.get("regions", {}).items()
    }

    # Rebuild characters
    characters = {
        cid: Character(**c)
        for cid, c in data.get("characters", {}).items()
    }

    # Rebuild players
    players = {
        uid: PlayerState(**p)
        for uid, p in data.get("players", {}).items()
    }

    # Rebuild quests
    quests = {
        qid: Quest(**q)
        for qid, q in data.get("quests", {}).items()
    }

    # Metrics
    metrics = WorldMetrics(**data.get("metrics", {}))

    # Last events
    last_events_list = [
        Event(**e) for e in data.get("last_events", [])
    ]

    # PATCH: handle missing fields for older saved worlds
    seed_prompt = data.get("seed_prompt", "A mysterious world.")
    chat_log = data.get("chat_log", [])
    story_log = data.get("story_log", [])
    last_scene_text = data.get("last_scene_text")
    is_open = data.get("is_open", True)
    world_size = data.get("world_size", "medium")

    return WorldState(
        world_id=data["world_id"],
        seed_prompt=seed_prompt,
        tick=data.get("tick", 0),
        regions=regions,
        characters=characters,
        players=players,
        quests=quests,
        metrics=metrics,
        history_summaries=data.get("history_summaries", []),
        last_events=last_events_list,
        active_players=data.get("active_players", {}),
        last_scene_text=last_scene_text,
        world_size=world_size,
        chat_log=chat_log,
        story_log=story_log,
        is_open=is_open,
    )
