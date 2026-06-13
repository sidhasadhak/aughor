"""Action Hub data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class ActionTrigger:
    """A configured webhook integration that fires when a recommendation is executed."""
    id:       str
    name:     str
    type:     Literal["webhook", "slack", "jira"]
    url:      str
    headers:  dict[str, str] = field(default_factory=dict)
    enabled:  bool = True
    # Optional Slack-specific
    channel:  Optional[str] = None
    # Optional Jira-specific
    project:  Optional[str] = None
    issue_type: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "name":       self.name,
            "type":       self.type,
            "url":        self.url,
            "headers":    self.headers,
            "enabled":    self.enabled,
            "channel":    self.channel,
            "project":    self.project,
            "issue_type": self.issue_type,
        }

    def to_safe_dict(self) -> dict:
        """API-facing form — the credential `url` is masked so the raw secret never
        leaves the server. The frontend shows the preview; on save it sends the mask
        back unchanged, which the update path detects and keeps (see the router)."""
        from aughor.secretvault import mask_secret
        return {**self.to_dict(), "url": mask_secret(self.url)}

    @classmethod
    def from_dict(cls, d: dict) -> "ActionTrigger":
        return cls(
            id=d["id"],
            name=d["name"],
            type=d.get("type", "webhook"),
            url=d.get("url", ""),
            headers=d.get("headers", {}),
            enabled=d.get("enabled", True),
            channel=d.get("channel"),
            project=d.get("project"),
            issue_type=d.get("issue_type"),
        )


@dataclass
class ActionPayload:
    """Context payload sent to the webhook when a recommendation is executed."""
    investigation_id: str
    rec_index:        int
    recommendation:   str
    metric_name:      str
    headline:         Optional[str]
    trigger_id:       str
    triggered_at:     str

    def to_dict(self) -> dict:
        return {
            "investigation_id": self.investigation_id,
            "rec_index":        self.rec_index,
            "recommendation":   self.recommendation,
            "metric_name":      self.metric_name,
            "headline":         self.headline,
            "trigger_id":       self.trigger_id,
            "triggered_at":     self.triggered_at,
            "source":           "aughor",
        }


@dataclass
class ActionLog:
    """Immutable record of a fired action."""
    id:               str
    trigger_id:       str
    trigger_name:     str
    investigation_id: str
    rec_index:        int
    recommendation:   str
    status:           Literal["ok", "failed", "timeout"]
    http_status:      Optional[int]
    error:            Optional[str]
    fired_at:         str

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "trigger_id":       self.trigger_id,
            "trigger_name":     self.trigger_name,
            "investigation_id": self.investigation_id,
            "rec_index":        self.rec_index,
            "recommendation":   self.recommendation,
            "status":           self.status,
            "http_status":      self.http_status,
            "error":            self.error,
            "fired_at":         self.fired_at,
        }
