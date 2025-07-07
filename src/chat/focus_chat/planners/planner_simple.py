import json  # <--- 确保导入 json
import traceback
from typing import List, Dict, Any, Optional
from rich.traceback import install
from src.llm_models.utils_model import LLMRequest
from src.config.config import global_config
from src.chat.focus_chat.info.info_base import InfoBase
from src.chat.focus_chat.info.obs_info import ObsInfo
from src.chat.focus_chat.info.action_info import ActionInfo
from src.common.logger import get_logger
from src.chat.utils.prompt_builder import Prompt, global_prompt_manager
from src.chat.focus_chat.planners.action_manager import ActionManager
from json_repair import repair_json
from src.chat.focus_chat.planners.base_planner import BasePlanner
from src.chat.heart_flow.utils_chat import get_chat_type_and_target_info
from datetime import datetime

logger = get_logger("planner")

install(extra_lines=3)


def init_prompt():
    Prompt(
        """
{time_block}
{indentify_block}
你现在需要根据聊天内容，选择的合适的action来参与聊天。
{chat_context_description}，以下是具体的聊天内容：
{chat_content_block}
{moderation_prompt}
现在请你根据聊天内容选择合适的action:

{action_options_text}

请根据动作示例，以严格的 JSON 格式输出，且仅包含 JSON 内容：
""",
        "simple_planner_prompt",
    )

    Prompt(
        """
{time_block}
{indentify_block}
你现在需要根据聊天内容，选择的合适的action来参与聊天。
{chat_context_description}，以下是具体的聊天内容：
{chat_content_block}
{moderation_prompt}
现在请你选择合适的action:

{action_options_text}

请根据动作示例，以严格的 JSON 格式输出，且仅包含 JSON 内容：
""",
        "simple_planner_prompt_private",
    )

    Prompt(
        """
{action_require}
{{
    "action": "{action_name}",{action_parameters}
}}
""",
        "action_prompt",
    )

    Prompt(
        """
{action_require}
{{
    "action": "{action_name}",{action_parameters}
}}
""",
        "action_prompt_private",
    )


