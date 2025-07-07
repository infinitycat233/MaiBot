from typing import Tuple

# 导入新插件系统
from src.plugin_system import BaseAction, ActionActivationType, ChatMode

# 导入依赖的系统组件
from src.common.logger import get_logger

# 导入API模块 - 标准Python包方式
from src.plugin_system.apis import emoji_api
from src.plugins.built_in.core_actions.no_reply import NoReplyAction


logger = get_logger("core_actions")


class EmojiAction(BaseAction):
    """表情动作 - 发送表情包"""

    # 激活设置
    focus_activation_type = ActionActivationType.LLM_JUDGE
    normal_activation_type = ActionActivationType.RANDOM
    mode_enable = ChatMode.ALL
    parallel_action = True
    random_activation_probability = 0.2  # 默认值，可通过配置覆盖

    # 动作基本信息
    action_name = "emoji"
    action_description = "发送表情包辅助表达情绪"

    # LLM判断提示词
    llm_judge_prompt = """
    判定是否需要使用表情动作的条件：
    1. 用户明确要求使用表情包
    2. 这是一个适合表达强烈情绪的场合
    3. 不要发送太多表情包，如果你已经发送过多个表情包则回答"否"
    
    请回答"是"或"否"。
    """

    # 动作参数定义
    action_parameters = {"description": "文字描述你想要发送的表情包内容"}

    # 动作使用场景
    action_require = [
        "发送表情包辅助表达情绪",
        "表达情绪时可以选择使用",
        "不要连续发送，如果你已经发过[表情包]，就不要选择此动作",
    ]

    # 关联类型
    associated_types = ["emoji"]

    async def execute(self) -> Tuple[bool, str]:
        """执行表情动作"""
        logger.info(f"{self.log_prefix} 决定发送表情")

        try:
            # 1. 根据描述选择表情包
            description = self.action_data.get("description", "")
            emoji_result = await emoji_api.get_by_description(description)

            if not emoji_result:
                logger.warning(f"{self.log_prefix} 未找到匹配描述 '{description}' 的表情包")
                return False, f"未找到匹配 '{description}' 的表情包"

            emoji_base64, emoji_description, matched_emotion = emoji_result
            logger.info(f"{self.log_prefix} 找到表情包: {emoji_description}, 匹配情感: {matched_emotion}")

            # 使用BaseAction的便捷方法发送表情包
            success = await self.send_emoji(emoji_base64)

            if not success:
                logger.error(f"{self.log_prefix} 表情包发送失败")
                return False, "表情包发送失败"

            # 重置NoReplyAction的连续计数器
            NoReplyAction.reset_consecutive_count()

            return True, f"发送表情包: {emoji_description}"

        except Exception as e:
            logger.error(f"{self.log_prefix} 表情动作执行失败: {e}")
            return False, f"表情发送失败: {str(e)}"
