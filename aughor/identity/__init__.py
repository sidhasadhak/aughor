"""Identity resolution — a door-supplied principal → a stable attribution key."""
from aughor.identity.models import UNATTRIBUTED, Identity, parse_ref
from aughor.identity.resolver import attribution_key, resolve

__all__ = ["UNATTRIBUTED", "Identity", "parse_ref", "resolve", "attribution_key"]
