from dataclasses import dataclass, field
from typing import Optional, Dict, TYPE_CHECKING
from . import BaseDataModel

if TYPE_CHECKING:
    from .database_data_model import DatabaseMessages
    from src.plugin_system.base.component_types import ActionInfo


@dataclass
class TargetPersonInfo(BaseDataModel):
    platform: str = field(default_factory=str)
    user_id: str = field(default_factory=str)
    user_nickname: str = field(default_factory=str)
    person_id: Optional[str] = None
    person_name: Optional[str] = None


@dataclass
class ActionPlannerInfo(BaseDataModel):
    action_type: str = field(default_factory=str)
    reasoning: Optional[str] = None
    action_data: Optional[Dict] = None
    action_message: Optional["DatabaseMessages"] = None
    available_actions: Optional[Dict[str, "ActionInfo"]] = None
