import time
import urllib3

from abc import abstractmethod
from dataclasses import dataclass
from rich.traceback import install
from typing import Optional, Any, List
from maim_message import Seg, UserInfo, BaseMessageInfo, MessageBase

from src.common.logger import get_logger
from src.chat.utils.utils_image import get_image_manager
from src.chat.utils.utils_voice import get_voice_text
from .chat_stream import ChatStream

install(extra_lines=3)

logger = get_logger("chat_message")

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 这个类是消息数据类，用于存储和管理消息数据。
# 它定义了消息的属性，包括群组ID、用户ID、消息ID、原始消息内容、纯文本内容和时间戳。
# 它还定义了两个辅助属性：keywords用于提取消息的关键词，is_plain_text用于判断消息是否为纯文本。


@dataclass
class Message(MessageBase):
    chat_stream: "ChatStream" = None  # type: ignore
    reply: Optional["Message"] = None
    processed_plain_text: str = ""

    def __init__(
        self,
        message_id: str,
        chat_stream: "ChatStream",
        user_info: UserInfo,
        message_segment: Optional[Seg] = None,
        timestamp: Optional[float] = None,
        reply: Optional["MessageRecv"] = None,
        processed_plain_text: str = "",
    ):
        # 使用传入的时间戳或当前时间
        current_timestamp = timestamp if timestamp is not None else round(time.time(), 3)
        # 构造基础消息信息
        message_info = BaseMessageInfo(
            platform=chat_stream.platform,
            message_id=message_id,
            time=current_timestamp,
            group_info=chat_stream.group_info,
            user_info=user_info,
        )

        # 调用父类初始化
        super().__init__(message_info=message_info, message_segment=message_segment, raw_message=None)  # type: ignore

        self.chat_stream = chat_stream
        # 文本处理相关属性
        self.processed_plain_text = processed_plain_text

        # 回复消息
        self.reply = reply

    async def _process_message_segments(self, segment: Seg) -> str:
        # sourcery skip: remove-unnecessary-else, swap-if-else-branches
        """递归处理消息段，转换为文字描述

        Args:
            segment: 要处理的消息段

        Returns:
            str: 处理后的文本
        """
        if segment.type == "seglist":
            # 处理消息段列表
            segments_text = []
            for seg in segment.data:
                processed = await self._process_message_segments(seg)  # type: ignore
                if processed:
                    segments_text.append(processed)
            return " ".join(segments_text)
        else:
            # 处理单个消息段
            return await self._process_single_segment(segment)  # type: ignore

    @abstractmethod
    async def _process_single_segment(self, segment):
        pass


@dataclass
class MessageRecv(Message):
    """接收消息类，用于处理从MessageCQ序列化的消息"""

    def __init__(self, message_dict: dict[str, Any]):
        """从MessageCQ的字典初始化

        Args:
            message_dict: MessageCQ序列化后的字典
        """
        self.message_info = BaseMessageInfo.from_dict(message_dict.get("message_info", {}))
        self.message_segment = Seg.from_dict(message_dict.get("message_segment", {}))
        self.raw_message = message_dict.get("raw_message")
        self.processed_plain_text = message_dict.get("processed_plain_text", "")
        self.is_emoji = False
        self.has_emoji = False
        self.is_picid = False
        self.has_picid = False
        self.is_voice = False
        self.is_mentioned = None
        self.is_notify = False

        self.is_command = False

        self.priority_mode = "interest"
        self.priority_info = None
        self.interest_value: float = None  # type: ignore

        self.key_words = []
        self.key_words_lite = []

    def update_chat_stream(self, chat_stream: "ChatStream"):
        self.chat_stream = chat_stream

    async def process(self) -> None:
        """处理消息内容，生成纯文本和详细文本

        这个方法必须在创建实例后显式调用，因为它包含异步操作。
        """
        self.processed_plain_text = await self._process_message_segments(self.message_segment)

    async def _process_single_segment(self, segment: Seg) -> str:
        """处理单个消息段

        Args:
            segment: 消息段

        Returns:
            str: 处理后的文本
        """
        try:
            if segment.type == "text":
                self.is_picid = False
                self.is_emoji = False
                return segment.data  # type: ignore
            elif segment.type == "image":
                # 如果是base64图片数据
                if isinstance(segment.data, str):
                    self.has_picid = True
                    self.is_picid = True
                    self.is_emoji = False
                    image_manager = get_image_manager()
                    # print(f"segment.data: {segment.data}")
                    _, processed_text = await image_manager.process_image(segment.data)
                    return processed_text
                return "[发了一张图片，网卡了加载不出来]"
            elif segment.type == "emoji":
                self.has_emoji = True
                self.is_emoji = True
                self.is_picid = False
                self.is_voice = False
                if isinstance(segment.data, str):
                    return await get_image_manager().get_emoji_description(segment.data)
                return "[发了一个表情包，网卡了加载不出来]"
            elif segment.type == "voice":
                self.is_picid = False
                self.is_emoji = False
                self.is_voice = True
                if isinstance(segment.data, str):
                    return await get_voice_text(segment.data)
                return "[发了一段语音，网卡了加载不出来]"
            elif segment.type == "mention_bot":
                self.is_picid = False
                self.is_emoji = False
                self.is_voice = False
                self.is_mentioned = float(segment.data)  # type: ignore
                return ""
            elif segment.type == "priority_info":
                self.is_picid = False
                self.is_emoji = False
                self.is_voice = False
                if isinstance(segment.data, dict):
                    # 处理优先级信息
                    self.priority_mode = "priority"
                    self.priority_info = segment.data
                    """
                    {
                        'message_type': 'vip', # vip or normal
                        'message_priority': 1.0, # 优先级，大为优先，float
                    }
                    """
                return ""
            else:
                return ""
        except Exception as e:
            logger.error(f"处理消息段失败: {str(e)}, 类型: {segment.type}, 数据: {segment.data}")
            return f"[处理失败的{segment.type}消息]"


