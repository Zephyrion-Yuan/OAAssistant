"""personalize node — fill empty intent slots from a static user profile.

Runs between understand and check_slot. This is the Stage-2 seam for the
Stage-3 personalization/memory feature: defaults (factory / WBS / common stock
locations / department) travel with the user and pre-fill slots so the agent
asks less. No-op when there is no profile. LLM-free and deterministic.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..config import get_settings
from ..schemas import Profile
from .. import store
from ._common import append_history

# intent slot  <-  profile default
_SLOT_DEFAULTS = {
    "factory_code": "default_factory_code",
    "movement_type": "default_movement_type",
    "wbs": "default_wbs",
    "transfer_out_stock_location_name": "default_transfer_out_stock_location_name",
    "transfer_out_stock_location_sap": "default_transfer_out_stock_location_sap",
    "transfer_in_stock_location_name": "default_transfer_in_stock_location_name",
    "transfer_in_stock_location_sap": "default_transfer_in_stock_location_sap",
}


def _load_profile(state: Dict[str, Any]) -> Optional[Profile]:
    raw = state.get("profile")
    if raw:
        return Profile.model_validate(raw)
    user_id = state.get("user_id")
    if user_id:
        return store.get_profile(get_settings().store_path, user_id)
    return None


def personalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    profile = _load_profile(state)
    if profile is None:
        return {"history": append_history(state, {"node": "personalize", "applied": []})}

    intent = dict(state.get("intent") or {})
    applied = []
    for slot, default_field in _SLOT_DEFAULTS.items():
        if not intent.get(slot):
            value = getattr(profile, default_field, None)
            if value:
                intent[slot] = value
                applied.append(slot)

    history = append_history(state, {"node": "personalize", "user_id": profile.user_id, "applied": applied})
    return {"intent": intent, "profile": profile.model_dump(), "history": history}
