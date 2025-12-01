# dreamweaver/agents/visual_renderer.py

from typing import Optional, List

from dreamweaver.world.models import WorldState, PlayerState, Quest, Region


def _make_bar(value: float, length: int = 10) -> str:
    """
    Turn a 0..1 float into a simple unicode bar, e.g. 0.7 -> ███████░░░
    """
    v = max(0.0, min(1.0, value))
    filled = int(round(v * length))
    empty = length - filled
    return "█" * filled + "░" * empty


def _get_focus_player(world_state: WorldState) -> Optional[PlayerState]:
    """
    For now, just pick the first player. (The orchestrator doesn't pass user_id in.)
    """
    if not world_state.players:
        return None
    # deterministic order
    key = sorted(world_state.players.keys())[0]
    return world_state.players[key]


def _region_for_player(world_state: WorldState, player: PlayerState) -> Optional[Region]:
    return world_state.regions.get(player.location_region_id)


def _region_quests(world_state: WorldState, region: Region) -> List[Quest]:
    quests = []
    for q in world_state.quests.values():
        if region.id in q.related_regions or q.id in region.local_quest_ids:
            quests.append(q)
    return quests


def _other_players_here(world_state: WorldState, player: PlayerState) -> List[PlayerState]:
    here = []
    for p in world_state.players.values():
        if p.user_id == player.user_id:
            continue
        if p.location_region_id == player.location_region_id:
            here.append(p)
    return here


def render_turn(
    world_state: WorldState,
    last_action_type: str,
    special_event: Optional[str],
) -> str:
    """
    Return a rich ASCII "world view" instead of the tiny box.

    This is what shows up on the right side of the UI under #map-output.
    """
    lines: List[str] = []

    world_label = f"{world_state.world_id} (size: {getattr(world_state, 'world_size', 'unknown')})"
    lines.append(f"════════════ WORLD MAP ════════════")
    lines.append(f"World: {world_label}")
    lines.append(f"Tick: {world_state.tick}")
    lines.append("")

    player = _get_focus_player(world_state)
    if player is None:
        lines.append("No players are currently in this world.")
        return "\n".join(lines)

    region = _region_for_player(world_state, player)
    region_name = region.name if region else player.location_region_id
    region_desc = region.description if region else "(unknown region)"

    # Current region
    lines.append(f"You are in: {region_name}")
    lines.append(f"  {region_desc}")
    lines.append("")

    # Paths / exits
    lines.append("Paths from here:")

    if region:
        exits = region.exits or {}

        # If exits is empty but we have neighbors, fall back
        if not exits and getattr(region, "neighbors", None):
            exits = {f"path{i+1}": nb for i, nb in enumerate(region.neighbors)}

        if not exits:
            lines.append("  (No obvious paths. Try exploring or using SEARCH.)")
        else:
            for label, dest_id in exits.items():
                dest_region = world_state.regions.get(dest_id)
                dest_name = dest_region.name if dest_region else dest_id

                flavor = (region.exit_flavor or {}).get(label, "")
                extra = f" – {flavor}" if flavor else ""
                lines.append(f"  [{label}] {dest_name}{extra}")
    else:
        lines.append("  (Region data missing.)")

    lines.append("")

    # Quests in / near this region
    lines.append("Quests tied to this area:")
    if region:
        local_quests = _region_quests(world_state, region)
    else:
        local_quests = []

    if not local_quests:
        lines.append("  (No active quests are anchored here.)")
    else:
        for q in local_quests:
            tag = "MAIN" if "main" in q.title.lower() else "SIDE"
            lines.append(f"  - [{tag}] {q.title} ({q.status})")
            lines.append(f"      {q.summary}")

    lines.append("")

    # World metrics
    m = world_state.metrics
    lines.append("World State:")
    lines.append(f"  Health   { _make_bar(m.world_health) }  ({m.world_health:.2f})")
    lines.append(f"  Chaos    { _make_bar(m.chaos_level) }  ({m.chaos_level:.2f})")
    lines.append(f"  Magic    { _make_bar(m.magic_level) }  ({m.magic_level:.2f})")
    lines.append(f"  Tension  { _make_bar(m.alliance_tension) }  ({m.alliance_tension:.2f})")
    lines.append("")

    # Player stats
    lines.append(f"Your stats ({player.name}, {player.char_class}):")
    for stat_name, val in player.stats.items():
        lines.append(f"  {stat_name.capitalize():8s} { _make_bar(val) }  ({val:.2f})")
    lines.append("")

    # Other players nearby
    others_here = _other_players_here(world_state, player)
    lines.append("Players in this region:")
    if not others_here:
        lines.append("  (You are alone here.)")
    else:
        for p in others_here:
            lines.append(f"  - {p.name} ({p.char_class})")

    lines.append("")

    # Optional special event banner
    if special_event:
        lines.append(f"!!! SPECIAL EVENT: {special_event} !!!")

    return "\n".join(lines)
