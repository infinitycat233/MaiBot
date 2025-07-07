from src.chat.memory_system.Hippocampus import hippocampus_manager
from src.config.config import global_config
from src.chat.message_receive.message import MessageRecv
from src.chat.message_receive.storage import MessageStorage
from src.chat.heart_flow.heartflow import heartflow
from src.chat.message_receive.chat_stream import get_chat_manager
from src.chat.utils.utils import is_mentioned_bot_in_message
from src.chat.utils.timer_calculator import Timer
from src.common.logger import get_logger
import re
import math
import traceback
from typing import Optional, Tuple

from src.person_info.relationship_manager import get_relationship_manager

# from ..message_receive.message_buffer import message_buffer

logger = get_logger("chat")


async def _handle_error(error: Exception, context: str, message: Optional[MessageRecv] = None) -> None:
    """统一的错误处理函数

    Args:
        error: 捕获到的异常
        context: 错误发生的上下文描述
        message: 可选的消息对象，用于记录相关消息内容
    """
    logger.error(f"{context}: {error}")
    logger.error(traceback.format_exc())
    if message and hasattr(message, "raw_message"):
        logger.error(f"相关消息原始内容: {message.raw_message}")


async def _process_relationship(message: MessageRecv) -> None:
    """处理用户关系逻辑

    Args:
        message: 消息对象，包含用户信息
    """
    platform = message.message_info.platform
    user_id = message.message_info.user_info.user_id
    nickname = message.message_info.user_info.user_nickname
    cardname = message.message_info.user_info.user_cardname or nickname

    relationship_manager = get_relationship_manager()
    is_known = await relationship_manager.is_known_some_one(platform, user_id)

    if not is_known:
        logger.info(f"首次认识用户: {nickname}")
        await relationship_manager.first_knowing_some_one(platform, user_id, nickname, cardname)


async def _calculate_interest(message: MessageRecv) -> Tuple[float, bool]:
    """计算消息的兴趣度

    Args:
        message: 待处理的消息对象

    Returns:
        Tuple[float, bool]: (兴趣度, 是否被提及)
    """
    is_mentioned, _ = is_mentioned_bot_in_message(message)
    interested_rate = 0.0

    if global_config.memory.enable_memory:
        with Timer("记忆激活"):
            interested_rate = await hippocampus_manager.get_activate_from_text(
                message.processed_plain_text,
                fast_retrieval=True,
            )
            logger.debug(f"记忆激活率: {interested_rate:.2f}")

    text_len = len(message.processed_plain_text)
    # 根据文本长度调整兴趣度，长度越大兴趣度越高，但增长率递减，最低0.01，最高0.05
    # 采用对数函数实现递减增长

    base_interest = 0.01 + (0.05 - 0.01) * (math.log10(text_len + 1) / math.log10(1000 + 1))
    base_interest = min(max(base_interest, 0.01), 0.05)

    interested_rate += base_interest

    if is_mentioned:
        interest_increase_on_mention = 1
        interested_rate += interest_increase_on_mention

    return interested_rate, is_mentioned


class HeartFCMessageReceiver:
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
        try:
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

            subheartflow = await heartflow.get_or_create_subheartflow(chat.stream_id)
            message.update_chat_stream(chat)

            # 6. 兴趣度计算与更新
            interested_rate, is_mentioned = await _calculate_interest(message)
            subheartflow.add_message_to_normal_chat_cache(message, interested_rate, is_mentioned)

            # 7. 日志记录
            mes_name = chat.group_info.group_name if chat.group_info else "私聊"
            # current_time = time.strftime("%H:%M:%S", time.localtime(message.message_info.time))
            current_talk_frequency = global_config.chat.get_current_talk_frequency(chat.stream_id)

            # 如果消息中包含图片标识，则日志展示为图片

            picid_match = re.search(r"\[picid:([^\]]+)\]", message.processed_plain_text)
            if picid_match:
                logger.info(f"[{mes_name}]{userinfo.user_nickname}: [图片] [当前回复频率: {current_talk_frequency}]")
            else:
                logger.info(
                    f"[{mes_name}]{userinfo.user_nickname}:{message.processed_plain_text}[当前回复频率: {current_talk_frequency}]"
                )

            # 8. 关系处理
            if global_config.relationship.enable_relationship:
                await _process_relationship(message)

        except Exception as e:
            await _handle_error(e, "消息处理失败", message)
