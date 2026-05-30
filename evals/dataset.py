"""Load and wrap the golden dataset for Braintrust evals."""
from __future__ import annotations

import json
from pathlib import Path

GOLDEN_PATH = Path(__file__).parent / "golden.jsonl"


def load_golden_dataset() -> list[dict]:
    """Return all golden Q&A records from golden.jsonl."""
    records: list[dict] = []
    with open(GOLDEN_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def as_braintrust_dataset(name: str = "aughor-golden-v1"):
    """Wrap golden dataset as a Braintrust Dataset object.

    Lazy import — this function requires ``braintrust`` to be installed
    (``pip install 'aughor[evals]'``), but importing this module does not.
    """
    try:
        import braintrust  # type: ignore[import]
    except ImportError:
        raise ImportError(
            "braintrust is not installed. Run: pip install 'aughor[evals]'"
        ) from None

    ds = braintrust.init_dataset(project="aughor-investigations", name=name)
    for record in load_golden_dataset():
        ds.insert(
            input={
                "question": record["question"],
                "connection_id": record["connection_id"],
            },
            expected=record,
            id=record["id"],
        )
    return ds
