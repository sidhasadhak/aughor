"""Wave Q — the quality plane.

One structural rule, set in `docs/WAVE_Q_QUALITY_ARC.md` before any code: **monitors,
checks and profiler findings write ONE results store** (J12). Quality-shaped results
already lived in five mutually-unaware places, and a check result looks exactly like a
monitor alert, so the sixth surface was one convenient table away.

Eval results stay out. They answer "is the platform right", not "is this data healthy",
and merging those would be the opposite mistake.
"""
