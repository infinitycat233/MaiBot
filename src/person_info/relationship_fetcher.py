from src.config.config import global_config
from src.llm_models.utils_model import LLMRequest
import time
import traceback
from src.common.logger import get_logger
from src.chat.utils.prompt_builder import Prompt, global_prompt_manager
from src.person_info.person_info import get_person_info_manager
from typing import List, Dict
from json_repair import repair_json
from src.chat.message_receive.chat_stream import get_chat_manager
import json


logger = get_logger("relationship_fetcher")


def init_real_time_info_prompts():
    """初始化实时信息提取相关的提示词"""
    relationship_prompt = """
<聊天记录>
{chat_observe_info}
</聊天记录>

{name_block}
现在，你想要回复{person_name}的消息，消息内容是：{target_message}。请根据聊天记录和你要回复的消息，从你对{person_name}的了解中提取有关的信息：
1.你需要提供你想要提取的信息具体是哪方面的信息，例如：年龄，性别，你们之间的交流方式，最近发生的事等等。
2.请注意，请不要重复调取相同的信息，已经调取的信息如下：
{info_cache_block}
3.如果当前聊天记录中没有需要查询的信息，或者现有信息已经足够回复，请返回{{"none": "不需要查询"}}

请以json格式输出，例如：

{{
    "info_type": "信息类型",
}}

请严格按照json输出格式，不要输出多余内容：
"""
    Prompt(relationship_prompt, "real_time_info_identify_prompt")

    fetch_info_prompt = """
    
{name_block}
以下是你在之前与{person_name}的交流中，产生的对{person_name}的了解：
{person_impression_block}
{points_text_block}

请从中提取用户"{person_name}"的有关"{info_type}"信息
请以json格式输出，例如：

{{
    {info_json_str}
}}

请严格按照json输出格式，不要输出多余内容：
"""
    Prompt(fetch_info_prompt, "real_time_fetch_person_info_prompt")


