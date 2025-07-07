from src.llm_models.utils_model import LLMRequest
from src.config.config import global_config
from src.chat.message_receive.message import MessageThinking
from src.common.logger import get_logger
from src.person_info.person_info import PersonInfoManager, get_person_info_manager
from src.chat.utils.utils import process_llm_response
from src.plugin_system.apis import generator_api
from src.chat.focus_chat.memory_activator import MemoryActivator


logger = get_logger("normal_chat_response")


class NormalChatGenerator:
    def __init__(self):
        model_config_1 = global_config.model.replyer_1.copy()
        model_config_2 = global_config.model.replyer_2.copy()

        prob_first = global_config.chat.replyer_random_probability

        model_config_1["weight"] = prob_first
        model_config_2["weight"] = 1.0 - prob_first

        self.model_configs = [model_config_1, model_config_2]

        self.model_sum = LLMRequest(model=global_config.model.memory_summary, temperature=0.7, request_type="relation")
        self.memory_activator = MemoryActivator()

    async def generate_response(
        self,
        message: MessageThinking,
        available_actions=None,
    ):
        logger.info(
            f"NormalChat思考:{message.processed_plain_text[:30] + '...' if len(message.processed_plain_text) > 30 else message.processed_plain_text}"
        )
        person_id = PersonInfoManager.get_person_id(
            message.chat_stream.user_info.platform, message.chat_stream.user_info.user_id
        )
        person_info_manager = get_person_info_manager()
        person_name = await person_info_manager.get_value(person_id, "person_name")
        relation_info = await person_info_manager.get_value(person_id, "short_impression")
        reply_to_str = f"{person_name}:{message.processed_plain_text}"

        try:
            success, reply_set, prompt = await generator_api.generate_reply(
                chat_stream=message.chat_stream,
                reply_to=reply_to_str,
                relation_info=relation_info,
                available_actions=available_actions,
                enable_tool=global_config.tool.enable_in_normal_chat,
                model_configs=self.model_configs,
                request_type="normal.replyer",
                return_prompt=True,
            )

            if not success or not reply_set:
                logger.info(f"对 {message.processed_plain_text} 的回复生成失败")
                return None

            content = " ".join([item[1] for item in reply_set if item[0] == "text"])
            logger.debug(f"对 {message.processed_plain_text} 的回复：{content}")

            if content:
                logger.info(f"{global_config.bot.nickname}的备选回复是：{content}")
                content = process_llm_response(content)

            return content

        except Exception:
            logger.exception("生成回复时出错")
            return None
