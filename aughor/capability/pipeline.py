"""The ③ Capability plane's template (AL-02) — one answer shape, `Generate → Validate →
Execute → Interpret`, parameterized by domain.

The review found three isomorphic pipelines implemented separately — Data (SQL Generator →
SQL Validator → execute → Interpreter), Code (Generator → Validator → Executor → Interpreter),
Metadata (Handler → Interpreter). They are the *same shape* built three times. This models
that shape once as a `CapabilityPipeline` Protocol + a `run()` template that sequences the four
phases and routes `validate` through the Trust plane (`aughor/trust.verify` — AL-01). A new
capability (the review's "forecast" example) is then *registered*, not wired by hand.

Named `CapabilityPipeline`, NOT `Capability`, to stay clear of `licensing.capabilities.Capability`
(the tier/permission enum) — a different concern. This is the answer-pipeline template.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from aughor.trust import Scope, Verdict, verify as trust_verify


@dataclass
class CapabilityRequest:
    """What a capability is asked to answer, plus the scope its guards/probes need.

    `semantic` carries a resolved `SemanticContext` from the Semantic plane (AL-05) — the review's
    "Capability takes Question × Scope × SemanticContext" contract. Typed loosely (`Any`) so the
    Capability plane stays independent of the Semantic plane; orchestration composes them."""
    question: str = ""
    artifact: str = ""                                 # a pre-supplied artifact (e.g. user SQL)
    scope: Scope = field(default_factory=Scope)
    semantic: Any = None                               # a semantic.SemanticContext, attached by orchestration
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilityResult:
    """The uniform carrier every domain returns, so callers don't special-case per pipeline."""
    domain: str
    ok: bool
    artifact: str = ""                                 # the (possibly repaired) artifact that ran
    verdict: Verdict | None = None
    output: dict[str, Any] = field(default_factory=dict)  # domain-specific (rows/columns for sql, …)
    narrative: str = ""
    error: str = ""
    trace: tuple[str, ...] = ()                        # the phases that fired, in order — a receipt


@runtime_checkable
class CapabilityPipeline(Protocol):
    """One domain answered in four phases. `domain` is the registry key ("data", "metadata",
    "forecast", …); `kind` is the Trust-plane artifact kind ("sql" | "code" | "metadata")."""
    domain: str
    kind: str

    def generate(self, req: CapabilityRequest) -> str: ...
    def validate(self, artifact: str, req: CapabilityRequest) -> Verdict: ...
    def execute(self, artifact: str, req: CapabilityRequest) -> dict: ...
    def interpret(self, output: dict, req: CapabilityRequest) -> str: ...


def default_validate(kind: str, artifact: str, req: CapabilityRequest) -> Verdict:
    """The shared validate every capability gets for free: route the artifact through the one
    Trust plane. A pipeline may override, but the default *is* the plane — that's the point."""
    return trust_verify(artifact, req.scope, kind=kind)


def run(pipeline: CapabilityPipeline, req: CapabilityRequest) -> CapabilityResult:
    """Sequence the four phases. A failed `validate` (a Trust-plane BLOCK) short-circuits before
    execute — a mutating statement never reaches the database. `validate` may repair the artifact
    (`Verdict.artifact`); the repaired form is what executes. Never raises out of a phase is *not*
    guaranteed here — a pipeline's own phases own their error handling; the template only owns the
    ordering + the block short-circuit."""
    trace = ["generate"]
    artifact = pipeline.generate(req)

    trace.append("validate")
    verdict = pipeline.validate(artifact, req)
    if not verdict.ok:
        return CapabilityResult(domain=pipeline.domain, ok=False, artifact=artifact,
                                verdict=verdict, error=verdict.reason, trace=tuple(trace))
    artifact = verdict.artifact or artifact            # adopt any repair the validate produced

    trace.append("execute")
    output = pipeline.execute(artifact, req) or {}

    trace.append("interpret")
    narrative = pipeline.interpret(output, req)

    err = (output.get("error") if isinstance(output, dict) else None) or ""
    return CapabilityResult(domain=pipeline.domain, ok=(not err), artifact=artifact, verdict=verdict,
                            output=output if isinstance(output, dict) else {}, narrative=narrative,
                            error=err, trace=tuple(trace))
