"""
发送API模块

专门负责发送各种类型的消息，采用标准Python包设计模式

使用方式：
    from src.plugin_system.apis import send_api

    # 方式1：直接使用stream_id（推荐）
    await send_api.text_to_stream("hello", stream_id)
    await send_api.emoji_to_stream(emoji_base64, stream_id)
    await send_api.custom_to_stream("video", video_data, stream_id)

    # 方式2：使用群聊/私聊指定函数
    await send_api.text_to_group("hello", "123456")
    await send_api.text_to_user("hello", "987654")

    # 方式3：使用通用custom_message函数
    await send_api.custom_message("video", video_data, "123456", True)
"""

import traceback
import time
from typing import Optional, Union, Dict, Any, List, TYPE_CHECKING

from src.common.logger import get_logger
from src.config.config import global_config
from src.chat.message_receive.chat_stream import get_chat_manager
from src.chat.message_receive.uni_message_sender import HeartFCSender
from src.chat.message_receive.message import MessageSending, MessageRecv
from maim_message import Seg, UserInfo

if TYPE_CHECKING:
    from src.common.data_models.database_data_model import DatabaseMessages

logger = get_logger("send_api")


# =============================================================================
# 内部实现函数（不暴露给外部）
# =============================================================================


async def _send_to_target(
    message_type: str,
    content: Union[str, dict],
    stream_id: str,
    display_message: str = "",
    typing: bool = False,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
    selected_expressions: Optional[List[int]] = None,
) -> bool:
    """向指定目标发送消息的内部实现

    Args:
        message_type: 消息类型，如"text"、"image"、"emoji"等
        content: 消息内容
        stream_id: 目标流ID
        display_message: 显示消息
        typing: 是否模拟打字等待。
        reply_to: 回复消息，格式为"发送者:消息内容"
        storage_message: 是否存储消息到数据库
        show_log: 发送是否显示日志

    Returns:
        bool: 是否发送成功
    """
    try:
        if set_reply and not reply_message:
            logger.warning("[SendAPI] 使用引用回复，但未提供回复消息")
            return False

        if show_log:
            logger.debug(f"[SendAPI] 发送{message_type}消息到 {stream_id}")

        # 查找目标聊天流
        target_stream = get_chat_manager().get_stream(stream_id)
        if not target_stream:
            logger.error(f"[SendAPI] 未找到聊天流: {stream_id}")
            return False

        # 创建发送器
        heart_fc_sender = HeartFCSender()

        # 生成消息ID
        current_time = time.time()
        message_id = f"send_api_{int(current_time * 1000)}"

        # 构建机器人用户信息
        bot_user_info = UserInfo(
            user_id=global_config.bot.qq_account,
            user_nickname=global_config.bot.nickname,
            platform=target_stream.platform,
        )

        # 创建消息段
        message_segment = Seg(type=message_type, data=content)  # type: ignore

        if reply_message:
            anchor_message = message_dict_to_message_recv(reply_message.flatten())
            if anchor_message:
                anchor_message.update_chat_stream(target_stream)
                assert anchor_message.message_info.user_info, "用户信息缺失"
                reply_to_platform_id = (
                    f"{anchor_message.message_info.platform}:{anchor_message.message_info.user_info.user_id}"
                )
        else:
            reply_to_platform_id = ""
            anchor_message = None

        # 构建发送消息对象
        bot_message = MessageSending(
            message_id=message_id,
            chat_stream=target_stream,
            bot_user_info=bot_user_info,
            sender_info=target_stream.user_info,
            message_segment=message_segment,
            display_message=display_message,
            reply=anchor_message,
            is_head=True,
            is_emoji=(message_type == "emoji"),
            thinking_start_time=current_time,
            reply_to=reply_to_platform_id,
            selected_expressions=selected_expressions,
        )

        # 发送消息
        sent_msg = await heart_fc_sender.send_message(
            bot_message,
            typing=typing,
            set_reply=set_reply,
            storage_message=storage_message,
            show_log=show_log,
        )

        if sent_msg:
            logger.debug(f"[SendAPI] 成功发送消息到 {stream_id}")
            return True
        else:
            logger.error("[SendAPI] 发送消息失败")
            return False

    except Exception as e:
        logger.error(f"[SendAPI] 发送消息时出错: {e}")
        traceback.print_exc()
        return False


