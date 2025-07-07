import time
import heapq
import math
from typing import List, Dict, Optional
from ..message_receive.message import MessageRecv
from src.common.logger import get_logger

logger = get_logger("normal_chat")


class PrioritizedMessage:
    """带有优先级的消息对象"""

    def __init__(self, message: MessageRecv, interest_scores: List[float], is_vip: bool = False):
        self.message = message
        self.arrival_time = time.time()
        self.interest_scores = interest_scores
        self.is_vip = is_vip
        self.priority = self.calculate_priority()

    def calculate_priority(self, decay_rate: float = 0.01) -> float:
        """
        计算优先级分数。
        优先级 = 兴趣分 * exp(-衰减率 * 消息年龄)
        """
        age = time.time() - self.arrival_time
        decay_factor = math.exp(-decay_rate * age)
        priority = sum(self.interest_scores) + decay_factor
        return priority

    def __lt__(self, other: "PrioritizedMessage") -> bool:
        """用于堆排序的比较函数，我们想要一个最大堆，所以用 >"""
        return self.priority > other.priority


class PriorityManager:
    """
    管理消息队列，根据优先级选择消息进行处理。
    """

    def __init__(self, interest_dict: Dict[str, float], normal_queue_max_size: int = 5):
        self.vip_queue: List[PrioritizedMessage] = []  # VIP 消息队列 (最大堆)
        self.normal_queue: List[PrioritizedMessage] = []  # 普通消息队列 (最大堆)
        self.interest_dict = interest_dict if interest_dict is not None else {}
        self.normal_queue_max_size = normal_queue_max_size

    def _get_interest_score(self, user_id: str) -> float:
        """获取用户的兴趣分，默认为1.0"""
        return self.interest_dict.get("interests", {}).get(user_id, 1.0)

    def add_message(self, message: MessageRecv, interest_score: Optional[float] = None):
        """
        添加新消息到合适的队列中。
        """
        user_id = message.message_info.user_info.user_id
        is_vip = message.priority_info.get("message_type") == "vip" if message.priority_info else False
        message_priority = message.priority_info.get("message_priority", 0.0) if message.priority_info else 0.0

        p_message = PrioritizedMessage(message, [interest_score, message_priority], is_vip)

        if is_vip:
            heapq.heappush(self.vip_queue, p_message)
            logger.debug(f"消息来自VIP用户 {user_id}, 已添加到VIP队列. 当前VIP队列长度: {len(self.vip_queue)}")
        else:
            if len(self.normal_queue) >= self.normal_queue_max_size:
                # 如果队列已满，只在消息优先级高于最低优先级消息时才添加
                if p_message.priority > self.normal_queue[0].priority:
                    heapq.heapreplace(self.normal_queue, p_message)
                    logger.debug(f"普通队列已满，但新消息优先级更高，已替换. 用户: {user_id}")
                else:
                    logger.debug(f"普通队列已满且新消息优先级较低，已忽略. 用户: {user_id}")
            else:
                heapq.heappush(self.normal_queue, p_message)
                logger.debug(
                    f"消息来自普通用户 {user_id}, 已添加到普通队列. 当前普通队列长度: {len(self.normal_queue)}"
                )

    def get_highest_priority_message(self) -> Optional[MessageRecv]:
        """
        从VIP和普通队列中获取当前最高优先级的消息。
        """
        # 更新所有消息的优先级
        for p_msg in self.vip_queue:
            p_msg.priority = p_msg.calculate_priority()
        for p_msg in self.normal_queue:
            p_msg.priority = p_msg.calculate_priority()

        # 重建堆
        heapq.heapify(self.vip_queue)
        heapq.heapify(self.normal_queue)

        vip_msg = self.vip_queue[0] if self.vip_queue else None
        normal_msg = self.normal_queue[0] if self.normal_queue else None

        if vip_msg:
            return heapq.heappop(self.vip_queue).message
        elif normal_msg:
            return heapq.heappop(self.normal_queue).message
        else:
            return None

    def is_empty(self) -> bool:
        """检查所有队列是否为空"""
        return not self.vip_queue and not self.normal_queue

    def get_queue_status(self) -> str:
        """获取队列状态信息"""
        return f"VIP队列: {len(self.vip_queue)}, 普通队列: {len(self.normal_queue)}"
