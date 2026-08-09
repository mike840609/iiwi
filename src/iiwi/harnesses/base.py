"""Harness source contracts."""

from abc import ABC, abstractmethod

from iiwi.models.session import AgentSession, SessionDescriptor
from iiwi.models.time_range import DateRange


class HarnessSessionSource(ABC):
    """Discover and load sessions from one coding-agent harness."""

    @abstractmethod
    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        raise NotImplementedError

    @abstractmethod
    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        raise NotImplementedError