def message_dict_to_message_recv(message_dict: Dict[str, Any]) -> Optional[MessageRecv]:
    """将数据库dict重建为MessageRecv对象
    Args:
        message_dict: 消息字典

    Returns:
        Optional[MessageRecv]: 找到的消息，如果没找到则返回None
    """
    # 构建MessageRecv对象
    user_info = {
        "platform": message_dict.get("user_platform", ""),
        "user_id": message_dict.get("user_id", ""),
        "user_nickname": message_dict.get("user_nickname", ""),
        "user_cardname": message_dict.get("user_cardname", ""),
    }

    group_info = {}
    if message_dict.get("chat_info_group_id"):
        group_info = {
            "platform": message_dict.get("chat_info_group_platform", ""),
            "group_id": message_dict.get("chat_info_group_id", ""),
            "group_name": message_dict.get("chat_info_group_name", ""),
        }

    format_info = {"content_format": "", "accept_format": ""}
    template_info = {"template_items": {}}

    message_info = {
        "platform": message_dict.get("chat_info_platform", ""),
        "message_id": message_dict.get("message_id"),
        "time": message_dict.get("time"),
        "group_info": group_info,
        "user_info": user_info,
        "additional_config": message_dict.get("additional_config"),
        "format_info": format_info,
        "template_info": template_info,
    }

    message_dict_recv = {
        "message_info": message_info,
        "raw_message": message_dict.get("processed_plain_text"),
        "processed_plain_text": message_dict.get("processed_plain_text"),
    }

    message_recv = MessageRecv(message_dict_recv)

    logger.info(f"[SendAPI] 找到匹配的回复消息，发送者: {message_dict.get('user_nickname', '')}")
    return message_recv


# =============================================================================
# 公共API函数 - 预定义类型的发送函数
# =============================================================================


async def text_to_stream(
    text: str,
    stream_id: str,
    typing: bool = False,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    selected_expressions: Optional[List[int]] = None,
) -> bool:
    """向指定流发送文本消息

    Args:
        text: 要发送的文本内容
        stream_id: 聊天流ID
        typing: 是否显示正在输入
        reply_to: 回复消息，格式为"发送者:消息内容"
        storage_message: 是否存储消息到数据库

    Returns:
        bool: 是否发送成功
    """
    return await _send_to_target(
        "text",
        text,
        stream_id,
        "",
        typing,
        set_reply=set_reply,
        reply_message=reply_message,
        storage_message=storage_message,
        selected_expressions=selected_expressions,
    )


async def emoji_to_stream(
    emoji_base64: str,
    stream_id: str,
    storage_message: bool = True,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
) -> bool:
    """向指定流发送表情包

    Args:
        emoji_base64: 表情包的base64编码
        stream_id: 聊天流ID
        storage_message: 是否存储消息到数据库

    Returns:
        bool: 是否发送成功
    """
    return await _send_to_target(
        "emoji",
        emoji_base64,
        stream_id,
        "",
        typing=False,
        storage_message=storage_message,
        set_reply=set_reply,
        reply_message=reply_message,
    )


async def image_to_stream(
    image_base64: str,
    stream_id: str,
    storage_message: bool = True,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
) -> bool:
    """向指定流发送图片

    Args:
        image_base64: 图片的base64编码
        stream_id: 聊天流ID
        storage_message: 是否存储消息到数据库

    Returns:
        bool: 是否发送成功
    """
    return await _send_to_target(
        "image",
        image_base64,
        stream_id,
        "",
        typing=False,
        storage_message=storage_message,
        set_reply=set_reply,
        reply_message=reply_message,
    )


async def command_to_stream(
    command: Union[str, dict],
    stream_id: str,
    storage_message: bool = True,
    display_message: str = "",
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
) -> bool:
    """向指定流发送命令

    Args:
        command: 命令
        stream_id: 聊天流ID
        storage_message: 是否存储消息到数据库

    Returns:
        bool: 是否发送成功
    """
    return await _send_to_target(
        "command",
        command,
        stream_id,
        display_message,
        typing=False,
        storage_message=storage_message,
        set_reply=set_reply,
        reply_message=reply_message,
    )


async def custom_to_stream(
    message_type: str,
    content: str | dict,
    stream_id: str,
    display_message: str = "",
    typing: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    set_reply: bool = False,
    storage_message: bool = True,
    show_log: bool = True,
) -> bool:
    """向指定流发送自定义类型消息

    Args:
        message_type: 消息类型，如"text"、"image"、"emoji"、"video"、"file"等
        content: 消息内容（通常是base64编码或文本）
        stream_id: 聊天流ID
        display_message: 显示消息
        typing: 是否显示正在输入
        reply_to: 回复消息，格式为"发送者:消息内容"
        storage_message: 是否存储消息到数据库
        show_log: 是否显示日志
    Returns:
        bool: 是否发送成功
    """
    return await _send_to_target(
        message_type=message_type,
        content=content,
        stream_id=stream_id,
        display_message=display_message,
        typing=typing,
        reply_message=reply_message,
        set_reply=set_reply,
        storage_message=storage_message,
        show_log=show_log,
    )