@dataclass
class MessageRecvS4U(MessageRecv):
    def __init__(self, message_dict: dict[str, Any]):
        super().__init__(message_dict)
        self.is_gift = False
        self.is_fake_gift = False
        self.is_superchat = False
        self.gift_info = None
        self.gift_name = None
        self.gift_count: Optional[str] = None
        self.superchat_info = None
        self.superchat_price = None
        self.superchat_message_text = None
        self.is_screen = False
        self.is_internal = False
        self.voice_done = None

        self.chat_info = None

    async def process(self) -> None:
        self.processed_plain_text = await self._process_message_segments(self.message_segment)

    async def _process_single_segment(self, segment: Seg) -> str:
        """处理单个消息段

        Args:
            segment: 消息段

        Returns:
            str: 处理后的文本
        """
        try:
            if segment.type == "text":
                self.is_voice = False
                self.is_picid = False
                self.is_emoji = False
                return segment.data  # type: ignore
            elif segment.type == "image":
                self.is_voice = False
                # 如果是base64图片数据
                if isinstance(segment.data, str):
                    self.has_picid = True
                    self.is_picid = True
                    self.is_emoji = False
                    image_manager = get_image_manager()
                    # print(f"segment.data: {segment.data}")
                    _, processed_text = await image_manager.process_image(segment.data)
                    return processed_text
                return "[发了一张图片，网卡了加载不出来]"
            elif segment.type == "emoji":
                self.has_emoji = True
                self.is_emoji = True
                self.is_picid = False
                if isinstance(segment.data, str):
                    return await get_image_manager().get_emoji_description(segment.data)
                return "[发了一个表情包，网卡了加载不出来]"
            elif segment.type == "voice":
                self.has_picid = False
                self.is_picid = False
                self.is_emoji = False
                self.is_voice = True
                if isinstance(segment.data, str):
                    return await get_voice_text(segment.data)
                return "[发了一段语音，网卡了加载不出来]"
            elif segment.type == "mention_bot":
                self.is_voice = False
                self.is_picid = False
                self.is_emoji = False
                self.is_mentioned = float(segment.data)  # type: ignore
                return ""
            elif segment.type == "priority_info":
                self.is_voice = False
                self.is_picid = False
                self.is_emoji = False
                if isinstance(segment.data, dict):
                    # 处理优先级信息
                    self.priority_mode = "priority"
                    self.priority_info = segment.data
                    """
                    {
                        'message_type': 'vip', # vip or normal
                        'message_priority': 1.0, # 优先级，大为优先，float
                    }
                    """
                return ""
            elif segment.type == "gift":
                self.is_voice = False
                self.is_gift = True
                # 解析gift_info，格式为"名称:数量"
                name, count = segment.data.split(":", 1)  # type: ignore
                self.gift_info = segment.data
                self.gift_name = name.strip()
                self.gift_count = int(count.strip())
                return ""
            elif segment.type == "voice_done":
                msg_id = segment.data
                logger.info(f"voice_done: {msg_id}")
                self.voice_done = msg_id
                return ""
            elif segment.type == "superchat":
                self.is_superchat = True
                self.superchat_info = segment.data
                price, message_text = segment.data.split(":", 1)  # type: ignore
                self.superchat_price = price.strip()
                self.superchat_message_text = message_text.strip()

                self.processed_plain_text = str(self.superchat_message_text)
                self.processed_plain_text += (
                    f"（注意：这是一条超级弹幕信息，价值{self.superchat_price}元，请你认真回复）"
                )

                return self.processed_plain_text
            elif segment.type == "screen":
                self.is_screen = True
                self.screen_info = segment.data
                return "屏幕信息"
            else:
                return ""
        except Exception as e:
            logger.error(f"处理消息段失败: {str(e)}, 类型: {segment.type}, 数据: {segment.data}")
            return f"[处理失败的{segment.type}消息]"


