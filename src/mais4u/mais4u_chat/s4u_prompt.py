from src.config.config import global_config
from src.common.logger import get_logger
from src.chat.utils.prompt_builder import Prompt, global_prompt_manager
from src.chat.utils.chat_message_builder import build_readable_messages, get_raw_msg_before_timestamp_with_chat
import time
from src.chat.utils.utils import get_recent_group_speaker
from src.chat.memory_system.Hippocampus import hippocampus_manager
import random
from datetime import datetime
import asyncio
import ast

from src.person_info.person_info import get_person_info_manager
from src.person_info.relationship_manager import get_relationship_manager

logger = get_logger("prompt")


def init_prompt():
    Prompt("你正在qq群里聊天，下面是群里在聊的内容：", "chat_target_group1")
    Prompt("你正在和{sender_name}聊天，这是你们之前聊的内容：", "chat_target_private1")
    Prompt("在群里聊天", "chat_target_group2")
    Prompt("和{sender_name}私聊", "chat_target_private2")

    Prompt("\n你有以下这些**知识**：\n{prompt_info}\n请你**记住上面的知识**，之后可能会用到。\n", "knowledge_prompt")
    Prompt("\n关于你们的关系，你需要知道：\n{relation_info}\n", "relation_prompt")
    Prompt("你回想起了一些事情：\n{memory_info}\n", "memory_prompt")

    Prompt(
        """{identity_block}

{relation_info_block}
{memory_block}

你现在的主要任务是和 {sender_name} 聊天。同时，也有其他用户会参与你们的聊天，你可以参考他们的回复内容，但是你主要还是关注你和{sender_name}的聊天内容。

{background_dialogue_prompt}
--------------------------------
{time_block}
这是你和{sender_name}的对话，你们正在交流中：
{core_dialogue_prompt}

对方最新发送的内容：{message_txt}
回复可以简短一些。可以参考贴吧，知乎和微博的回复风格，回复不要浮夸，不要用夸张修辞，平淡一些。
不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。只输出回复内容，现在{sender_name}正在等待你的回复。
你的回复风格不要浮夸，有逻辑和条理，请你继续回复{sender_name}。
你的发言：
""",
        "s4u_prompt",  # New template for private CHAT chat
    )


