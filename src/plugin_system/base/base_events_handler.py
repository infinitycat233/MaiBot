from abc import ABC, abstractmethod
from typing import Tuple, Optional, Dict

from src.common.logger import get_logger
from .component_types import MaiMessages, EventType, EventHandlerInfo, ComponentType

logger = get_logger("base_event_handler")


class BaseEventHandler(ABC):
    """事件处理器基类

    所有事件处理器都应该继承这个基类，提供事件处理的基本接口
    """

    event_type: EventType | str = EventType.UNKNOWN
    """事件类型，默认为未知"""
    handler_name: str = ""
    """处理器名称"""
    handler_description: str = ""
    """处理器描述"""
    weight: int = 0
    """处理器权重，越大权重越高"""
    intercept_message: bool = False
    """是否拦截消息，默认为否"""

    def __init__(self):
        self.log_prefix = "[EventHandler]"
        self.plugin_name = ""
        """对应插件名"""
        self.plugin_config: Optional[Dict] = None
        """插件配置字典"""
        if self.event_type == EventType.UNKNOWN:
            raise NotImplementedError("事件处理器必须指定 event_type")

    @abstractmethod
    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, Optional[str]]:
        """执行事件处理的抽象方法，子类必须实现
        Args:
            message (MaiMessages | None): 事件消息对象，当你注册的事件为ON_START和ON_STOP时message为None
        Returns:
            Tuple[bool, bool, Optional[str]]: (是否执行成功, 是否需要继续处理, 可选的返回消息)
        """
        raise NotImplementedError("子类必须实现 execute 方法")

    @classmethod
    def get_handler_info(cls) -> "EventHandlerInfo":
        """获取事件处理器的信息"""
        # 从类属性读取名称，如果没有定义则使用类名自动生成
        name: str = getattr(cls, "handler_name", cls.__name__.lower().replace("handler", ""))
        if "." in name:
            logger.error(f"事件处理器名称 '{name}' 包含非法字符 '.'，请使用下划线替代")
            raise ValueError(f"事件处理器名称 '{name}' 包含非法字符 '.'，请使用下划线替代")
        return EventHandlerInfo(
            name=name,
            component_type=ComponentType.EVENT_HANDLER,
            description=getattr(cls, "handler_description", "events处理器"),
            event_type=cls.event_type,
            weight=cls.weight,
            intercept_message=cls.intercept_message,
        )

    def set_plugin_config(self, plugin_config: Dict) -> None:
        """设置插件配置

        Args:
            plugin_config (dict): 插件配置字典
        """
        self.plugin_config = plugin_config

    def set_plugin_name(self, plugin_name: str) -> None:
        """设置插件名称

        Args:
            plugin_name (str): 插件名称
        """
        self.plugin_name = plugin_name

    def get_config(self, key: str, default=None):
        """获取插件配置值，支持嵌套键访问

        Args:
            key: 配置键名，支持嵌套访问如 "section.subsection.key"
            default: 默认值

        Returns:
            Any: 配置值或默认值
        """
        if not self.plugin_config:
            return default

        # 支持嵌套键访问
        keys = key.split(".")
        current = self.plugin_config

        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default

        return current