class ActionPlanner(BasePlanner):
    def __init__(self, log_prefix: str, action_manager: ActionManager):
        super().__init__(log_prefix, action_manager)
        # LLM规划器配置
        self.planner_llm = LLMRequest(
            model=global_config.model.planner,
            request_type="focus.planner",  # 用于动作规划
        )

        self.utils_llm = LLMRequest(
            model=global_config.model.utils_small,
            request_type="focus.planner",  # 用于动作规划
        )

    async def plan(
        self, all_plan_info: List[InfoBase], running_memorys: List[Dict[str, Any]], loop_start_time: float
    ) -> Dict[str, Any]:
        """
        规划器 (Planner): 使用LLM根据上下文决定做出什么动作。

        参数:
            all_plan_info: 所有计划信息
            running_memorys: 回忆信息
            loop_start_time: 循环开始时间
        """

        action = "no_reply"  # 默认动作
        reasoning = "规划器初始化默认"
        action_data = {}

        try:
            # 获取观察信息
            extra_info: list[str] = []

            extra_info = []
            observed_messages = []
            observed_messages_str = ""
            chat_type = "group"
            is_group_chat = True
            chat_id = None  # 添加chat_id变量

            for info in all_plan_info:
                if isinstance(info, ObsInfo):
                    observed_messages = info.get_talking_message()
                    observed_messages_str = info.get_talking_message_str_truncate_short()
                    chat_type = info.get_chat_type()
                    is_group_chat = chat_type == "group"
                    # 从ObsInfo中获取chat_id
                    chat_id = info.get_chat_id()
                else:
                    extra_info.append(info.get_processed_info())

            # 获取聊天类型和目标信息
            chat_target_info = None
            if chat_id:
                try:
                    # 重新获取更准确的聊天信息
                    is_group_chat_updated, chat_target_info = get_chat_type_and_target_info(chat_id)
                    # 如果获取成功，更新is_group_chat
                    if is_group_chat_updated is not None:
                        is_group_chat = is_group_chat_updated
                    logger.debug(
                        f"{self.log_prefix}获取到聊天信息 - 群聊: {is_group_chat}, 目标信息: {chat_target_info}"
                    )
                except Exception as e:
                    logger.warning(f"{self.log_prefix}获取聊天目标信息失败: {e}")
                    chat_target_info = None

            # 获取经过modify_actions处理后的最终可用动作集
            # 注意：动作的激活判定现在在主循环的modify_actions中完成
            # 使用Focus模式过滤动作
            current_available_actions_dict = self.action_manager.get_using_actions_for_mode("focus")

            # 获取完整的动作信息
            all_registered_actions = self.action_manager.get_registered_actions()
            current_available_actions = {}
            for action_name in current_available_actions_dict.keys():
                if action_name in all_registered_actions:
                    current_available_actions[action_name] = all_registered_actions[action_name]
                else:
                    logger.warning(f"{self.log_prefix}使用中的动作 {action_name} 未在已注册动作中找到")

            # 如果没有可用动作或只有no_reply动作，直接返回no_reply
            if not current_available_actions or (
                len(current_available_actions) == 1 and "no_reply" in current_available_actions
            ):
                action = "no_reply"
                reasoning = "没有可用的动作" if not current_available_actions else "只有no_reply动作可用，跳过规划"
                logger.info(f"{self.log_prefix}{reasoning}")
                self.action_manager.restore_actions()
                logger.debug(
                    f"{self.log_prefix}[focus]沉默后恢复到默认动作集, 当前可用: {list(self.action_manager.get_using_actions().keys())}"
                )
                return {
                    "action_result": {"action_type": action, "action_data": action_data, "reasoning": reasoning},
                    "observed_messages": observed_messages,
                }

            # --- 构建提示词 (调用修改后的 PromptBuilder 方法) ---
            prompt = await self.build_planner_prompt(
                is_group_chat=is_group_chat,  # <-- Pass HFC state
                chat_target_info=chat_target_info,  # <-- 传递获取到的聊天目标信息
                observed_messages_str=observed_messages_str,  # <-- Pass local variable
                current_available_actions=current_available_actions,  # <-- Pass determined actions
            )

            # --- 调用 LLM (普通文本生成) ---
            llm_content = None
            try:
                prompt = f"{prompt}"
                llm_content, (reasoning_content, _) = await self.planner_llm.generate_response_async(prompt=prompt)

                logger.info(f"{self.log_prefix}规划器原始提示词: {prompt}")
                logger.info(f"{self.log_prefix}规划器原始响应: {llm_content}")
                logger.info(f"{self.log_prefix}规划器推理: {reasoning_content}")

            except Exception as req_e:
                logger.error(f"{self.log_prefix}LLM 请求执行失败: {req_e}")
                reasoning = f"LLM 请求失败，你的模型出现问题: {req_e}"
                action = "no_reply"

            if llm_content:
                try:
                    fixed_json_string = repair_json(llm_content)
                    if isinstance(fixed_json_string, str):
                        try:
                            parsed_json = json.loads(fixed_json_string)
                        except json.JSONDecodeError as decode_error:
                            logger.error(f"JSON解析错误: {str(decode_error)}")
                            parsed_json = {}
                    else:
                        # 如果repair_json直接返回了字典对象，直接使用
                        parsed_json = fixed_json_string

                    # 处理repair_json可能返回列表的情况
                    if isinstance(parsed_json, list):
                        if parsed_json:
                            # 取列表中最后一个元素（通常是最完整的）
                            parsed_json = parsed_json[-1]
                            logger.warning(f"{self.log_prefix}LLM返回了多个JSON对象，使用最后一个: {parsed_json}")
                        else:
                            parsed_json = {}

                    # 确保parsed_json是字典
                    if not isinstance(parsed_json, dict):
                        logger.error(f"{self.log_prefix}解析后的JSON不是字典类型: {type(parsed_json)}")
                        parsed_json = {}

                    # 提取决策，提供默认值
                    extracted_action = parsed_json.get("action", "no_reply")
                    extracted_reasoning = ""

                    # 将所有其他属性添加到action_data
                    action_data = {}
                    for key, value in parsed_json.items():
                        if key not in ["action", "reasoning"]:
                            action_data[key] = value

                    action_data["loop_start_time"] = loop_start_time

                    # 对于reply动作不需要额外处理，因为相关字段已经在上面的循环中添加到action_data

                    if extracted_action not in current_available_actions:
                        logger.warning(
                            f"{self.log_prefix}LLM 返回了当前不可用或无效的动作: '{extracted_action}' (可用: {list(current_available_actions.keys())})，将强制使用 'no_reply'"
                        )
                        action = "no_reply"
                        reasoning = f"LLM 返回了当前不可用的动作 '{extracted_action}' (可用: {list(current_available_actions.keys())})。原始理由: {extracted_reasoning}"
                    else:
                        # 动作有效且可用
                        action = extracted_action
                        reasoning = extracted_reasoning

                except Exception as json_e:
                    logger.warning(f"{self.log_prefix}解析LLM响应JSON失败 {json_e}. LLM原始输出: '{llm_content}'")
                    traceback.print_exc()
                    reasoning = f"解析LLM响应JSON失败: {json_e}. 将使用默认动作 'no_reply'."
                    action = "no_reply"

        except Exception as outer_e:
            logger.error(f"{self.log_prefix}Planner 处理过程中发生意外错误，规划失败，将执行 no_reply: {outer_e}")
            traceback.print_exc()
            action = "no_reply"
            reasoning = f"Planner 内部处理错误: {outer_e}"

        # 恢复到默认动作集
        self.action_manager.restore_actions()
        logger.debug(
            f"{self.log_prefix}规划后恢复到默认动作集, 当前可用: {list(self.action_manager.get_using_actions().keys())}"
        )

        action_result = {"action_type": action, "action_data": action_data, "reasoning": reasoning}

        plan_result = {
            "action_result": action_result,
            "observed_messages": observed_messages,
            "action_prompt": prompt,
        }

        return plan_result

    async def build_planner_prompt(
        self,
        is_group_chat: bool,  # Now passed as argument
        chat_target_info: Optional[dict],  # Now passed as argument
        observed_messages_str: str,
        current_available_actions: Dict[str, ActionInfo],
    ) -> str:
        """构建 Planner LLM 的提示词 (获取模板并填充数据)"""
        try:
            chat_context_description = "你现在正在一个群聊中"
            chat_target_name = None  # Only relevant for private
            if not is_group_chat and chat_target_info:
                chat_target_name = (
                    chat_target_info.get("person_name") or chat_target_info.get("user_nickname") or "对方"
                )
                chat_context_description = f"你正在和 {chat_target_name} 私聊"

            chat_content_block = ""
            if observed_messages_str:
                chat_content_block = f"\n{observed_messages_str}"
            else:
                chat_content_block = "你还未开始聊天"

            action_options_block = ""
            # 根据聊天类型选择不同的动作prompt模板
            action_template_name = "action_prompt_private" if not is_group_chat else "action_prompt"

            for using_actions_name, using_actions_info in current_available_actions.items():
                using_action_prompt = await global_prompt_manager.get_prompt_async(action_template_name)

                if using_actions_info["parameters"]:
                    param_text = "\n"
                    for param_name, param_description in using_actions_info["parameters"].items():
                        param_text += f'    "{param_name}":"{param_description}"\n'
                    param_text = param_text.rstrip("\n")
                else:
                    param_text = ""

                require_text = ""
                for require_item in using_actions_info["require"]:
                    require_text += f"- {require_item}\n"
                require_text = require_text.rstrip("\n")

                # 根据模板类型决定是否包含description参数
                if action_template_name == "action_prompt_private":
                    # 私聊模板不包含description参数
                    using_action_prompt = using_action_prompt.format(
                        action_name=using_actions_name,
                        action_parameters=param_text,
                        action_require=require_text,
                    )
                else:
                    # 群聊模板包含description参数
                    using_action_prompt = using_action_prompt.format(
                        action_name=using_actions_name,
                        action_description=using_actions_info["description"],
                        action_parameters=param_text,
                        action_require=require_text,
                    )

                action_options_block += using_action_prompt

            # moderation_prompt_block = "请不要输出违法违规内容，不要输出色情，暴力，政治相关内容，如有敏感内容，请规避。"
            moderation_prompt_block = ""

            # 获取当前时间
            time_block = f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            bot_name = global_config.bot.nickname
            if global_config.bot.alias_names:
                bot_nickname = f",也有人叫你{','.join(global_config.bot.alias_names)}"
            else:
                bot_nickname = ""
            bot_core_personality = global_config.personality.personality_core
            indentify_block = f"你的名字是{bot_name}{bot_nickname}，你{bot_core_personality}："

            # 根据聊天类型选择不同的prompt模板
            template_name = "simple_planner_prompt_private" if not is_group_chat else "simple_planner_prompt"
            planner_prompt_template = await global_prompt_manager.get_prompt_async(template_name)
            prompt = planner_prompt_template.format(
                time_block=time_block,
                chat_context_description=chat_context_description,
                chat_content_block=chat_content_block,
                action_options_text=action_options_block,
                moderation_prompt=moderation_prompt_block,
                indentify_block=indentify_block,
            )
            return prompt

        except Exception as e:
            logger.error(f"构建 Planner 提示词时出错: {e}")
            logger.error(traceback.format_exc())
            return "构建 Planner Prompt 时出错"


init_prompt()