class PromptBuilder:
    def __init__(self):
        self.prompt_built = ""
        self.activate_messages = ""

    async def build_identity_block(self) -> str:
        person_info_manager = get_person_info_manager()
        bot_person_id = person_info_manager.get_person_id("system", "bot_id")
        bot_name = global_config.bot.nickname
        if global_config.bot.alias_names:
            bot_nickname = f",也有人叫你{','.join(global_config.bot.alias_names)}"
        else:
            bot_nickname = ""
        short_impression = await person_info_manager.get_value(bot_person_id, "short_impression")
        try:
            if isinstance(short_impression, str) and short_impression.strip():
                short_impression = ast.literal_eval(short_impression)
            elif not short_impression:
                logger.warning("short_impression为空，使用默认值")
                short_impression = ["友好活泼", "人类"]
        except (ValueError, SyntaxError) as e:
            logger.error(f"解析short_impression失败: {e}, 原始值: {short_impression}")
            short_impression = ["友好活泼", "人类"]

        if not isinstance(short_impression, list) or len(short_impression) < 2:
            logger.warning(f"short_impression格式不正确: {short_impression}, 使用默认值")
            short_impression = ["友好活泼", "人类"]
        personality = short_impression[0]
        identity = short_impression[1]
        prompt_personality = personality + "，" + identity
        return f"你的名字是{bot_name}{bot_nickname}，你{prompt_personality}："

    async def build_relation_info(self, chat_stream) -> str:
        is_group_chat = bool(chat_stream.group_info)
        who_chat_in_group = []
        if is_group_chat:
            who_chat_in_group = get_recent_group_speaker(
                chat_stream.stream_id,
                (chat_stream.user_info.platform, chat_stream.user_info.user_id) if chat_stream.user_info else None,
                limit=global_config.chat.max_context_size,
            )
        elif chat_stream.user_info:
            who_chat_in_group.append(
                (chat_stream.user_info.platform, chat_stream.user_info.user_id, chat_stream.user_info.user_nickname)
            )

        relation_prompt = ""
        if global_config.relationship.enable_relationship and who_chat_in_group:
            relationship_manager = get_relationship_manager()
            relation_info_list = await asyncio.gather(
                *[relationship_manager.build_relationship_info(person) for person in who_chat_in_group]
            )
            relation_info = "".join(relation_info_list)
            if relation_info:
                relation_prompt = await global_prompt_manager.format_prompt(
                    "relation_prompt", relation_info=relation_info
                )
        return relation_prompt

    async def build_memory_block(self, text: str) -> str:
        related_memory = await hippocampus_manager.get_memory_from_text(
            text=text, max_memory_num=2, max_memory_length=2, max_depth=3, fast_retrieval=False
        )

        related_memory_info = ""
        if related_memory:
            for memory in related_memory:
                related_memory_info += memory[1]
            return await global_prompt_manager.format_prompt("memory_prompt", memory_info=related_memory_info)
        return ""

    def build_chat_history_prompts(self, chat_stream, message) -> (str, str):
        message_list_before_now = get_raw_msg_before_timestamp_with_chat(
            chat_id=chat_stream.stream_id,
            timestamp=time.time(),
            limit=100,
        )

        talk_type = message.message_info.platform + ":" + message.chat_stream.user_info.user_id

        core_dialogue_list = []
        background_dialogue_list = []
        bot_id = str(global_config.bot.qq_account)
        target_user_id = str(message.chat_stream.user_info.user_id)

        for msg_dict in message_list_before_now:
            try:
                msg_user_id = str(msg_dict.get("user_id"))
                if msg_user_id == bot_id:
                    if msg_dict.get("reply_to") and talk_type == msg_dict.get("reply_to"):
                        core_dialogue_list.append(msg_dict)
                    else:
                        background_dialogue_list.append(msg_dict)
                elif msg_user_id == target_user_id:
                    core_dialogue_list.append(msg_dict)
                else:
                    background_dialogue_list.append(msg_dict)
            except Exception as e:
                logger.error(f"无法处理历史消息记录: {msg_dict}, 错误: {e}")

        background_dialogue_prompt = ""
        if background_dialogue_list:
            latest_25_msgs = background_dialogue_list[-25:]
            background_dialogue_prompt_str = build_readable_messages(
                latest_25_msgs,
                merge_messages=True,
                timestamp_mode="normal_no_YMD",
                show_pic=False,
            )
            background_dialogue_prompt = f"这是其他用户的发言：\n{background_dialogue_prompt_str}"

        core_msg_str = ""
        if core_dialogue_list:
            core_dialogue_list = core_dialogue_list[-50:]

            first_msg = core_dialogue_list[0]
            start_speaking_user_id = first_msg.get("user_id")
            if start_speaking_user_id == bot_id:
                last_speaking_user_id = bot_id
                msg_seg_str = "你的发言：\n"
            else:
                start_speaking_user_id = target_user_id
                last_speaking_user_id = start_speaking_user_id
                msg_seg_str = "对方的发言：\n"

            msg_seg_str += f"{time.strftime('%H:%M:%S', time.localtime(first_msg.get('time')))}: {first_msg.get('processed_plain_text')}\n"

            all_msg_seg_list = []
            for msg in core_dialogue_list[1:]:
                speaker = msg.get("user_id")
                if speaker == last_speaking_user_id:
                    msg_seg_str += f"{time.strftime('%H:%M:%S', time.localtime(msg.get('time')))}: {msg.get('processed_plain_text')}\n"
                else:
                    msg_seg_str = f"{msg_seg_str}\n"
                    all_msg_seg_list.append(msg_seg_str)

                    if speaker == bot_id:
                        msg_seg_str = "你的发言：\n"
                    else:
                        msg_seg_str = "对方的发言：\n"

                    msg_seg_str += f"{time.strftime('%H:%M:%S', time.localtime(msg.get('time')))}: {msg.get('processed_plain_text')}\n"
                    last_speaking_user_id = speaker

            all_msg_seg_list.append(msg_seg_str)
            for msg in all_msg_seg_list:
                core_msg_str += msg

        return core_msg_str, background_dialogue_prompt

    async def build_prompt_normal(
        self,
        message,
        chat_stream,
        message_txt: str,
        sender_name: str = "某人",
    ) -> str:
        identity_block, relation_info_block, memory_block = await asyncio.gather(
            self.build_identity_block(), self.build_relation_info(chat_stream), self.build_memory_block(message_txt)
        )

        core_dialogue_prompt, background_dialogue_prompt = self.build_chat_history_prompts(chat_stream, message)

        time_block = f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        template_name = "s4u_prompt"

        prompt = await global_prompt_manager.format_prompt(
            template_name,
            identity_block=identity_block,
            time_block=time_block,
            relation_info_block=relation_info_block,
            memory_block=memory_block,
            sender_name=sender_name,
            core_dialogue_prompt=core_dialogue_prompt,
            background_dialogue_prompt=background_dialogue_prompt,
            message_txt=message_txt,
        )

        return prompt


def weighted_sample_no_replacement(items, weights, k) -> list:
    """
    加权且不放回地随机抽取k个元素。

    参数：
        items: 待抽取的元素列表
        weights: 每个元素对应的权重（与items等长，且为正数）
        k: 需要抽取的元素个数
    返回：
        selected: 按权重加权且不重复抽取的k个元素组成的列表

        如果 items 中的元素不足 k 个，就只会返回所有可用的元素

    实现思路：
        每次从当前池中按权重加权随机选出一个元素，选中后将其从池中移除，重复k次。
        这样保证了：
        1. count越大被选中概率越高
        2. 不会重复选中同一个元素
    """
    selected = []
    pool = list(zip(items, weights))
    for _ in range(min(k, len(pool))):
        total = sum(w for _, w in pool)
        r = random.uniform(0, total)
        upto = 0
        for idx, (item, weight) in enumerate(pool):
            upto += weight
            if upto >= r:
                selected.append(item)
                pool.pop(idx)
                break
    return selected


init_prompt()
prompt_builder = PromptBuilder()
