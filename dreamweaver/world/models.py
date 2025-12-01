from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


# dreamweaver/world/models.py

@dataclass
class Region:
    id: str
    name: str
    description: str

    # new “world flavor” fields
    biome: str = "plains"

    # legacy fields that your architect code still uses
    type: str = "unknown"
    neighbors: List[str] = field(default_factory=list)
    known_to_player: bool = True

    # direction/label -> region_id (you can later use "N", "S", etc.)
    exits: Dict[str, str] = field(default_factory=dict)

    # quest ids that are “local” here
    local_quest_ids: List[str] = field(default_factory=list)

    # optional path flavor: direction/label -> short text
    exit_flavor: Dict[str, str] = field(default_factory=dict)




@dataclass
class Character:
    id: str
    name: str
    role: str
    location_region_id: str
    mood: str = "neutral"
    loyalty: float = 0.5
    traits: List[str] = field(default_factory=list)
    memories: List[str] = field(default_factory=list)


@dataclass
class PlayerState:
    user_id: str          # real user ID (e.g., "lexi")
    character_id: str     # unique within this world
    name: str             # display name in this world
    char_class: str
    location_region_id: str
    stats: Dict[str, float] = field(default_factory=lambda: {
        "courage": 0.5,
        "empathy": 0.5,
        "cunning": 0.5,
    })
    reputation: Dict[str, float] = field(default_factory=dict)
    goals: List[str] = field(default_factory=list)
    inventory: List[str] = field(default_factory=list)


@dataclass
class WorldMetrics:
    world_health: float = 0.7
    chaos_level: float = 0.3
    magic_level: float = 0.4
    alliance_tension: float = 0.2

@dataclass
class Quest:
    id: str
    title: str
    status: str  # "open", "completed", "failed"
    summary: str
    related_regions: List[str] = field(default_factory=list)
    related_characters: List[str] = field(default_factory=list)

    # NEW: optional “backend” info for evaluation
    answer_type: str = "none"        # e.g. "riddle", "location", "item", "choice"
    correct_answers: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)



@dataclass
class Event:
    id: str
    type: str
    description: str
    tick: int
    affected_regions: List[str] = field(default_factory=list)
    impact: Dict[str, float] = field(default_factory=dict)


@dataclass
class Action:
    type: str
    target_region_id: Optional[str] = None
    target_character_id: Optional[str] = None
    params: Dict[str, str] = field(default_factory=dict)


@dataclass
class WorldState:
    world_id: str
    seed_prompt: str
    tick: int
    regions: Dict[str, Region]
    characters: Dict[str, Character]
    players: Dict[str, PlayerState]
    quests: Dict[str, Quest]
    metrics: WorldMetrics
    history_summaries: List[str]
    last_events: List[Event]
    active_players: Dict[str, float]

    # last rendered story text (without map)
    last_scene_text: Optional[str] = None

    # high-level world metadata
    world_size: str = "medium"

    # per-world chat log, newest last
    chat_log: List[str] = field(default_factory=list)

    # NEW: story timeline used by orchestrator.story_log.append(...)
    # each entry is a dict: {tick, user_id, message, text, timestamp}
    story_log: List[Dict[str, Any]] = field(default_factory=list)

    # whether there are any active players right now
    is_open: bool = False
