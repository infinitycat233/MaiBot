from typing import AsyncGenerator, Dict, List, Optional, Union
from dataclasses import dataclass
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk


@dataclass
class ChatMessage:
    """聊天消息数据类"""

    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


class AsyncOpenAIClient:
    """异步OpenAI客户端，支持流式传输"""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        """
        初始化客户端

        Args:
            api_key: OpenAI API密钥
            base_url: 可选的API基础URL，用于自定义端点
        """
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=10.0,  # 设置60秒的全局超时
        )

    async def chat_completion(
        self,
        messages: List[Union[ChatMessage, Dict[str, str]]],
        model: str = "gpt-3.5-turbo",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> ChatCompletion:
        """
        非流式聊天完成

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Returns:
            完整的聊天回复
        """
        # 转换消息格式
        formatted_messages = []
        for msg in messages:
            if isinstance(msg, ChatMessage):
                formatted_messages.append(msg.to_dict())
            else:
                formatted_messages.append(msg)

        extra_body = {}
        if kwargs.get("enable_thinking") is not None:
            extra_body["enable_thinking"] = kwargs.pop("enable_thinking")
        if kwargs.get("thinking_budget") is not None:
            extra_body["thinking_budget"] = kwargs.pop("thinking_budget")

        response = await self.client.chat.completions.create(
            model=model,
            messages=formatted_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            extra_body=extra_body if extra_body else None,
            **kwargs,
        )

        return response

    async def chat_completion_stream(
        self,
        messages: List[Union[ChatMessage, Dict[str, str]]],
        model: str = "gpt-3.5-turbo",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """
        流式聊天完成

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Yields:
            ChatCompletionChunk: 流式响应块
        """
        # 转换消息格式
        formatted_messages = []
        for msg in messages:
            if isinstance(msg, ChatMessage):
                formatted_messages.append(msg.to_dict())
            else:
                formatted_messages.append(msg)

        extra_body = {}
        if kwargs.get("enable_thinking") is not None:
            extra_body["enable_thinking"] = kwargs.pop("enable_thinking")
        if kwargs.get("thinking_budget") is not None:
            extra_body["thinking_budget"] = kwargs.pop("thinking_budget")

        stream = await self.client.chat.completions.create(
            model=model,
            messages=formatted_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            extra_body=extra_body if extra_body else None,
            **kwargs,
        )

        async for chunk in stream:
            yield chunk

    async def get_stream_content(
        self,
        messages: List[Union[ChatMessage, Dict[str, str]]],
        model: str = "gpt-3.5-turbo",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        获取流式内容（只返回文本内容）

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Yields:
            str: 文本内容片段
        """
        async for chunk in self.chat_completion_stream(
            messages=messages, model=model, temperature=temperature, max_tokens=max_tokens, **kwargs
        ):
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def collect_stream_response(
        self,
        messages: List[Union[ChatMessage, Dict[str, str]]],
        model: str = "gpt-3.5-turbo",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> str:
        """
        收集完整的流式响应

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Returns:
            str: 完整的响应文本
        """
        full_response = ""
        async for content in self.get_stream_content(
            messages=messages, model=model, temperature=temperature, max_tokens=max_tokens, **kwargs
        ):
            full_response += content

        return full_response

    async def close(self):
        """关闭客户端"""
        await self.client.close()

    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.close()


class ConversationManager:
    """对话管理器，用于管理对话历史"""

    def __init__(self, client: AsyncOpenAIClient, system_prompt: Optional[str] = None):
        """
        初始化对话管理器

        Args:
            client: OpenAI客户端实例
            system_prompt: 系统提示词
        """
        self.client = client
        self.messages: List[ChatMessage] = []

        if system_prompt:
            self.messages.append(ChatMessage(role="system", content=system_prompt))

    def add_user_message(self, content: str):
        """添加用户消息"""
        self.messages.append(ChatMessage(role="user", content=content))

    def add_assistant_message(self, content: str):
        """添加助手消息"""
        self.messages.append(ChatMessage(role="assistant", content=content))

    async def send_message_stream(
        self, content: str, model: str = "gpt-3.5-turbo", **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        发送消息并获取流式响应

        Args:
            content: 用户消息内容
            model: 模型名称
            **kwargs: 其他参数

        Yields:
            str: 响应内容片段
        """
        self.add_user_message(content)

        response_content = ""
        async for chunk in self.client.get_stream_content(messages=self.messages, model=model, **kwargs):
            response_content += chunk
            yield chunk

        self.add_assistant_message(response_content)

    async def send_message(self, content: str, model: str = "gpt-3.5-turbo", **kwargs) -> str:
        """
        发送消息并获取完整响应

        Args:
            content: 用户消息内容
            model: 模型名称
            **kwargs: 其他参数

        Returns:
            str: 完整响应
        """
        self.add_user_message(content)

        response = await self.client.chat_completion(messages=self.messages, model=model, **kwargs)

        response_content = response.choices[0].message.content
        self.add_assistant_message(response_content)

        return response_content

    def clear_history(self, keep_system: bool = True):
        """
        清除对话历史

        Args:
            keep_system: 是否保留系统消息
        """
        if keep_system and self.messages and self.messages[0].role == "system":
            self.messages = [self.messages[0]]
        else:
            self.messages = []

    def get_message_count(self) -> int:
        """获取消息数量"""
        return len(self.messages)

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """获取对话历史"""
        return [msg.to_dict() for msg in self.messages]
