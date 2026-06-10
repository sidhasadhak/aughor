"""The Aughor Kernel — the platform's reliability substrate (docs/KERNEL_ARCHITECTURE.md).

K0: the Ledger — one transactional state store (SQLite WAL) backing the JSON caches
and the append-only event journal. K1 adds the Job Kernel, K2 the event stream to
the UI, K3 lineage/provenance.
"""
from aughor.kernel.ledger import Ledger

__all__ = ["Ledger"]