class RelationshipFetcher:
    def __init__(self, chat_id):
        self.chat_id = chat_id

        # 信息获取缓存：记录正在获取的信息请求
        self.info_fetching_cache: List[Dict[str, any]] = []

        # 信息结果缓存：存储已获取的信息结果，带TTL
        self.info_fetched_cache: Dict[str, Dict[str, any]] = {}
        # 结构：{person_id: {info_type: {"info": str, "ttl": int, "start_time": float, "person_name": str, "unknow": bool}}}

        # LLM模型配置
        self.llm_model = LLMRequest(
            model=global_config.model.relation,
            request_type="relation",
        )

        # 小模型用于即时信息提取
        self.instant_llm_model = LLMRequest(
            model=global_config.model.utils_small,
            request_type="relation.instant",
        )

        name = get_chat_manager().get_stream_name(self.chat_id)
        self.log_prefix = f"[{name}] 实时信息"

    def _cleanup_expired_cache(self):
        """清理过期的信息缓存"""
        for person_id in list(self.info_fetched_cache.keys()):
            for info_type in list(self.info_fetched_cache[person_id].keys()):
                self.info_fetched_cache[person_id][info_type]["ttl"] -= 1
                if self.info_fetched_cache[person_id][info_type]["ttl"] <= 0:
                    del self.info_fetched_cache[person_id][info_type]
            if not self.info_fetched_cache[person_id]:
                del self.info_fetched_cache[person_id]

    async def build_relation_info(self, person_id, target_message, chat_history):
        # 清理过期的信息缓存
        self._cleanup_expired_cache()

        person_info_manager = get_person_info_manager()
        person_name = await person_info_manager.get_value(person_id, "person_name")
        short_impression = await person_info_manager.get_value(person_id, "short_impression")

        info_type = await self._build_fetch_query(person_id, target_message, chat_history)
        if info_type:
            await self._extract_single_info(person_id, info_type, person_name)

        relation_info = self._organize_known_info()
        relation_info = f"你对{person_name}的印象是：{short_impression}\n{relation_info}"
        return relation_info

    async def _build_fetch_query(self, person_id, target_message, chat_history):
        nickname_str = ",".join(global_config.bot.alias_names)
        name_block = f"你的名字是{global_config.bot.nickname},你的昵称有{nickname_str}，有人也会用这些昵称称呼你。"
        person_info_manager = get_person_info_manager()
        person_name = await person_info_manager.get_value(person_id, "person_name")

        info_cache_block = self._build_info_cache_block()

        prompt = (await global_prompt_manager.get_prompt_async("real_time_info_identify_prompt")).format(
            chat_observe_info=chat_history,
            name_block=name_block,
            info_cache_block=info_cache_block,
            person_name=person_name,
            target_message=target_message,
        )

        try:
            logger.debug(f"{self.log_prefix} 信息识别prompt: \n{prompt}\n")
            content, _ = await self.llm_model.generate_response_async(prompt=prompt)

            if content:
                content_json = json.loads(repair_json(content))

                # 检查是否返回了不需要查询的标志
                if "none" in content_json:
                    logger.info(f"{self.log_prefix} LLM判断当前不需要查询任何信息：{content_json.get('none', '')}")
                    return None

                info_type = content_json.get("info_type")
                if info_type:
                    # 记录信息获取请求
                    self.info_fetching_cache.append(
                        {
                            "person_id": get_person_info_manager().get_person_id_by_person_name(person_name),
                            "person_name": person_name,
                            "info_type": info_type,
                            "start_time": time.time(),
                            "forget": False,
                        }
                    )

                    # 限制缓存大小
                    if len(self.info_fetching_cache) > 10:
                        self.info_fetching_cache.pop(0)

                    logger.info(f"{self.log_prefix} 识别到需要调取用户 {person_name} 的[{info_type}]信息")
                    return info_type
                else:
                    logger.warning(f"{self.log_prefix} LLM未返回有效的info_type。响应: {content}")

        except Exception as e:
            logger.error(f"{self.log_prefix} 执行信息识别LLM请求时出错: {e}")
            logger.error(traceback.format_exc())

        return None

    def _build_info_cache_block(self) -> str:
        """构建已获取信息的缓存块"""
        info_cache_block = ""
        if self.info_fetching_cache:
            # 对于每个(person_id, info_type)组合，只保留最新的记录
            latest_records = {}
            for info_fetching in self.info_fetching_cache:
                key = (info_fetching["person_id"], info_fetching["info_type"])
                if key not in latest_records or info_fetching["start_time"] > latest_records[key]["start_time"]:
                    latest_records[key] = info_fetching

            # 按时间排序并生成显示文本
            sorted_records = sorted(latest_records.values(), key=lambda x: x["start_time"])
            for info_fetching in sorted_records:
                info_cache_block += (
                    f"你已经调取了[{info_fetching['person_name']}]的[{info_fetching['info_type']}]信息\n"
                )
        return info_cache_block

    async def _extract_single_info(self, person_id: str, info_type: str, person_name: str):
        """提取单个信息类型

        Args:
            person_id: 用户ID
            info_type: 信息类型
            person_name: 用户名
        """
        start_time = time.time()
        person_info_manager = get_person_info_manager()

        # 首先检查 info_list 缓存
        info_list = await person_info_manager.get_value(person_id, "info_list") or []
        cached_info = None

        # 查找对应的 info_type
        for info_item in info_list:
            if info_item.get("info_type") == info_type:
                cached_info = info_item.get("info_content")
                logger.debug(f"{self.log_prefix} 在info_list中找到 {person_name} 的 {info_type} 信息: {cached_info}")
                break

        # 如果缓存中有信息，直接使用
        if cached_info:
            if person_id not in self.info_fetched_cache:
                self.info_fetched_cache[person_id] = {}

            self.info_fetched_cache[person_id][info_type] = {
                "info": cached_info,
                "ttl": 2,
                "start_time": start_time,
                "person_name": person_name,
                "unknow": cached_info == "none",
            }
            logger.info(f"{self.log_prefix} 记得 {person_name} 的 {info_type}: {cached_info}")
            return

        # 如果缓存中没有，尝试从用户档案中提取
        try:
            person_impression = await person_info_manager.get_value(person_id, "impression")
            points = await person_info_manager.get_value(person_id, "points")

            # 构建印象信息块
            if person_impression:
                person_impression_block = (
                    f"<对{person_name}的总体了解>\n{person_impression}\n</对{person_name}的总体了解>"
                )
            else:
                person_impression_block = ""

            # 构建要点信息块
            if points:
                points_text = "\n".join([f"{point[2]}:{point[0]}" for point in points])
                points_text_block = f"<对{person_name}的近期了解>\n{points_text}\n</对{person_name}的近期了解>"
            else:
                points_text_block = ""

            # 如果完全没有用户信息
            if not points_text_block and not person_impression_block:
                if person_id not in self.info_fetched_cache:
                    self.info_fetched_cache[person_id] = {}
                self.info_fetched_cache[person_id][info_type] = {
                    "info": "none",
                    "ttl": 2,
                    "start_time": start_time,
                    "person_name": person_name,
                    "unknow": True,
                }
                logger.info(f"{self.log_prefix} 完全不认识 {person_name}")
                await self._save_info_to_cache(person_id, info_type, "none")
                return

            # 使用LLM提取信息
            nickname_str = ",".join(global_config.bot.alias_names)
            name_block = f"你的名字是{global_config.bot.nickname},你的昵称有{nickname_str}，有人也会用这些昵称称呼你。"

            prompt = (await global_prompt_manager.get_prompt_async("real_time_fetch_person_info_prompt")).format(
                name_block=name_block,
                info_type=info_type,
                person_impression_block=person_impression_block,
                person_name=person_name,
                info_json_str=f'"{info_type}": "有关{info_type}的信息内容"',
                points_text_block=points_text_block,
            )

            # 使用小模型进行即时提取
            content, _ = await self.instant_llm_model.generate_response_async(prompt=prompt)

            if content:
                content_json = json.loads(repair_json(content))
                if info_type in content_json:
                    info_content = content_json[info_type]
                    is_unknown = info_content == "none" or not info_content

                    # 保存到运行时缓存
                    if person_id not in self.info_fetched_cache:
                        self.info_fetched_cache[person_id] = {}
                    self.info_fetched_cache[person_id][info_type] = {
                        "info": "unknow" if is_unknown else info_content,
                        "ttl": 3,
                        "start_time": start_time,
                        "person_name": person_name,
                        "unknow": is_unknown,
                    }

                    # 保存到持久化缓存 (info_list)
                    await self._save_info_to_cache(person_id, info_type, info_content if not is_unknown else "none")

                    if not is_unknown:
                        logger.info(f"{self.log_prefix} 思考得到，{person_name} 的 {info_type}: {info_content}")
                    else:
                        logger.info(f"{self.log_prefix} 思考了也不知道{person_name} 的 {info_type} 信息")
            else:
                logger.warning(f"{self.log_prefix} 小模型返回空结果，获取 {person_name} 的 {info_type} 信息失败。")

        except Exception as e:
            logger.error(f"{self.log_prefix} 执行信息提取时出错: {e}")
            logger.error(traceback.format_exc())

    def _organize_known_info(self) -> str:
        """组织已知的用户信息为字符串

        Returns:
            str: 格式化的用户信息字符串
        """
        persons_infos_str = ""

        if self.info_fetched_cache:
            persons_with_known_info = []  # 有已知信息的人员
            persons_with_unknown_info = []  # 有未知信息的人员

            for person_id in self.info_fetched_cache:
                person_known_infos = []
                person_unknown_infos = []
                person_name = ""

                for info_type in self.info_fetched_cache[person_id]:
                    person_name = self.info_fetched_cache[person_id][info_type]["person_name"]
                    if not self.info_fetched_cache[person_id][info_type]["unknow"]:
                        info_content = self.info_fetched_cache[person_id][info_type]["info"]
                        person_known_infos.append(f"[{info_type}]：{info_content}")
                    else:
                        person_unknown_infos.append(info_type)

                # 如果有已知信息，添加到已知信息列表
                if person_known_infos:
                    known_info_str = "；".join(person_known_infos) + "；"
                    persons_with_known_info.append((person_name, known_info_str))

                # 如果有未知信息，添加到未知信息列表
                if person_unknown_infos:
                    persons_with_unknown_info.append((person_name, person_unknown_infos))

            # 先输出有已知信息的人员
            for person_name, known_info_str in persons_with_known_info:
                persons_infos_str += f"你对 {person_name} 的了解：{known_info_str}\n"

            # 统一处理未知信息，避免重复的警告文本
            if persons_with_unknown_info:
                unknown_persons_details = []
                for person_name, unknown_types in persons_with_unknown_info:
                    unknown_types_str = "、".join(unknown_types)
                    unknown_persons_details.append(f"{person_name}的[{unknown_types_str}]")

                if len(unknown_persons_details) == 1:
                    persons_infos_str += (
                        f"你不了解{unknown_persons_details[0]}信息，不要胡乱回答，可以直接说不知道或忘记了；\n"
                    )
                else:
                    unknown_all_str = "、".join(unknown_persons_details)
                    persons_infos_str += f"你不了解{unknown_all_str}等信息，不要胡乱回答，可以直接说不知道或忘记了；\n"

        return persons_infos_str

    async def _save_info_to_cache(self, person_id: str, info_type: str, info_content: str):
        """将提取到的信息保存到 person_info 的 info_list 字段中

        Args:
            person_id: 用户ID
            info_type: 信息类型
            info_content: 信息内容
        """
        try:
            person_info_manager = get_person_info_manager()

            # 获取现有的 info_list
            info_list = await person_info_manager.get_value(person_id, "info_list") or []

            # 查找是否已存在相同 info_type 的记录
            found_index = -1
            for i, info_item in enumerate(info_list):
                if isinstance(info_item, dict) and info_item.get("info_type") == info_type:
                    found_index = i
                    break

            # 创建新的信息记录
            new_info_item = {
                "info_type": info_type,
                "info_content": info_content,
            }

            if found_index >= 0:
                # 更新现有记录
                info_list[found_index] = new_info_item
                logger.info(f"{self.log_prefix} [缓存更新] 更新 {person_id} 的 {info_type} 信息缓存")
            else:
                # 添加新记录
                info_list.append(new_info_item)
                logger.info(f"{self.log_prefix} [缓存保存] 新增 {person_id} 的 {info_type} 信息缓存")

            # 保存更新后的 info_list
            await person_info_manager.update_one_field(person_id, "info_list", info_list)

        except Exception as e:
            logger.error(f"{self.log_prefix} [缓存保存] 保存信息到缓存失败: {e}")
            logger.error(traceback.format_exc())


class RelationshipFetcherManager:
    """关系提取器管理器

    管理不同 chat_id 的 RelationshipFetcher 实例
    """

    def __init__(self):
        self._fetchers: Dict[str, RelationshipFetcher] = {}

    def get_fetcher(self, chat_id: str) -> RelationshipFetcher:
        """获取或创建指定 chat_id 的 RelationshipFetcher

        Args:
            chat_id: 聊天ID

        Returns:
            RelationshipFetcher: 关系提取器实例
        """
        if chat_id not in self._fetchers:
            self._fetchers[chat_id] = RelationshipFetcher(chat_id)
        return self._fetchers[chat_id]

    def remove_fetcher(self, chat_id: str):
        """移除指定 chat_id 的 RelationshipFetcher

        Args:
            chat_id: 聊天ID
        """
        if chat_id in self._fetchers:
            del self._fetchers[chat_id]

    def clear_all(self):
        """清空所有 RelationshipFetcher"""
        self._fetchers.clear()

    def get_active_chat_ids(self) -> List[str]:
        """获取所有活跃的 chat_id 列表"""
        return list(self._fetchers.keys())


# 全局管理器实例
relationship_fetcher_manager = RelationshipFetcherManager()


init_real_time_info_prompts()
