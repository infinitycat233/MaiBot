"""
核心动作插件

将系统核心动作（reply、no_reply、emoji）转换为新插件系统格式
这是系统的内置插件，提供基础的聊天交互功能
"""

import random
import time
from typing import List, Tuple, Type

# 导入新插件系统
from src.plugin_system import BasePlugin, register_plugin, BaseAction, ComponentInfo, ActionActivationType, ChatMode
from src.plugin_system.base.config_types import ConfigField
from src.config.config import global_config

# 导入依赖的系统组件
from src.common.logger import get_logger

# 导入API模块 - 标准Python包方式
from src.plugin_system.apis import generator_api, message_api
from src.plugins.built_in.core_actions.no_reply import NoReplyAction
from src.plugins.built_in.core_actions.emoji import EmojiAction

logger = get_logger("core_actions")

# 常量定义
WAITING_TIME_THRESHOLD = 1200  # 等待新消息时间阈值，单位秒


class ReplyAction(BaseAction):
    """回复动作 - 参与聊天回复"""

    # 激活设置
    focus_activation_type = ActionActivationType.ALWAYS
    normal_activation_type = ActionActivationType.NEVER
    mode_enable = ChatMode.FOCUS
    parallel_action = False

    # 动作基本信息
    action_name = "reply"
    action_description = "参与聊天回复，发送文本进行表达"

    # 动作参数定义
    action_parameters = {
        "reply_to": "你要回复的对方的发言内容，格式：（用户名:发言内容），可以为none",
        "reason": "回复的原因",
    }

    # 动作使用场景
    action_require = ["你想要闲聊或者随便附和", "有人提到你", "如果你刚刚进行了回复，不要对同一个话题重复回应"]

    # 关联类型
    associated_types = ["text"]

    async def execute(self) -> Tuple[bool, str]:
        """执行回复动作"""
        logger.info(f"{self.log_prefix} 决定回复: {self.reasoning}")

        start_time = self.action_data.get("loop_start_time", time.time())

        try:
            success, reply_set = await generator_api.generate_reply(
                action_data=self.action_data,
                chat_id=self.chat_id,
                request_type="focus.replyer",
                enable_tool=global_config.tool.enable_in_focus_chat,
            )

            # 检查从start_time以来的新消息数量
            # 获取动作触发时间或使用默认值
            current_time = time.time()
            new_message_count = message_api.count_new_messages(
                chat_id=self.chat_id, start_time=start_time, end_time=current_time
            )

            # 根据新消息数量决定是否使用reply_to
            need_reply = new_message_count >= random.randint(2, 5)
            logger.info(
                f"{self.log_prefix} 从{start_time}到{current_time}共有{new_message_count}条新消息，{'使用' if need_reply else '不使用'}reply_to"
            )

            # 构建回复文本
            reply_text = ""
            first_replyed = False
            for reply_seg in reply_set:
                data = reply_seg[1]
                if not first_replyed:
                    if need_reply:
                        await self.send_text(content=data, reply_to=self.action_data.get("reply_to", ""), typing=False)
                        first_replyed = True
                    else:
                        await self.send_text(content=data, typing=False)
                        first_replyed = True
                else:
                    await self.send_text(content=data, typing=True)
                reply_text += data

            # 存储动作记录
            await self.store_action_info(
                action_build_into_prompt=False,
                action_prompt_display=reply_text,
                action_done=True,
            )

            # 重置NoReplyAction的连续计数器
            NoReplyAction.reset_consecutive_count()

            return success, reply_text

        except Exception as e:
            logger.error(f"{self.log_prefix} 回复动作执行失败: {e}")
            return False, f"回复失败: {str(e)}"


@register_plugin
class CoreActionsPlugin(BasePlugin):
    """核心动作插件

    系统内置插件，提供基础的聊天交互功能：
    - Reply: 回复动作
    - NoReply: 不回复动作
    - Emoji: 表情动作

    注意：插件基本信息优先从_manifest.json文件中读取
    """

    # 插件基本信息
    plugin_name = "core_actions"  # 内部标识符
    enable_plugin = True
    config_file_name = "config.toml"

    # 配置节描述
    config_section_descriptions = {
        "plugin": "插件启用配置",
        "components": "核心组件启用配置",
        "no_reply": "不回复动作配置（智能等待机制）",
    }

    # 配置Schema定义
    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="0.3.1", description="配置文件版本"),
        },
        "components": {
            "enable_reply": ConfigField(type=bool, default=True, description="是否启用'回复'动作"),
            "enable_no_reply": ConfigField(type=bool, default=True, description="是否启用'不回复'动作"),
            "enable_emoji": ConfigField(type=bool, default=True, description="是否启用'表情'动作"),
        },
        "no_reply": {
            "max_timeout": ConfigField(type=int, default=1200, description="最大等待超时时间（秒）"),
            "min_judge_interval": ConfigField(
                type=float, default=1.0, description="LLM判断的最小间隔时间（秒），防止过于频繁"
            ),
            "auto_exit_message_count": ConfigField(
                type=int, default=20, description="累计消息数量达到此阈值时自动结束等待"
            ),
            "random_probability": ConfigField(
                type=float, default=0.8, description="Focus模式下，随机选择不回复的概率（0.0到1.0）", example=0.8
            ),
            "skip_judge_when_tired": ConfigField(
                type=bool, default=True, description="当发言过多时是否启用跳过LLM判断机制"
            ),
            "frequency_check_window": ConfigField(
                type=int, default=600, description="回复频率检查窗口时间（秒）", example=600
            ),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""

        # --- 从配置动态设置Action/Command ---
        emoji_chance = global_config.normal_chat.emoji_chance
        EmojiAction.random_activation_probability = emoji_chance

        no_reply_probability = self.get_config("no_reply.random_probability", 0.8)
        NoReplyAction.random_activation_probability = no_reply_probability

        min_judge_interval = self.get_config("no_reply.min_judge_interval", 1.0)
        NoReplyAction._min_judge_interval = min_judge_interval

        auto_exit_message_count = self.get_config("no_reply.auto_exit_message_count", 20)
        NoReplyAction._auto_exit_message_count = auto_exit_message_count

        max_timeout = self.get_config("no_reply.max_timeout", 600)
        NoReplyAction._max_timeout = max_timeout

        skip_judge_when_tired = self.get_config("no_reply.skip_judge_when_tired", True)
        NoReplyAction._skip_judge_when_tired = skip_judge_when_tired

        # 新增：频率检测相关配置
        frequency_check_window = self.get_config("no_reply.frequency_check_window", 600)
        NoReplyAction._frequency_check_window = frequency_check_window

        # --- 根据配置注册组件 ---
        components = []
        if self.get_config("components.enable_reply", True):
            components.append((ReplyAction.get_action_info(), ReplyAction))
        if self.get_config("components.enable_no_reply", True):
            components.append((NoReplyAction.get_action_info(), NoReplyAction))
        if self.get_config("components.enable_emoji", True):
            components.append((EmojiAction.get_action_info(), EmojiAction))

        # components.append((DeepReplyAction.get_action_info(), DeepReplyAction))

        return components
