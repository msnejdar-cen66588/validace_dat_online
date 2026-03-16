"""Base Agent class for all pipeline agents."""
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass, field


class AgentStatus(str, Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAIL = "fail"
    WARN = "warn"


@dataclass
class AgentLog:
    """Single log entry from an agent."""
    timestamp: float
    message: str
    level: str = "info"  # info, warn, error, thinking

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "message": self.message,
            "level": self.level,
        }


@dataclass
class AgentResult:
    """Result from an agent's analysis."""
    status: AgentStatus = AgentStatus.IDLE
    category: Optional[int] = None
    score: Optional[float] = None
    summary: str = ""
    details: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "category": self.category,
            "score": self.score,
            "summary": self.summary,
            "details": self.details,
            "warnings": self.warnings,
            "errors": self.errors,
        }


class BaseAgent(ABC):
    """Abstract base class for all validation agents."""

    def __init__(self, name: str, description: str, system_prompt: str, model_name: str = "gemini"):
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.model_name = model_name
        self.status: AgentStatus = AgentStatus.IDLE
        self.logs: list[AgentLog] = []
        self.result: Optional[AgentResult] = None
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def log(self, message: str, level: str = "info"):
        """Add a log entry."""
        self.logs.append(AgentLog(
            timestamp=time.time(),
            message=message,
            level=level,
        ))

    def get_elapsed_time(self) -> float:
        """Get elapsed processing time in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time else time.time()
        return round(end - self.start_time, 2)

    @abstractmethod
    async def run(self, context: dict) -> AgentResult:
        """Execute the agent's analysis."""
        pass

    async def execute(self, context: dict) -> AgentResult:
        """Execute the agent with status tracking and logging."""
        self.status = AgentStatus.PROCESSING
        self.start_time = time.time()
        self.logs = []
        self.log(f"Agent {self.name} started processing.")

        try:
            self.result = await self.run(context)
            self.status = self.result.status
            self.log(f"Agent {self.name} finished with status: {self.status.value}")
        except Exception as e:
            self.status = AgentStatus.FAIL
            self.result = AgentResult(
                status=AgentStatus.FAIL,
                summary=f"Agent error: {str(e)}",
                errors=[str(e)],
            )
            self.log(f"Agent {self.name} encountered error: {str(e)}", level="error")

        self.end_time = time.time()
        return self.result

    def to_dict(self) -> dict:
        """Serialize agent state for API responses."""
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "status": self.status.value,
            "logs": [log.to_dict() for log in self.logs],
            "result": self.result.to_dict() if self.result else None,
            "elapsed_time": self.get_elapsed_time(),
        }