@dataclass
class MessageProcessBase(Message):
    """消息处理基类，用于处理中和发送中的消息"""

    def __init__(
        self,
        message_id: str,
        chat_stream: "ChatStream",
        bot_user_info: UserInfo,
        message_segment: Optional[Seg] = None,
        reply: Optional["MessageRecv"] = None,
        thinking_start_time: float = 0,
        timestamp: Optional[float] = None,
    ):
        # 调用父类初始化，传递时间戳
        super().__init__(
            message_id=message_id,
            timestamp=timestamp,
            chat_stream=chat_stream,
            user_info=bot_user_info,
            message_segment=message_segment,
            reply=reply,
        )

        # 处理状态相关属性
        self.thinking_start_time = thinking_start_time
        self.thinking_time = 0

    def update_thinking_time(self) -> float:
        """更新思考时间"""
        self.thinking_time = round(time.time() - self.thinking_start_time, 2)
        return self.thinking_time

    async def _process_single_segment(self, seg: Seg) -> str | None:
        """处理单个消息段

        Args:
            seg: 要处理的消息段

        Returns:
            str: 处理后的文本
        """
        try:
            if seg.type == "text":
                return seg.data  # type: ignore
            elif seg.type == "image":
                # 如果是base64图片数据
                if isinstance(seg.data, str):
                    return await get_image_manager().get_image_description(seg.data)
                return "[图片，网卡了加载不出来]"
            elif seg.type == "emoji":
                if isinstance(seg.data, str):
                    return await get_image_manager().get_emoji_tag(seg.data)
                return "[表情，网卡了加载不出来]"
            elif seg.type == "voice":
                if isinstance(seg.data, str):
                    return await get_voice_text(seg.data)
                return "[发了一段语音，网卡了加载不出来]"
            elif seg.type == "at":
                return f"[@{seg.data}]"
            elif seg.type == "reply":
                if self.reply and hasattr(self.reply, "processed_plain_text"):
                    # print(f"self.reply.processed_plain_text: {self.reply.processed_plain_text}")
                    # print(f"reply: {self.reply}")
                    return f"[回复<{self.reply.message_info.user_info.user_nickname}:{self.reply.message_info.user_info.user_id}> 的消息：{self.reply.processed_plain_text}]"  # type: ignore
                return None
            else:
                return f"[{seg.type}:{str(seg.data)}]"
        except Exception as e:
            logger.error(f"处理消息段失败: {str(e)}, 类型: {seg.type}, 数据: {seg.data}")
            return f"[处理失败的{seg.type}消息]"

    def _generate_detailed_text(self) -> str:
        """生成详细文本，包含时间和用户信息"""
        # time_str = time.strftime("%m-%d %H:%M:%S", time.localtime(self.message_info.time))
        timestamp = self.message_info.time
        user_info = self.message_info.user_info

        name = f"<{self.message_info.platform}:{user_info.user_id}:{user_info.user_nickname}:{user_info.user_cardname}>"  # type: ignore
        return f"[{timestamp}]，{name} 说：{self.processed_plain_text}\n"


