import os
import json
from typing import Optional, List

from dreamweaver.config import BASE_STORAGE_DIR
from dreamweaver.world.models import WorldState
from dreamweaver.world.serializers import world_state_to_dict, world_state_from_dict


def _world_path(world_id: str) -> str:
    return os.path.join(BASE_STORAGE_DIR, f"{world_id}.json")


def list_world_ids() -> List[str]:
    """
    Return a list of all world_ids currently stored.
    """
    if not os.path.exists(BASE_STORAGE_DIR):
        return []
    files = os.listdir(BASE_STORAGE_DIR)
    world_ids = []
    for f in files:
        if f.endswith(".json"):
            world_ids.append(f[:-5])  # strip .json
    return sorted(world_ids)


def load_world(world_id: str) -> Optional[WorldState]:
    """
    Load a WorldState from disk if it exists; otherwise return None.
    """
    path = _world_path(world_id)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    return world_state_from_dict(data)


def save_world(world_state: WorldState) -> None:
    """
    Save a WorldState to disk as JSON.
    """
    os.makedirs(BASE_STORAGE_DIR, exist_ok=True)
    path = _world_path(world_state.world_id)
    with open(path, "w") as f:
        json.dump(world_state_to_dict(world_state), f)
