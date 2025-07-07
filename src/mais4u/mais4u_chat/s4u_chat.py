import asyncio
import time
import random
from typing import Optional, Dict, Tuple  # 导入类型提示
from maim_message import UserInfo, Seg
from src.common.logger import get_logger
from src.chat.message_receive.chat_stream import ChatStream, get_chat_manager
from .s4u_stream_generator import S4UStreamGenerator
from src.chat.message_receive.message import MessageSending, MessageRecv
from src.config.config import global_config
from src.common.message.api import get_global_api
from src.chat.message_receive.storage import MessageStorage


logger = get_logger("S4U_chat")


class MessageSenderContainer:
    """一个简单的容器，用于按顺序发送消息并模拟打字效果。"""

    def __init__(self, chat_stream: ChatStream, original_message: MessageRecv):
        self.chat_stream = chat_stream
        self.original_message = original_message
        self.queue = asyncio.Queue()
        self.storage = MessageStorage()
        self._task: Optional[asyncio.Task] = None
        self._paused_event = asyncio.Event()
        self._paused_event.set()  # 默认设置为非暂停状态

    async def add_message(self, chunk: str):
        """向队列中添加一个消息块。"""
        await self.queue.put(chunk)

    async def close(self):
        """表示没有更多消息了，关闭队列。"""
        await self.queue.put(None)  # Sentinel

    def pause(self):
        """暂停发送。"""
        self._paused_event.clear()

    def resume(self):
        """恢复发送。"""
        self._paused_event.set()

    def _calculate_typing_delay(self, text: str) -> float:
        """根据文本长度计算模拟打字延迟。"""
        chars_per_second = 15.0
        min_delay = 0.2
        max_delay = 2.0

        delay = len(text) / chars_per_second
        return max(min_delay, min(delay, max_delay))

    async def _send_worker(self):
        """从队列中取出消息并发送。"""
        while True:
            try:
                # This structure ensures that task_done() is called for every item retrieved,
                # even if the worker is cancelled while processing the item.
                chunk = await self.queue.get()
            except asyncio.CancelledError:
                break

            try:
                if chunk is None:
                    break

                # Check for pause signal *after* getting an item.
                await self._paused_event.wait()

                # delay = self._calculate_typing_delay(chunk)
                delay = 0.1
                await asyncio.sleep(delay)

                current_time = time.time()
                msg_id = f"{current_time}_{random.randint(1000, 9999)}"

                text_to_send = chunk
                if global_config.experimental.debug_show_chat_mode:
                    text_to_send += "ⁿ"

                message_segment = Seg(type="text", data=text_to_send)
                bot_message = MessageSending(
                    message_id=msg_id,
                    chat_stream=self.chat_stream,
                    bot_user_info=UserInfo(
                        user_id=global_config.bot.qq_account,
                        user_nickname=global_config.bot.nickname,
                        platform=self.original_message.message_info.platform,
                    ),
                    sender_info=self.original_message.message_info.user_info,
                    message_segment=message_segment,
                    reply=self.original_message,
                    is_emoji=False,
                    apply_set_reply_logic=True,
                    reply_to=f"{self.original_message.message_info.user_info.platform}:{self.original_message.message_info.user_info.user_id}",
                )

                await bot_message.process()

                await get_global_api().send_message(bot_message)
                logger.info(f"已将消息 '{text_to_send}' 发往平台 '{bot_message.message_info.platform}'")

                await self.storage.store_message(bot_message, self.chat_stream)

            except Exception as e:
                logger.error(f"[{self.chat_stream.get_stream_name()}] 消息发送或存储时出现错误: {e}", exc_info=True)

            finally:
                # CRUCIAL: Always call task_done() for any item that was successfully retrieved.
                self.queue.task_done()

    def start(self):
        """启动发送任务。"""
        if self._task is None:
            self._task = asyncio.create_task(self._send_worker())

    async def join(self):
        """等待所有消息发送完毕。"""
        if self._task:
            await self._task


class S4UChatManager:
    def __init__(self):
        self.s4u_chats: Dict[str, "S4UChat"] = {}

    def get_or_create_chat(self, chat_stream: ChatStream) -> "S4UChat":
        if chat_stream.stream_id not in self.s4u_chats:
            stream_name = get_chat_manager().get_stream_name(chat_stream.stream_id) or chat_stream.stream_id
            logger.info(f"Creating new S4UChat for stream: {stream_name}")
            self.s4u_chats[chat_stream.stream_id] = S4UChat(chat_stream)
        return self.s4u_chats[chat_stream.stream_id]


s4u_chat_manager = S4UChatManager()


def get_s4u_chat_manager() -> S4UChatManager:
    return s4u_chat_manager