@dataclass
class MessageSending(MessageProcessBase):
    """发送状态的消息类"""

    def __init__(
        self,
        message_id: str,
        chat_stream: "ChatStream",
        bot_user_info: UserInfo,
        sender_info: UserInfo | None,  # 用来记录发送者信息
        message_segment: Seg,
        display_message: str = "",
        reply: Optional["MessageRecv"] = None,
        is_head: bool = False,
        is_emoji: bool = False,
        thinking_start_time: float = 0,
        apply_set_reply_logic: bool = False,
        reply_to: Optional[str] = None,
        selected_expressions: Optional[List[int]] = None,
    ):
        # 调用父类初始化
        super().__init__(
            message_id=message_id,
            chat_stream=chat_stream,
            bot_user_info=bot_user_info,
            message_segment=message_segment,
            reply=reply,
            thinking_start_time=thinking_start_time,
        )

        # 发送状态特有属性
        self.sender_info = sender_info
        self.reply_to_message_id = reply.message_info.message_id if reply else None
        self.is_head = is_head
        self.is_emoji = is_emoji
        self.apply_set_reply_logic = apply_set_reply_logic

        self.reply_to = reply_to

        # 用于显示发送内容与显示不一致的情况
        self.display_message = display_message

        self.interest_value = 0.0

        self.selected_expressions = selected_expressions

    def build_reply(self):
        """设置回复消息"""
        if self.reply:
            self.reply_to_message_id = self.reply.message_info.message_id
            self.message_segment = Seg(
                type="seglist",
                data=[
                    Seg(type="reply", data=self.reply.message_info.message_id),  # type: ignore
                    self.message_segment,
                ],
            )

    async def process(self) -> None:
        """处理消息内容，生成纯文本和详细文本"""
        if self.message_segment:
            self.processed_plain_text = await self._process_message_segments(self.message_segment)

    def to_dict(self):
        ret = super().to_dict()
        ret["message_info"]["user_info"] = self.chat_stream.user_info.to_dict()
        return ret

    def is_private_message(self) -> bool:
        """判断是否为私聊消息"""
        return self.message_info.group_info is None or self.message_info.group_info.group_id is None


@dataclass
class MessageSet:
    """消息集合类，可以存储多个发送消息"""

    def __init__(self, chat_stream: "ChatStream", message_id: str):
        self.chat_stream = chat_stream
        self.message_id = message_id
        self.messages: list[MessageSending] = []
        self.time = round(time.time(), 3)  # 保留3位小数

    def add_message(self, message: MessageSending) -> None:
        """添加消息到集合"""
        if not isinstance(message, MessageSending):
            raise TypeError("MessageSet只能添加MessageSending类型的消息")
        self.messages.append(message)
        self.messages.sort(key=lambda x: x.message_info.time)  # type: ignore

    def get_message_by_index(self, index: int) -> Optional[MessageSending]:
        """通过索引获取消息"""
        return self.messages[index] if 0 <= index < len(self.messages) else None

    def get_message_by_time(self, target_time: float) -> Optional[MessageSending]:
        """获取最接近指定时间的消息"""
        if not self.messages:
            return None

        left, right = 0, len(self.messages) - 1
        while left < right:
            mid = (left + right) // 2
            if self.messages[mid].message_info.time < target_time:  # type: ignore
                left = mid + 1
            else:
                right = mid

        return self.messages[left]

    def clear_messages(self) -> None:
        """清空所有消息"""
        self.messages.clear()

    def remove_message(self, message: MessageSending) -> bool:
        """移除指定消息"""
        if message in self.messages:
            self.messages.remove(message)
            return True
        return False

    def __str__(self) -> str:
        return f"MessageSet(id={self.message_id}, count={len(self.messages)})"

    def __len__(self) -> int:
        return len(self.messages)


def message_recv_from_dict(message_dict: dict) -> MessageRecv:
    return MessageRecv(message_dict)


def message_from_db_dict(db_dict: dict) -> MessageRecv:
    """从数据库字典创建MessageRecv实例"""
    # 转换扁平的数据库字典为嵌套结构
    message_info_dict = {
        "platform": db_dict.get("chat_info_platform"),
        "message_id": db_dict.get("message_id"),
        "time": db_dict.get("time"),
        "group_info": {
            "platform": db_dict.get("chat_info_group_platform"),
            "group_id": db_dict.get("chat_info_group_id"),
            "group_name": db_dict.get("chat_info_group_name"),
        },
        "user_info": {
            "platform": db_dict.get("user_platform"),
            "user_id": db_dict.get("user_id"),
            "user_nickname": db_dict.get("user_nickname"),
            "user_cardname": db_dict.get("user_cardname"),
        },
    }

    processed_text = db_dict.get("processed_plain_text", "")

    # 构建 MessageRecv 需要的字典
    recv_dict = {
        "message_info": message_info_dict,
        "message_segment": {"type": "text", "data": processed_text},  # 从纯文本重建消息段
        "raw_message": None,  # 数据库中未存储原始消息
        "processed_plain_text": processed_text,
    }

    # 创建 MessageRecv 实例
    msg = MessageRecv(recv_dict)

    # 从数据库字典中填充其他可选字段
    msg.interest_value = db_dict.get("interest_value", 0.0)
    msg.is_mentioned = db_dict.get("is_mentioned")
    msg.priority_mode = db_dict.get("priority_mode", "interest")
    msg.priority_info = db_dict.get("priority_info")
    msg.is_emoji = db_dict.get("is_emoji", False)
    msg.is_picid = db_dict.get("is_picid", False)

    return msg
