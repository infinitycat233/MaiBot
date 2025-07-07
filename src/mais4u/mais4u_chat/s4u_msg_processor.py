from src.chat.message_receive.message import MessageRecv
from src.chat.message_receive.storage import MessageStorage
from src.chat.message_receive.chat_stream import get_chat_manager
from src.common.logger import get_logger
from .s4u_chat import get_s4u_chat_manager


# from ..message_receive.message_buffer import message_buffer

logger = get_logger("chat")


class S4UMessageProcessor:
    """心流处理器，负责处理接收到的消息并计算兴趣度"""

    def __init__(self):
        """初始化心流处理器，创建消息存储实例"""
        self.storage = MessageStorage()

    async def process_message(self, message: MessageRecv) -> None:
        """处理接收到的原始消息数据

        主要流程:
        1. 消息解析与初始化
        2. 消息缓冲处理
        3. 过滤检查
        4. 兴趣度计算
        5. 关系处理

        Args:
            message_data: 原始消息字符串
        """

        target_user_id_list = ["1026294844", "964959351"]

        # 1. 消息解析与初始化
        groupinfo = message.message_info.group_info
        userinfo = message.message_info.user_info
        messageinfo = message.message_info

        chat = await get_chat_manager().get_or_create_stream(
            platform=messageinfo.platform,
            user_info=userinfo,
            group_info=groupinfo,
        )

        await self.storage.store_message(message, chat)

        s4u_chat = get_s4u_chat_manager().get_or_create_chat(chat)

        if userinfo.user_id in target_user_id_list:
            await s4u_chat.add_message(message)
        else:
            await s4u_chat.add_message(message)

        # 7. 日志记录
        logger.info(f"[S4U]{userinfo.user_nickname}:{message.processed_plain_text}")
