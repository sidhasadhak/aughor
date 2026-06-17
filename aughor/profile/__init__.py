"""Business/Industry Profile — the keystone for industry-aware intelligence.

A per-connection inferred artifact that captures WHAT KIND of business a dataset
represents (industry, business model) and WHICH metrics/questions matter for that
vertical. Every downstream layer (explorer angles today; metrics, KB retrieval,
briefing, charts later) reads from this single source of truth instead of
re-deriving generic, ecommerce-biased context ad hoc.
"""
from aughor.profile.models import BusinessProfile, NorthStarMetric
from aughor.profile.infer import infer_business_profile, get_or_infer
from aughor.profile import store

__all__ = [
    "BusinessProfile",
    "NorthStarMetric",
    "infer_business_profile",
    "get_or_infer",
    "store",
]
