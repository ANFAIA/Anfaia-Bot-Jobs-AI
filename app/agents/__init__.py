"""The system's specialized agents (they depend only on ports)."""

from app.agents.discord_publisher_agent import DiscordPublisherAgent
from app.agents.duplicate_detector import DuplicateDetectorAgent
from app.agents.job_classifier import JobClassifierAgent
from app.agents.job_collector import JobCollectorAgent
from app.agents.job_editor import JobEditorAgent

__all__ = [
    "DiscordPublisherAgent",
    "DuplicateDetectorAgent",
    "JobClassifierAgent",
    "JobCollectorAgent",
    "JobEditorAgent",
]