class S4UChat:
    _MESSAGE_TIMEOUT_SECONDS = 60  # 普通消息存活时间（秒）

    def __init__(self, chat_stream: ChatStream):
        """初始化 S4UChat 实例。"""

        self.chat_stream = chat_stream
        self.stream_id = chat_stream.stream_id
        self.stream_name = get_chat_manager().get_stream_name(self.stream_id) or self.stream_id

        # 两个消息队列
        self._vip_queue = asyncio.PriorityQueue()
        self._normal_queue = asyncio.PriorityQueue()

        self._entry_counter = 0  # 保证FIFO的全局计数器
        self._new_message_event = asyncio.Event()  # 用于唤醒处理器

        self._processing_task = asyncio.create_task(self._message_processor())
        self._current_generation_task: Optional[asyncio.Task] = None
        # 当前消息的元数据：(队列类型, 优先级分数, 计数器, 消息对象)
        self._current_message_being_replied: Optional[Tuple[str, float, int, MessageRecv]] = None

        self._is_replying = False
        self.gpt = S4UStreamGenerator()
        self.interest_dict: Dict[str, float] = {}  # 用户兴趣分
        self.at_bot_priority_bonus = 100.0  # @机器人的优先级加成
        self.normal_queue_max_size = 50  # 普通队列最大容量
        logger.info(f"[{self.stream_name}] S4UChat with two-queue system initialized.")

    def _is_vip(self, message: MessageRecv) -> bool:
        """检查消息是否来自VIP用户。"""
        # 您需要修改此处或在配置文件中定义VIP用户
        vip_user_ids = ["1026294844"]
        vip_user_ids = [""]
        return message.message_info.user_info.user_id in vip_user_ids

    def _get_interest_score(self, user_id: str) -> float:
        """获取用户的兴趣分，默认为1.0"""
        return self.interest_dict.get(user_id, 1.0)

    def _calculate_base_priority_score(self, message: MessageRecv) -> float:
        """
        为消息计算基础优先级分数。分数越高，优先级越高。
        """
        score = 0.0
        # 如果消息 @ 了机器人，则增加一个很大的分数
        if f"@{global_config.bot.nickname}" in message.processed_plain_text or any(
            f"@{alias}" in message.processed_plain_text for alias in global_config.bot.alias_names
        ):
            score += self.at_bot_priority_bonus

        # 加上用户的固有兴趣分
        score += self._get_interest_score(message.message_info.user_info.user_id)
        return score

    async def add_message(self, message: MessageRecv) -> None:
        """根据VIP状态和中断逻辑将消息放入相应队列。"""
        is_vip = self._is_vip(message)
        new_priority_score = self._calculate_base_priority_score(message)

        should_interrupt = False
        if self._current_generation_task and not self._current_generation_task.done():
            if self._current_message_being_replied:
                current_queue, current_priority, _, current_msg = self._current_message_being_replied

                # 规则：VIP从不被打断
                if current_queue == "vip":
                    pass  # Do nothing

                # 规则：普通消息可以被打断
                elif current_queue == "normal":
                    # VIP消息可以打断普通消息
                    if is_vip:
                        should_interrupt = True
                        logger.info(f"[{self.stream_name}] VIP message received, interrupting current normal task.")
                    # 普通消息的内部打断逻辑
                    else:
                        new_sender_id = message.message_info.user_info.user_id
                        current_sender_id = current_msg.message_info.user_info.user_id
                        # 新消息优先级更高
                        if new_priority_score > current_priority:
                            should_interrupt = True
                            logger.info(f"[{self.stream_name}] New normal message has higher priority, interrupting.")
                        # 同用户，新消息的优先级不能更低
                        elif new_sender_id == current_sender_id and new_priority_score >= current_priority:
                            should_interrupt = True
                            logger.info(f"[{self.stream_name}] Same user sent new message, interrupting.")

        if should_interrupt:
            if self.gpt.partial_response:
                logger.warning(
                    f"[{self.stream_name}] Interrupting reply. Already generated: '{self.gpt.partial_response}'"
                )
            self._current_generation_task.cancel()

        # asyncio.PriorityQueue 是最小堆，所以我们存入分数的相反数
        # 这样，原始分数越高的消息，在队列中的优先级数字越小，越靠前
        item = (-new_priority_score, self._entry_counter, time.time(), message)

        if is_vip:
            await self._vip_queue.put(item)
            logger.info(f"[{self.stream_name}] VIP message added to queue.")
        else:
            # 应用普通队列的最大容量限制
            if self._normal_queue.qsize() >= self.normal_queue_max_size:
                # 队列已满，简单忽略新消息
                # 更复杂的逻辑（如替换掉队列中优先级最低的）对于 asyncio.PriorityQueue 来说实现复杂
                logger.debug(
                    f"[{self.stream_name}] Normal queue is full, ignoring new message from {message.message_info.user_info.user_id}"
                )
                return

            await self._normal_queue.put(item)

        self._entry_counter += 1
        self._new_message_event.set()  # 唤醒处理器

    async def _message_processor(self):
        """调度器：优先处理VIP队列，然后处理普通队列。"""
        while True:
            try:
                # 等待有新消息的信号，避免空转
                await self._new_message_event.wait()
                self._new_message_event.clear()

                # 优先处理VIP队列
                if not self._vip_queue.empty():
                    neg_priority, entry_count, _, message = self._vip_queue.get_nowait()
                    priority = -neg_priority
                    queue_name = "vip"
                # 其次处理普通队列
                elif not self._normal_queue.empty():
                    neg_priority, entry_count, timestamp, message = self._normal_queue.get_nowait()
                    priority = -neg_priority
                    # 检查普通消息是否超时
                    if time.time() - timestamp > self._MESSAGE_TIMEOUT_SECONDS:
                        logger.info(
                            f"[{self.stream_name}] Discarding stale normal message: {message.processed_plain_text[:20]}..."
                        )
                        self._normal_queue.task_done()
                        continue  # 处理下一条
                    queue_name = "normal"
                else:
                    continue  # 没有消息了，回去等事件

                self._current_message_being_replied = (queue_name, priority, entry_count, message)
                self._current_generation_task = asyncio.create_task(self._generate_and_send(message))

                try:
                    await self._current_generation_task
                except asyncio.CancelledError:
                    logger.info(
                        f"[{self.stream_name}] Reply generation was interrupted externally for {queue_name} message. The message will be discarded."
                    )
                    # 被中断的消息应该被丢弃，而不是重新排队，以响应最新的用户输入。
                    # 旧的重新入队逻辑会导致所有中断的消息最终都被回复。

                except Exception as e:
                    logger.error(f"[{self.stream_name}] _generate_and_send task error: {e}", exc_info=True)
                finally:
                    self._current_generation_task = None
                    self._current_message_being_replied = None
                    # 标记任务完成
                    if queue_name == "vip":
                        self._vip_queue.task_done()
                    else:
                        self._normal_queue.task_done()

                    # 检查是否还有任务，有则立即再次触发事件
                    if not self._vip_queue.empty() or not self._normal_queue.empty():
                        self._new_message_event.set()

            except asyncio.CancelledError:
                logger.info(f"[{self.stream_name}] Message processor is shutting down.")
                break
            except Exception as e:
                logger.error(f"[{self.stream_name}] Message processor main loop error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _generate_and_send(self, message: MessageRecv):
        """为单个消息生成文本和音频回复。整个过程可以被中断。"""
        self._is_replying = True
        sender_container = MessageSenderContainer(self.chat_stream, message)
        sender_container.start()

        try:
            logger.info(f"[S4U] 开始为消息生成文本和音频流: '{message.processed_plain_text[:30]}...'")

            # 1. 逐句生成文本、发送并播放音频
            gen = self.gpt.generate_response(message, "")
            async for chunk in gen:
                # 如果任务被取消，await 会在此处引发 CancelledError

                # a. 发送文本块
                await sender_container.add_message(chunk)

                # b. 为该文本块生成并播放音频
                # if chunk.strip():
                # audio_data = await self.audio_generator.generate(chunk)
                # player = MockAudioPlayer(audio_data)
                # await player.play()

            # 等待所有文本消息发送完成
            await sender_container.close()
            await sender_container.join()
            logger.info(f"[{self.stream_name}] 所有文本和音频块处理完毕。")

        except asyncio.CancelledError:
            logger.info(f"[{self.stream_name}] 回复流程（文本或音频）被中断。")
            raise  # 将取消异常向上传播
        except Exception as e:
            logger.error(f"[{self.stream_name}] 回复生成过程中出现错误: {e}", exc_info=True)
        finally:
            self._is_replying = False
            # 确保发送器被妥善关闭（即使已关闭，再次调用也是安全的）
            sender_container.resume()
            if not sender_container._task.done():
                await sender_container.close()
                await sender_container.join()
            logger.info(f"[{self.stream_name}] _generate_and_send 任务结束，资源已清理。")

    async def shutdown(self):
        """平滑关闭处理任务。"""
        logger.info(f"正在关闭 S4UChat: {self.stream_name}")

        # 取消正在运行的任务
        if self._current_generation_task and not self._current_generation_task.done():
            self._current_generation_task.cancel()

        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()

        # 等待任务响应取消
        try:
            await self._processing_task
        except asyncio.CancelledError:
            logger.info(f"处理任务已成功取消: {self.stream_name}")
