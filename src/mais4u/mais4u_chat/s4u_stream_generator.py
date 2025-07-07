import os
from typing import AsyncGenerator
from src.llm_models.utils_model import LLMRequest
from src.mais4u.openai_client import AsyncOpenAIClient
from src.config.config import global_config
from src.chat.message_receive.message import MessageRecv
from src.mais4u.mais4u_chat.s4u_prompt import prompt_builder
from src.common.logger import get_logger
from src.person_info.person_info import PersonInfoManager, get_person_info_manager
import asyncio
import re


logger = get_logger("s4u_stream_generator")


class S4UStreamGenerator:
    def __init__(self):
        replyer_1_config = global_config.model.replyer_1
        provider = replyer_1_config.get("provider")
        if not provider:
            logger.error("`replyer_1` 在配置文件中缺少 `provider` 字段")
            raise ValueError("`replyer_1` 在配置文件中缺少 `provider` 字段")

        api_key = os.environ.get(f"{provider.upper()}_KEY")
        base_url = os.environ.get(f"{provider.upper()}_BASE_URL")

        if not api_key:
            logger.error(f"环境变量 {provider.upper()}_KEY 未设置")
            raise ValueError(f"环境变量 {provider.upper()}_KEY 未设置")

        self.client_1 = AsyncOpenAIClient(api_key=api_key, base_url=base_url)
        self.model_1_name = replyer_1_config.get("name")
        if not self.model_1_name:
            logger.error("`replyer_1` 在配置文件中缺少 `model_name` 字段")
            raise ValueError("`replyer_1` 在配置文件中缺少 `model_name` 字段")
        self.replyer_1_config = replyer_1_config

        self.model_sum = LLMRequest(model=global_config.model.memory_summary, temperature=0.7, request_type="relation")
        self.current_model_name = "unknown model"
        self.partial_response = ""

        # 正则表达式用于按句子切分，同时处理各种标点和边缘情况
        # 匹配常见的句子结束符，但会忽略引号内和数字中的标点
        self.sentence_split_pattern = re.compile(
            r'([^\s\w"\'([{]*["\'([{].*?["\'}\])][^\s\w"\'([{]*|'  # 匹配被引号/括号包裹的内容
            r'[^.。!?？！\n\r]+(?:[.。!?？！\n\r](?![\'"])|$))',  # 匹配直到句子结束符
            re.UNICODE | re.DOTALL,
        )

    async def generate_response(
        self, message: MessageRecv, previous_reply_context: str = ""
    ) -> AsyncGenerator[str, None]:
        """根据当前模型类型选择对应的生成函数"""
        # 从global_config中获取模型概率值并选择模型
        self.partial_response = ""
        current_client = self.client_1
        self.current_model_name = self.model_1_name

        person_id = PersonInfoManager.get_person_id(
            message.chat_stream.user_info.platform, message.chat_stream.user_info.user_id
        )
        person_info_manager = get_person_info_manager()
        person_name = await person_info_manager.get_value(person_id, "person_name")

        if message.chat_stream.user_info.user_nickname:
            sender_name = f"[{message.chat_stream.user_info.user_nickname}]（你叫ta{person_name}）"
        else:
            sender_name = f"用户({message.chat_stream.user_info.user_id})"

        # 构建prompt
        if previous_reply_context:
            message_txt = f"""
             你正在回复用户的消息，但中途被打断了。这是已有的对话上下文:
             [你已经对上一条消息说的话]: {previous_reply_context}
             ---
             [这是用户发来的新消息, 你需要结合上下文，对此进行回复]:
             {message.processed_plain_text}
             """
        else:
            message_txt = message.processed_plain_text

        prompt = await prompt_builder.build_prompt_normal(
            message=message,
            message_txt=message_txt,
            sender_name=sender_name,
            chat_stream=message.chat_stream,
        )

        logger.info(
            f"{self.current_model_name}思考:{message_txt[:30] + '...' if len(message_txt) > 30 else message_txt}"
        )  # noqa: E501

        extra_kwargs = {}
        if self.replyer_1_config.get("enable_thinking") is not None:
            extra_kwargs["enable_thinking"] = self.replyer_1_config.get("enable_thinking")
        if self.replyer_1_config.get("thinking_budget") is not None:
            extra_kwargs["thinking_budget"] = self.replyer_1_config.get("thinking_budget")

        async for chunk in self._generate_response_with_model(
            prompt, current_client, self.current_model_name, **extra_kwargs
        ):
            yield chunk

    async def _generate_response_with_model(
        self,
        prompt: str,
        client: AsyncOpenAIClient,
        model_name: str,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        print(prompt)

        buffer = ""
        delimiters = "，。！？,.!?\n\r"  # For final trimming
        punctuation_buffer = ""

        async for content in client.get_stream_content(
            messages=[{"role": "user", "content": prompt}], model=model_name, **kwargs
        ):
            buffer += content

            # 使用正则表达式匹配句子
            last_match_end = 0
            for match in self.sentence_split_pattern.finditer(buffer):
                sentence = match.group(0).strip()
                if sentence:
                    # 如果句子看起来完整（即不只是等待更多内容），则发送
                    if match.end(0) < len(buffer) or sentence.endswith(tuple(delimiters)):
                        # 检查是否只是一个标点符号
                        if sentence in [",", "，", ".", "。", "!", "！", "?", "？"]:
                            punctuation_buffer += sentence
                        else:
                            # 发送之前累积的标点和当前句子
                            to_yield = punctuation_buffer + sentence
                            if to_yield.endswith((",", "，")):
                                to_yield = to_yield.rstrip(",，")

                            self.partial_response += to_yield
                            yield to_yield
                            punctuation_buffer = ""  # 清空标点符号缓冲区
                            await asyncio.sleep(0)  # 允许其他任务运行

                        last_match_end = match.end(0)

            # 从缓冲区移除已发送的部分
            if last_match_end > 0:
                buffer = buffer[last_match_end:]

        # 发送缓冲区中剩余的任何内容
        to_yield = (punctuation_buffer + buffer).strip()
        if to_yield:
            if to_yield.endswith(("，", ",")):
                to_yield = to_yield.rstrip("，,")
            if to_yield:
                self.partial_response += to_yield
                yield to_yield
