"""
回复器API模块

提供回复器相关功能，采用标准Python包设计模式
使用方式：
    from src.plugin_system.apis import generator_api
    replyer = generator_api.get_replyer(chat_stream)
    success, reply_set = await generator_api.generate_reply(chat_stream, action_data, reasoning)
"""

import traceback
from typing import Tuple, Any, Dict, List, Optional
from src.common.logger import get_logger
from src.chat.replyer.default_generator import DefaultReplyer
from src.chat.message_receive.chat_stream import ChatStream
from src.chat.utils.utils import process_llm_response
from src.chat.replyer.replyer_manager import replyer_manager

logger = get_logger("generator_api")


# =============================================================================
# 回复器获取API函数
# =============================================================================


def get_replyer(
    chat_stream: Optional[ChatStream] = None,
    chat_id: Optional[str] = None,
    enable_tool: bool = False,
    model_configs: Optional[List[Dict[str, Any]]] = None,
    request_type: str = "replyer",
) -> Optional[DefaultReplyer]:
    """获取回复器对象

    优先使用chat_stream，如果没有则使用chat_id直接查找。
    使用 ReplyerManager 来管理实例，避免重复创建。

    Args:
        chat_stream: 聊天流对象（优先）
        chat_id: 聊天ID（实际上就是stream_id）
        model_configs: 模型配置列表
        request_type: 请求类型

    Returns:
        Optional[DefaultReplyer]: 回复器对象，如果获取失败则返回None
    """
    try:
        logger.debug(f"[GeneratorAPI] 正在获取回复器，chat_id: {chat_id}, chat_stream: {'有' if chat_stream else '无'}")
        return replyer_manager.get_replyer(
            chat_stream=chat_stream,
            chat_id=chat_id,
            model_configs=model_configs,
            request_type=request_type,
            enable_tool=enable_tool,
        )
    except Exception as e:
        logger.error(f"[GeneratorAPI] 获取回复器时发生意外错误: {e}", exc_info=True)
        traceback.print_exc()
        return None


# =============================================================================
# 回复生成API函数
# =============================================================================


async def generate_reply(
    chat_stream=None,
    chat_id: str = None,
    action_data: Dict[str, Any] = None,
    reply_to: str = "",
    relation_info: str = "",
    extra_info: str = "",
    available_actions: List[str] = None,
    enable_tool: bool = False,
    enable_splitter: bool = True,
    enable_chinese_typo: bool = True,
    return_prompt: bool = False,
    model_configs: Optional[List[Dict[str, Any]]] = None,
    request_type: str = "",
) -> Tuple[bool, List[Tuple[str, Any]]]:
    """生成回复

    Args:
        chat_stream: 聊天流对象（优先）
        action_data: 动作数据
        chat_id: 聊天ID（备用）
        enable_splitter: 是否启用消息分割器
        enable_chinese_typo: 是否启用错字生成器
        return_prompt: 是否返回提示词
    Returns:
        Tuple[bool, List[Tuple[str, Any]]]: (是否成功, 回复集合)
    """
    try:
        # 获取回复器
        replyer = get_replyer(
            chat_stream, chat_id, model_configs=model_configs, request_type=request_type, enable_tool=enable_tool
        )
        if not replyer:
            logger.error("[GeneratorAPI] 无法获取回复器")
            return False, []

        logger.info("[GeneratorAPI] 开始生成回复")

        # 调用回复器生成回复
        success, content, prompt = await replyer.generate_reply_with_context(
            reply_data=action_data or {},
            reply_to=reply_to,
            relation_info=relation_info,
            extra_info=extra_info,
            available_actions=available_actions,
        )

        reply_set = await process_human_text(content, enable_splitter, enable_chinese_typo)

        if success:
            logger.info(f"[GeneratorAPI] 回复生成成功，生成了 {len(reply_set)} 个回复项")
        else:
            logger.warning("[GeneratorAPI] 回复生成失败")

        if return_prompt:
            return success, reply_set or [], prompt
        else:
            return success, reply_set or []

    except Exception as e:
        logger.error(f"[GeneratorAPI] 生成回复时出错: {e}")
        return False, []


async def rewrite_reply(
    chat_stream=None,
    reply_data: Dict[str, Any] = None,
    chat_id: str = None,
    enable_splitter: bool = True,
    enable_chinese_typo: bool = True,
    model_configs: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, List[Tuple[str, Any]]]:
    """重写回复

    Args:
        chat_stream: 聊天流对象（优先）
        reply_data: 回复数据
        chat_id: 聊天ID（备用）
        enable_splitter: 是否启用消息分割器
        enable_chinese_typo: 是否启用错字生成器

    Returns:
        Tuple[bool, List[Tuple[str, Any]]]: (是否成功, 回复集合)
    """
    try:
        # 获取回复器
        replyer = get_replyer(chat_stream, chat_id, model_configs=model_configs)
        if not replyer:
            logger.error("[GeneratorAPI] 无法获取回复器")
            return False, []

        logger.info("[GeneratorAPI] 开始重写回复")

        # 调用回复器重写回复
        success, content = await replyer.rewrite_reply_with_context(reply_data=reply_data or {})

        reply_set = await process_human_text(content, enable_splitter, enable_chinese_typo)

        if success:
            logger.info(f"[GeneratorAPI] 重写回复成功，生成了 {len(reply_set)} 个回复项")
        else:
            logger.warning("[GeneratorAPI] 重写回复失败")

        return success, reply_set or []

    except Exception as e:
        logger.error(f"[GeneratorAPI] 重写回复时出错: {e}")
        return False, []


async def process_human_text(content: str, enable_splitter: bool, enable_chinese_typo: bool) -> List[Tuple[str, Any]]:
    """将文本处理为更拟人化的文本

    Args:
        content: 文本内容
        enable_splitter: 是否启用消息分割器
        enable_chinese_typo: 是否启用错字生成器
    """
    try:
        processed_response = process_llm_response(content, enable_splitter, enable_chinese_typo)

        reply_set = []
        for str in processed_response:
            reply_seg = ("text", str)
            reply_set.append(reply_seg)

        return reply_set

    except Exception as e:
        logger.error(f"[GeneratorAPI] 处理人形文本时出错: {e}")
        return []
