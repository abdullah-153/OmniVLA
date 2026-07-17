"""
cogniagent/reasoning/action_reasoner.py

AgentAction data class used to represent the action the VLM decided to take.
Used by ScreenVerifier for semantic verification.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class AgentAction:
    """
    Represents a single agent action step.

    Attributes
    ----------
    action_type : str
        The name of the tool called (e.g. "click", "type", "key_press").
    thought : str
        The model's one-sentence plan for the action (from Step.thought).
    args : List[str]
        Optional ordered arguments (e.g. text to type, key name).
    """
    action_type: str = ""
    thought: str = ""
    args: List[str] = field(default_factory=list)
