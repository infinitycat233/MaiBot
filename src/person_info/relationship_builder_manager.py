from typing import Dict, Optional, List
from src.common.logger import get_logger
from .relationship_builder import RelationshipBuilder

logger = get_logger("relationship_builder_manager")


class RelationshipBuilderManager:
    """关系构建器管理器

    简单的关系构建器存储和获取管理
    """

    def __init__(self):
        self.builders: Dict[str, RelationshipBuilder] = {}

    def get_or_create_builder(self, chat_id: str) -> RelationshipBuilder:
        """获取或创建关系构建器

        Args:
            chat_id: 聊天ID

        Returns:
            RelationshipBuilder: 关系构建器实例
        """
        if chat_id not in self.builders:
            self.builders[chat_id] = RelationshipBuilder(chat_id)
            logger.info(f"创建聊天 {chat_id} 的关系构建器")

        return self.builders[chat_id]

    def get_builder(self, chat_id: str) -> Optional[RelationshipBuilder]:
        """获取关系构建器

        Args:
            chat_id: 聊天ID

        Returns:
            Optional[RelationshipBuilder]: 关系构建器实例或None
        """
        return self.builders.get(chat_id)

    def remove_builder(self, chat_id: str) -> bool:
        """移除关系构建器

        Args:
            chat_id: 聊天ID

        Returns:
            bool: 是否成功移除
        """
        if chat_id in self.builders:
            del self.builders[chat_id]
            logger.info(f"移除聊天 {chat_id} 的关系构建器")
            return True
        return False

    def get_all_chat_ids(self) -> List[str]:
        """获取所有管理的聊天ID列表

        Returns:
            List[str]: 聊天ID列表
        """
        return list(self.builders.keys())

    def get_status(self) -> Dict[str, any]:
        """获取管理器状态

        Returns:
            Dict[str, any]: 状态信息
        """
        return {
            "total_builders": len(self.builders),
            "chat_ids": list(self.builders.keys()),
        }

    async def process_chat_messages(self, chat_id: str):
        """处理指定聊天的消息

        Args:
            chat_id: 聊天ID
        """
        builder = self.get_or_create_builder(chat_id)
        await builder.build_relation()

    async def force_cleanup_user(self, chat_id: str, person_id: str) -> bool:
        """强制清理指定用户的关系构建缓存

        Args:
            chat_id: 聊天ID
            person_id: 用户ID

        Returns:
            bool: 是否成功清理
        """
        builder = self.get_builder(chat_id)
        if builder:
            return builder.force_cleanup_user_segments(person_id)
        return False


# 全局管理器实例
relationship_builder_manager = RelationshipBuilderManager()
