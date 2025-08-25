import asyncio
import concurrent.futures

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Tuple, List

from src.common.logger import get_logger
from src.common.database.database import db
from src.common.database.database_model import OnlineTime, LLMUsage, Messages
from src.manager.async_task_manager import AsyncTask
from src.manager.local_store_manager import local_storage

logger = get_logger("maibot_statistic")

# 统计数据的键
TOTAL_REQ_CNT = "total_requests"
TOTAL_COST = "total_cost"
REQ_CNT_BY_TYPE = "requests_by_type"
REQ_CNT_BY_USER = "requests_by_user"
REQ_CNT_BY_MODEL = "requests_by_model"
REQ_CNT_BY_MODULE = "requests_by_module"
IN_TOK_BY_TYPE = "in_tokens_by_type"
IN_TOK_BY_USER = "in_tokens_by_user"
IN_TOK_BY_MODEL = "in_tokens_by_model"
IN_TOK_BY_MODULE = "in_tokens_by_module"
OUT_TOK_BY_TYPE = "out_tokens_by_type"
OUT_TOK_BY_USER = "out_tokens_by_user"
OUT_TOK_BY_MODEL = "out_tokens_by_model"
OUT_TOK_BY_MODULE = "out_tokens_by_module"
TOTAL_TOK_BY_TYPE = "tokens_by_type"
TOTAL_TOK_BY_USER = "tokens_by_user"
TOTAL_TOK_BY_MODEL = "tokens_by_model"
TOTAL_TOK_BY_MODULE = "tokens_by_module"
COST_BY_TYPE = "costs_by_type"
COST_BY_USER = "costs_by_user"
COST_BY_MODEL = "costs_by_model"
COST_BY_MODULE = "costs_by_module"
TIME_COST_BY_TYPE = "time_costs_by_type"
TIME_COST_BY_USER = "time_costs_by_user"
TIME_COST_BY_MODEL = "time_costs_by_model"
TIME_COST_BY_MODULE = "time_costs_by_module"
AVG_TIME_COST_BY_TYPE = "avg_time_costs_by_type"
AVG_TIME_COST_BY_USER = "avg_time_costs_by_user"
AVG_TIME_COST_BY_MODEL = "avg_time_costs_by_model"
AVG_TIME_COST_BY_MODULE = "avg_time_costs_by_module"
STD_TIME_COST_BY_TYPE = "std_time_costs_by_type"
STD_TIME_COST_BY_USER = "std_time_costs_by_user"
STD_TIME_COST_BY_MODEL = "std_time_costs_by_model"
STD_TIME_COST_BY_MODULE = "std_time_costs_by_module"
ONLINE_TIME = "online_time"
TOTAL_MSG_CNT = "total_messages"
MSG_CNT_BY_CHAT = "messages_by_chat"


class OnlineTimeRecordTask(AsyncTask):
    """在线时间记录任务"""

    def __init__(self):
        super().__init__(task_name="Online Time Record Task", run_interval=60)

        self.record_id: int | None = None  # Changed to int for Peewee's default ID
        """记录ID"""

        self._init_database()  # 初始化数据库

    @staticmethod
    def _init_database():
        """初始化数据库"""
        with db.atomic():  # Use atomic operations for schema changes
            OnlineTime.create_table(safe=True)  # Creates table if it doesn't exist, Peewee handles indexes from model

    async def run(self):  # sourcery skip: use-named-expression
        try:
            current_time = datetime.now()
            extended_end_time = current_time + timedelta(minutes=1)

            if self.record_id:
                # 如果有记录，则更新结束时间
                query = OnlineTime.update(end_timestamp=extended_end_time).where(OnlineTime.id == self.record_id)  # type: ignore
                updated_rows = query.execute()
                if updated_rows == 0:
                    # Record might have been deleted or ID is stale, try to find/create
                    self.record_id = None  # Reset record_id to trigger find/create logic below

            if not self.record_id:  # Check again if record_id was reset or initially None
                # 如果没有记录，检查一分钟以内是否已有记录
                # Look for a record whose end_timestamp is recent enough to be considered ongoing
                recent_record = (
                    OnlineTime.select()
                    .where(OnlineTime.end_timestamp >= (current_time - timedelta(minutes=1)))  # type: ignore
                    .order_by(OnlineTime.end_timestamp.desc())
                    .first()
                )

                if recent_record:
                    # 如果有记录，则更新结束时间
                    self.record_id = recent_record.id
                    recent_record.end_timestamp = extended_end_time
                    recent_record.save()
                else:
                    # 若没有记录，则插入新的在线时间记录
                    new_record = OnlineTime.create(
                        timestamp=current_time.timestamp(),  # 添加此行
                        start_timestamp=current_time,
                        end_timestamp=extended_end_time,
                        duration=5,  # 初始时长为5分钟
                    )
                    self.record_id = new_record.id
        except Exception as e:
            logger.error(f"在线时间记录失败，错误信息：{e}")


def _format_online_time(online_seconds: int) -> str:
    """
    格式化在线时间
    :param online_seconds: 在线时间（秒）
    :return: 格式化后的在线时间字符串
    """
    total_online_time = timedelta(seconds=online_seconds)

    days = total_online_time.days
    hours = total_online_time.seconds // 3600
    minutes = (total_online_time.seconds // 60) % 60
    seconds = total_online_time.seconds % 60
    if days > 0:
        # 如果在线时间超过1天，则格式化为"X天X小时X分钟"
        return f"{total_online_time.days}天{hours}小时{minutes}分钟{seconds}秒"
    elif hours > 0:
        # 如果在线时间超过1小时，则格式化为"X小时X分钟X秒"
        return f"{hours}小时{minutes}分钟{seconds}秒"
    else:
        # 其他情况格式化为"X分钟X秒"
        return f"{minutes}分钟{seconds}秒"


class StatisticOutputTask(AsyncTask):
    """统计输出任务"""

    SEP_LINE = "-" * 84

    def __init__(self, record_file_path: str = "maibot_statistics.html"):
        # 延迟300秒启动，运行间隔300秒
        super().__init__(task_name="Statistics Data Output Task", wait_before_start=0, run_interval=300)

        self.name_mapping: Dict[str, Tuple[str, float]] = {}
        """
            联系人/群聊名称映射 {聊天ID: (联系人/群聊名称, 记录时间（timestamp）)}
            注：设计记录时间的目的是方便更新名称，使联系人/群聊名称保持最新
        """

        self.record_file_path: str = record_file_path
        """
        记录文件路径
        """

        now = datetime.now()
        if "deploy_time" in local_storage:
            # 如果存在部署时间，则使用该时间作为全量统计的起始时间
            deploy_time = datetime.fromtimestamp(local_storage["deploy_time"])  # type: ignore
        else:
            # 否则，使用最大时间范围，并记录部署时间为当前时间
            deploy_time = datetime(2000, 1, 1)
            local_storage["deploy_time"] = now.timestamp()

        self.stat_period: List[Tuple[str, timedelta, str]] = [
            ("all_time", now - deploy_time, "自部署以来"),  # 必须保留"all_time"
            ("last_7_days", timedelta(days=7), "最近7天"),
            ("last_3_days", timedelta(days=3), "最近3天"),
            ("last_24_hours", timedelta(days=1), "最近24小时"),
            ("last_3_hours", timedelta(hours=3), "最近3小时"),
            ("last_hour", timedelta(hours=1), "最近1小时"),
        ]
        """
        统计时间段 [(统计名称, 统计时间段, 统计描述), ...]
        """

    def _statistic_console_output(self, stats: Dict[str, Any], now: datetime):
        """
        输出统计数据到控制台
        :param stats: 统计数据
        :param now: 基准当前时间
        """
        # 输出最近一小时的统计数据

        output = [
            self.SEP_LINE,
            f"  最近1小时的统计数据  (自{now.strftime('%Y-%m-%d %H:%M:%S')}开始，详细信息见文件：{self.record_file_path})",
            self.SEP_LINE,
            self._format_total_stat(stats["last_hour"]),
            "",
            self._format_model_classified_stat(stats["last_hour"]),
            "",
            self._format_chat_stat(stats["last_hour"]),
            self.SEP_LINE,
            "",
        ]

        logger.info("\n" + "\n".join(output))

    async def run(self):
        try:
            now = datetime.now()

            # 使用线程池并行执行耗时操作
            loop = asyncio.get_event_loop()

            # 在线程池中并行执行数据收集和之前的HTML生成（如果存在）
            with concurrent.futures.ThreadPoolExecutor() as executor:
                logger.info("正在收集统计数据...")

                # 数据收集任务
                collect_task = loop.run_in_executor(executor, self._collect_all_statistics, now)

                # 等待数据收集完成
                stats = await collect_task
                logger.info("统计数据收集完成")

                # 并行执行控制台输出和HTML报告生成
                console_task = loop.run_in_executor(executor, self._statistic_console_output, stats, now)
                html_task = loop.run_in_executor(executor, self._generate_html_report, stats, now)

                # 等待两个输出任务完成
                await asyncio.gather(console_task, html_task)

            logger.info("统计数据输出完成")
        except Exception as e:
            logger.exception(f"输出统计数据过程中发生异常，错误信息：{e}")

    async def run_async_background(self):
        """
        备选方案：完全异步后台运行统计输出
        使用此方法可以让统计任务完全非阻塞
        """

        async def _async_collect_and_output():
            try:
                import concurrent.futures

                now = datetime.now()
                loop = asyncio.get_event_loop()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    logger.info("正在后台收集统计数据...")

                    # 创建后台任务，不等待完成
                    collect_task = asyncio.create_task(
                        loop.run_in_executor(executor, self._collect_all_statistics, now)  # type: ignore
                    )

                    stats = await collect_task
                    logger.info("统计数据收集完成")

                    # 创建并发的输出任务
                    output_tasks = [
                        asyncio.create_task(loop.run_in_executor(executor, self._statistic_console_output, stats, now)),  # type: ignore
                        asyncio.create_task(loop.run_in_executor(executor, self._generate_html_report, stats, now)),  # type: ignore
                    ]

                    # 等待所有输出任务完成
                    await asyncio.gather(*output_tasks)

                logger.info("统计数据后台输出完成")
            except Exception as e:
                logger.exception(f"后台统计数据输出过程中发生异常：{e}")

        # 创建后台任务，立即返回
        asyncio.create_task(_async_collect_and_output())

    # -- 以下为统计数据收集方法 --

    @staticmethod
    def _collect_model_request_for_period(collect_period: List[Tuple[str, datetime]]) -> Dict[str, Any]:
        """
        收集指定时间段的LLM请求统计数据

        :param collect_period: 统计时间段
        """
        if not collect_period:
            return {}

        # 排序-按照时间段开始时间降序排列（最晚的时间段在前）
        collect_period.sort(key=lambda x: x[1], reverse=True)

        stats = {
            period_key: {
                TOTAL_REQ_CNT: 0,
                REQ_CNT_BY_TYPE: defaultdict(int),
                REQ_CNT_BY_USER: defaultdict(int),
                REQ_CNT_BY_MODEL: defaultdict(int),
                REQ_CNT_BY_MODULE: defaultdict(int),
                IN_TOK_BY_TYPE: defaultdict(int),
                IN_TOK_BY_USER: defaultdict(int),
                IN_TOK_BY_MODEL: defaultdict(int),
                IN_TOK_BY_MODULE: defaultdict(int),
                OUT_TOK_BY_TYPE: defaultdict(int),
                OUT_TOK_BY_USER: defaultdict(int),
                OUT_TOK_BY_MODEL: defaultdict(int),
                OUT_TOK_BY_MODULE: defaultdict(int),
                TOTAL_TOK_BY_TYPE: defaultdict(int),
                TOTAL_TOK_BY_USER: defaultdict(int),
                TOTAL_TOK_BY_MODEL: defaultdict(int),
                TOTAL_TOK_BY_MODULE: defaultdict(int),
                TOTAL_COST: 0.0,
                COST_BY_TYPE: defaultdict(float),
                COST_BY_USER: defaultdict(float),
                COST_BY_MODEL: defaultdict(float),
                COST_BY_MODULE: defaultdict(float),
                TIME_COST_BY_TYPE: defaultdict(list),
                TIME_COST_BY_USER: defaultdict(list),
                TIME_COST_BY_MODEL: defaultdict(list),
                TIME_COST_BY_MODULE: defaultdict(list),
                AVG_TIME_COST_BY_TYPE: defaultdict(float),
                AVG_TIME_COST_BY_USER: defaultdict(float),
                AVG_TIME_COST_BY_MODEL: defaultdict(float),
                AVG_TIME_COST_BY_MODULE: defaultdict(float),
                STD_TIME_COST_BY_TYPE: defaultdict(float),
                STD_TIME_COST_BY_USER: defaultdict(float),
                STD_TIME_COST_BY_MODEL: defaultdict(float),
                STD_TIME_COST_BY_MODULE: defaultdict(float),
            }
            for period_key, _ in collect_period
        }

        # 以最早的时间戳为起始时间获取记录
        # Assuming LLMUsage.timestamp is a DateTimeField
        query_start_time = collect_period[-1][1]
        for record in LLMUsage.select().where(LLMUsage.timestamp >= query_start_time):  # type: ignore
            record_timestamp = record.timestamp  # This is already a datetime object
            for idx, (_, period_start) in enumerate(collect_period):
                if record_timestamp >= period_start:
                    for period_key, _ in collect_period[idx:]:
                        stats[period_key][TOTAL_REQ_CNT] += 1

                        request_type = record.request_type or "unknown"
                        user_id = record.user_id or "unknown"  # user_id is TextField, already string
                        model_name = record.model_name or "unknown"

                        # 提取模块名：如果请求类型包含"."，取第一个"."之前的部分
                        module_name = request_type.split(".")[0] if "." in request_type else request_type

                        stats[period_key][REQ_CNT_BY_TYPE][request_type] += 1
                        stats[period_key][REQ_CNT_BY_USER][user_id] += 1
                        stats[period_key][REQ_CNT_BY_MODEL][model_name] += 1
                        stats[period_key][REQ_CNT_BY_MODULE][module_name] += 1

                        prompt_tokens = record.prompt_tokens or 0
                        completion_tokens = record.completion_tokens or 0
                        total_tokens = prompt_tokens + completion_tokens

                        stats[period_key][IN_TOK_BY_TYPE][request_type] += prompt_tokens
                        stats[period_key][IN_TOK_BY_USER][user_id] += prompt_tokens
                        stats[period_key][IN_TOK_BY_MODEL][model_name] += prompt_tokens
                        stats[period_key][IN_TOK_BY_MODULE][module_name] += prompt_tokens

                        stats[period_key][OUT_TOK_BY_TYPE][request_type] += completion_tokens
                        stats[period_key][OUT_TOK_BY_USER][user_id] += completion_tokens
                        stats[period_key][OUT_TOK_BY_MODEL][model_name] += completion_tokens
                        stats[period_key][OUT_TOK_BY_MODULE][module_name] += completion_tokens

                        stats[period_key][TOTAL_TOK_BY_TYPE][request_type] += total_tokens
                        stats[period_key][TOTAL_TOK_BY_USER][user_id] += total_tokens
                        stats[period_key][TOTAL_TOK_BY_MODEL][model_name] += total_tokens
                        stats[period_key][TOTAL_TOK_BY_MODULE][module_name] += total_tokens

                        cost = record.cost or 0.0
                        stats[period_key][TOTAL_COST] += cost
                        stats[period_key][COST_BY_TYPE][request_type] += cost
                        stats[period_key][COST_BY_USER][user_id] += cost
                        stats[period_key][COST_BY_MODEL][model_name] += cost
                        stats[period_key][COST_BY_MODULE][module_name] += cost

                        # 收集time_cost数据
                        time_cost = record.time_cost or 0.0
                        if time_cost > 0:  # 只记录有效的time_cost
                            stats[period_key][TIME_COST_BY_TYPE][request_type].append(time_cost)
                            stats[period_key][TIME_COST_BY_USER][user_id].append(time_cost)
                            stats[period_key][TIME_COST_BY_MODEL][model_name].append(time_cost)
                            stats[period_key][TIME_COST_BY_MODULE][module_name].append(time_cost)
                    break

        # 计算平均耗时和标准差
        for period_key in stats:
            for category in [REQ_CNT_BY_TYPE, REQ_CNT_BY_USER, REQ_CNT_BY_MODEL, REQ_CNT_BY_MODULE]:
                time_cost_key = f"time_costs_by_{category.split('_')[-1]}"
                avg_key = f"avg_time_costs_by_{category.split('_')[-1]}"
                std_key = f"std_time_costs_by_{category.split('_')[-1]}"
                
                for item_name in stats[period_key][category]:
                    time_costs = stats[period_key][time_cost_key].get(item_name, [])
                    if time_costs:
                        # 计算平均耗时
                        avg_time_cost = sum(time_costs) / len(time_costs)
                        stats[period_key][avg_key][item_name] = round(avg_time_cost, 3)
                        
                        # 计算标准差
                        if len(time_costs) > 1:
                            variance = sum((x - avg_time_cost) ** 2 for x in time_costs) / len(time_costs)
                            std_time_cost = variance ** 0.5
                            stats[period_key][std_key][item_name] = round(std_time_cost, 3)
                        else:
                            stats[period_key][std_key][item_name] = 0.0
                    else:
                        stats[period_key][avg_key][item_name] = 0.0
                        stats[period_key][std_key][item_name] = 0.0

        return stats

    @staticmethod
    def _collect_online_time_for_period(collect_period: List[Tuple[str, datetime]], now: datetime) -> Dict[str, Any]:
        """
        收集指定时间段的在线时间统计数据

        :param collect_period: 统计时间段
        """
        if not collect_period:
            return {}

        collect_period.sort(key=lambda x: x[1], reverse=True)

        stats = {
            period_key: {
                ONLINE_TIME: 0.0,
            }
            for period_key, _ in collect_period
        }

        query_start_time = collect_period[-1][1]
        # Assuming OnlineTime.end_timestamp is a DateTimeField
        for record in OnlineTime.select().where(OnlineTime.end_timestamp >= query_start_time):  # type: ignore
            # record.end_timestamp and record.start_timestamp are datetime objects
            record_end_timestamp = record.end_timestamp
            record_start_timestamp = record.start_timestamp

            for idx, (_, period_boundary_start) in enumerate(collect_period):
                if record_end_timestamp >= period_boundary_start:
                    # Calculate effective end time for this record in relation to 'now'
                    effective_end_time = min(record_end_timestamp, now)

                    for period_key, current_period_start_time in collect_period[idx:]:
                        # Determine the portion of the record that falls within this specific statistical period
                        overlap_start = max(record_start_timestamp, current_period_start_time)
                        overlap_end = effective_end_time  # Already capped by 'now' and record's own end

                        if overlap_end > overlap_start:
                            stats[period_key][ONLINE_TIME] += (overlap_end - overlap_start).total_seconds()
                    break
        return stats

    def _collect_message_count_for_period(self, collect_period: List[Tuple[str, datetime]]) -> Dict[str, Any]:
        """
        收集指定时间段的消息统计数据

        :param collect_period: 统计时间段
        """
        if not collect_period:
            return {}

        collect_period.sort(key=lambda x: x[1], reverse=True)

        stats = {
            period_key: {
                TOTAL_MSG_CNT: 0,
                MSG_CNT_BY_CHAT: defaultdict(int),
            }
            for period_key, _ in collect_period
        }

        query_start_timestamp = collect_period[-1][1].timestamp()  # Messages.time is a DoubleField (timestamp)
        for message in Messages.select().where(Messages.time >= query_start_timestamp):  # type: ignore
            message_time_ts = message.time  # This is a float timestamp

            chat_id = None
            chat_name = None

            # Logic based on Peewee model structure, aiming to replicate original intent
            if message.chat_info_group_id:
                chat_id = f"g{message.chat_info_group_id}"
                chat_name = message.chat_info_group_name or f"群{message.chat_info_group_id}"
            elif message.user_id:  # Fallback to sender's info for chat_id if not a group_info based chat
                # This uses the message SENDER's ID as per original logic's fallback
                chat_id = f"u{message.user_id}"  # SENDER's user_id
                chat_name = message.user_nickname  # SENDER's nickname
            else:
                # If neither group_id nor sender_id is available for chat identification
                logger.warning(
                    f"Message (PK: {message.id if hasattr(message, 'id') else 'N/A'}) lacks group_id and user_id for chat stats."
                )
                continue

            if not chat_id:  # Should not happen if above logic is correct
                continue

            # Update name_mapping
            if chat_id in self.name_mapping:
                if chat_name != self.name_mapping[chat_id][0] and message_time_ts > self.name_mapping[chat_id][1]:
                    self.name_mapping[chat_id] = (chat_name, message_time_ts)
            else:
                self.name_mapping[chat_id] = (chat_name, message_time_ts)

            for idx, (_, period_start_dt) in enumerate(collect_period):
                if message_time_ts >= period_start_dt.timestamp():
                    for period_key, _ in collect_period[idx:]:
                        stats[period_key][TOTAL_MSG_CNT] += 1
                        stats[period_key][MSG_CNT_BY_CHAT][chat_id] += 1
                    break
        return stats

    

    def _collect_all_statistics(self, now: datetime) -> Dict[str, Dict[str, Any]]:
        """
        收集各时间段的统计数据
        :param now: 基准当前时间
        """

        last_all_time_stat = None

        if "last_full_statistics" in local_storage:
            # 如果存在上次完整统计数据，则使用该数据进行增量统计
            last_stat: Dict[str, Any] = local_storage["last_full_statistics"]  # 上次完整统计数据 # type: ignore

            self.name_mapping = last_stat["name_mapping"]  # 上次完整统计数据的名称映射
            last_all_time_stat = last_stat["stat_data"]  # 上次完整统计的统计数据
            last_stat_timestamp = datetime.fromtimestamp(last_stat["timestamp"])  # 上次完整统计数据的时间戳
            self.stat_period = [item for item in self.stat_period if item[0] != "all_time"]  # 删除"所有时间"的统计时段
            self.stat_period.append(("all_time", now - last_stat_timestamp, "自部署以来的"))

        stat_start_timestamp = [(period[0], now - period[1]) for period in self.stat_period]

        stat = {item[0]: {} for item in self.stat_period}

        model_req_stat = self._collect_model_request_for_period(stat_start_timestamp)
        online_time_stat = self._collect_online_time_for_period(stat_start_timestamp, now)
        message_count_stat = self._collect_message_count_for_period(stat_start_timestamp)

        # 统计数据合并
        # 合并三类统计数据
        for period_key, _ in stat_start_timestamp:
            stat[period_key].update(model_req_stat[period_key])
            stat[period_key].update(online_time_stat[period_key])
            stat[period_key].update(message_count_stat[period_key])

        if last_all_time_stat:
            # 若存在上次完整统计数据，则将其与当前统计数据合并
            for key, val in last_all_time_stat.items():
                # 确保当前统计数据中存在该key
                if key not in stat["all_time"]:
                    continue

                if isinstance(val, dict):
                    # 是字典类型，则进行合并
                    for sub_key, sub_val in val.items():
                        # 普通的数值或字典合并
                        if sub_key in stat["all_time"][key]:
                            # 检查是否为嵌套的字典类型（如版本统计）
                            if isinstance(sub_val, dict) and isinstance(stat["all_time"][key][sub_key], dict):
                                # 合并嵌套字典
                                for nested_key, nested_val in sub_val.items():
                                    if nested_key in stat["all_time"][key][sub_key]:
                                        stat["all_time"][key][sub_key][nested_key] += nested_val
                                    else:
                                        stat["all_time"][key][sub_key][nested_key] = nested_val
                            else:
                                # 普通数值累加
                                stat["all_time"][key][sub_key] += sub_val
                        else:
                            stat["all_time"][key][sub_key] = sub_val
                else:
                    # 直接合并
                    stat["all_time"][key] += val

        # 更新上次完整统计数据的时间戳
        # 将所有defaultdict转换为普通dict以避免类型冲突
        clean_stat_data = self._convert_defaultdict_to_dict(stat["all_time"])
        local_storage["last_full_statistics"] = {
            "name_mapping": self.name_mapping,
            "stat_data": clean_stat_data,
            "timestamp": now.timestamp(),
        }

        return stat

    def _convert_defaultdict_to_dict(self, data):
        # sourcery skip: dict-comprehension, extract-duplicate-method, inline-immediately-returned-variable, merge-duplicate-blocks
        """递归转换defaultdict为普通dict"""
        if isinstance(data, defaultdict):
            # 转换defaultdict为普通dict
            result = {}
            for key, value in data.items():
                result[key] = self._convert_defaultdict_to_dict(value)
            return result
        elif isinstance(data, dict):
            # 递归处理普通dict
            result = {}
            for key, value in data.items():
                result[key] = self._convert_defaultdict_to_dict(value)
            return result
        else:
            # 其他类型直接返回
            return data

    # -- 以下为统计数据格式化方法 --

    @staticmethod
    def _format_total_stat(stats: Dict[str, Any]) -> str:
        """
        格式化总统计数据
        """

        output = [
            f"总在线时间: {_format_online_time(stats[ONLINE_TIME])}",
            f"总消息数: {stats[TOTAL_MSG_CNT]}",
            f"总请求数: {stats[TOTAL_REQ_CNT]}",
            f"总花费: {stats[TOTAL_COST]:.2f}¥",
            "",
        ]

        return "\n".join(output)

    @staticmethod
    def _format_model_classified_stat(stats: Dict[str, Any]) -> str:
        """
        格式化按模型分类的统计数据
        """
        if stats[TOTAL_REQ_CNT] <= 0:
            return ""
        data_fmt = "{:<32}  {:>10}  {:>12}  {:>12}  {:>12}  {:>9.2f}¥  {:>10.1f}  {:>10.1f}"

        output = [
            "按模型分类统计:",
            " 模型名称                          调用次数    输入Token     输出Token     Token总量     累计花费    平均耗时(秒)  标准差(秒)",
        ]
        for model_name, count in sorted(stats[REQ_CNT_BY_MODEL].items()):
            name = f"{model_name[:29]}..." if len(model_name) > 32 else model_name
            in_tokens = stats[IN_TOK_BY_MODEL][model_name]
            out_tokens = stats[OUT_TOK_BY_MODEL][model_name]
            tokens = stats[TOTAL_TOK_BY_MODEL][model_name]
            cost = stats[COST_BY_MODEL][model_name]
            avg_time_cost = stats[AVG_TIME_COST_BY_MODEL][model_name]
            std_time_cost = stats[STD_TIME_COST_BY_MODEL][model_name]
            output.append(data_fmt.format(name, count, in_tokens, out_tokens, tokens, cost, avg_time_cost, std_time_cost))

        output.append("")
        return "\n".join(output)

    def _format_chat_stat(self, stats: Dict[str, Any]) -> str:
        """
        格式化聊天统计数据
        """
        if stats[TOTAL_MSG_CNT] <= 0:
            return ""
        output = ["聊天消息统计:", " 联系人/群组名称                  消息数量"]
        output.extend(
            f"{self.name_mapping[chat_id][0][:32]:<32}  {count:>10}"
            for chat_id, count in sorted(stats[MSG_CNT_BY_CHAT].items())
        )
        output.append("")
        return "\n".join(output)

    def _get_chat_display_name_from_id(self, chat_id: str) -> str:
        """从chat_id获取显示名称"""
        try:
            # 首先尝试从chat_stream获取真实群组名称
            from src.chat.message_receive.chat_stream import get_chat_manager

            chat_manager = get_chat_manager()

            if chat_id in chat_manager.streams:
                stream = chat_manager.streams[chat_id]
                if stream.group_info and hasattr(stream.group_info, "group_name"):
                    group_name = stream.group_info.group_name
                    if group_name and group_name.strip():
                        return group_name.strip()
                elif stream.user_info and hasattr(stream.user_info, "user_nickname"):
                    user_name = stream.user_info.user_nickname
                    if user_name and user_name.strip():
                        return user_name.strip()

            # 如果从chat_stream获取失败，尝试解析chat_id格式
            if chat_id.startswith("g"):
                return f"群聊{chat_id[1:]}"
            elif chat_id.startswith("u"):
                return f"用户{chat_id[1:]}"
            else:
                return chat_id
        except Exception as e:
            logger.warning(f"获取聊天显示名称失败: {e}")
            return chat_id

    # 移除_generate_versions_tab方法

    def _generate_html_report(self, stat: dict[str, Any], now: datetime):
        """
        生成HTML格式的统计报告
        :param stat: 统计数据
        :param now: 基准当前时间
        :return: HTML格式的统计报告
        """

        # 移除版本对比内容相关tab和内容
        tab_list = [
            f'<button class="tab-link" onclick="showTab(event, \'{period[0]}\')">{period[2]}</button>'
            for period in self.stat_period
        ]
        tab_list.append('<button class="tab-link" onclick="showTab(event, \'charts\')">数据图表</button>')

        def _format_stat_data(stat_data: dict[str, Any], div_id: str, start_time: datetime) -> str:
            """
            格式化一个时间段的统计数据到html div块
            :param stat_data: 统计数据
            :param div_id: div的ID
            :param start_time: 统计时间段开始时间
            """
            # format总在线时间

            # 按模型分类统计
            model_rows = "\n".join(
                [
                    f"<tr>"
                    f"<td>{model_name}</td>"
                    f"<td>{count}</td>"
                    f"<td>{stat_data[IN_TOK_BY_MODEL][model_name]}</td>"
                    f"<td>{stat_data[OUT_TOK_BY_MODEL][model_name]}</td>"
                    f"<td>{stat_data[TOTAL_TOK_BY_MODEL][model_name]}</td>"
                    f"<td>{stat_data[COST_BY_MODEL][model_name]:.2f} ¥</td>"
                    f"<td>{stat_data[AVG_TIME_COST_BY_MODEL][model_name]:.1f} 秒</td>"
                    f"<td>{stat_data[STD_TIME_COST_BY_MODEL][model_name]:.1f} 秒</td>"
                    f"</tr>"
                    for model_name, count in sorted(stat_data[REQ_CNT_BY_MODEL].items())
                ]
            )
            # 按请求类型分类统计
            type_rows = "\n".join(
                [
                    f"<tr>"
                    f"<td>{req_type}</td>"
                    f"<td>{count}</td>"
                    f"<td>{stat_data[IN_TOK_BY_TYPE][req_type]}</td>"
                    f"<td>{stat_data[OUT_TOK_BY_TYPE][req_type]}</td>"
                    f"<td>{stat_data[TOTAL_TOK_BY_TYPE][req_type]}</td>"
                    f"<td>{stat_data[COST_BY_TYPE][req_type]:.2f} ¥</td>"
                    f"<td>{stat_data[AVG_TIME_COST_BY_TYPE][req_type]:.1f} 秒</td>"
                    f"<td>{stat_data[STD_TIME_COST_BY_TYPE][req_type]:.1f} 秒</td>"
                    f"</tr>"
                    for req_type, count in sorted(stat_data[REQ_CNT_BY_TYPE].items())
                ]
            )
            # 按模块分类统计
            module_rows = "\n".join(
                [
                    f"<tr>"
                    f"<td>{module_name}</td>"
                    f"<td>{count}</td>"
                    f"<td>{stat_data[IN_TOK_BY_MODULE][module_name]}</td>"
                    f"<td>{stat_data[OUT_TOK_BY_MODULE][module_name]}</td>"
                    f"<td>{stat_data[TOTAL_TOK_BY_MODULE][module_name]}</td>"
                    f"<td>{stat_data[COST_BY_MODULE][module_name]:.2f} ¥</td>"
                    f"<td>{stat_data[AVG_TIME_COST_BY_MODULE][module_name]:.1f} 秒</td>"
                    f"<td>{stat_data[STD_TIME_COST_BY_MODULE][module_name]:.1f} 秒</td>"
                    f"</tr>"
                    for module_name, count in sorted(stat_data[REQ_CNT_BY_MODULE].items())
                ]
            )

            # 聊天消息统计
            chat_rows = "\n".join(
                [
                    f"<tr><td>{self.name_mapping[chat_id][0]}</td><td>{count}</td></tr>"
                    for chat_id, count in sorted(stat_data[MSG_CNT_BY_CHAT].items())
                ]
            )
            # 生成HTML
            return f"""
            <div id=\"{div_id}\" class=\"tab-content\">
                <p class=\"info-item\">
                    <strong>统计时段: </strong>
                    {start_time.strftime("%Y-%m-%d %H:%M:%S")} ~ {now.strftime("%Y-%m-%d %H:%M:%S")}
                </p>
                <p class=\"info-item\"><strong>总在线时间: </strong>{_format_online_time(stat_data[ONLINE_TIME])}</p>
                <p class=\"info-item\"><strong>总消息数: </strong>{stat_data[TOTAL_MSG_CNT]}</p>
                <p class=\"info-item\"><strong>总请求数: </strong>{stat_data[TOTAL_REQ_CNT]}</p>
                <p class=\"info-item\"><strong>总花费: </strong>{stat_data[TOTAL_COST]:.2f} ¥</p>
                
                <h2>按模型分类统计</h2>
                <table>
                    <thead><tr><th>模型名称</th><th>调用次数</th><th>输入Token</th><th>输出Token</th><th>Token总量</th><th>累计花费</th><th>平均耗时(秒)</th><th>标准差(秒)</th></tr></thead>
                    <tbody>
                        {model_rows}
                    </tbody>
                </table>
                
                <h2>按模块分类统计</h2>
                <table>
                    <thead>
                        <tr><th>模块名称</th><th>调用次数</th><th>输入Token</th><th>输出Token</th><th>Token总量</th><th>累计花费</th><th>平均耗时(秒)</th><th>标准差(秒)</th></tr>
                    </thead>
                    <tbody>
                    {module_rows}
                    </tbody>
                </table>
    
                <h2>按请求类型分类统计</h2>
                <table>
                    <thead>
                        <tr><th>请求类型</th><th>调用次数</th><th>输入Token</th><th>输出Token</th><th>Token总量</th><th>累计花费</th><th>平均耗时(秒)</th><th>标准差(秒)</th></tr>
                    </thead>
                    <tbody>
                    {type_rows}
                    </tbody>
                </table>
    
                <h2>聊天消息统计</h2>
                <table>
                    <thead>
                        <tr><th>联系人/群组名称</th><th>消息数量</th></tr>
                    </thead>
                    <tbody>
                    {chat_rows}
                    </tbody>
                </table>
                

                    // 为当前统计卡片创建饼图
                    createPieCharts_{div_id}();
                    
                    function createPieCharts_{div_id}() {{
                        const colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#34495e', '#e67e22', '#95a5a6', '#f1c40f'];
                        
                        // 模型调用次数饼图
                        const modelData = {{
                            labels: {[f'"{model_name}"' for model_name in sorted(stat_data[REQ_CNT_BY_MODEL].keys())]},
                            datasets: [{{
                                data: {[stat_data[REQ_CNT_BY_MODEL][model_name] for model_name in sorted(stat_data[REQ_CNT_BY_MODEL].keys())]},
                                backgroundColor: colors[:len(stat_data[REQ_CNT_BY_MODEL])],
                                borderColor: colors[:len(stat_data[REQ_CNT_BY_MODEL])],
                                borderWidth: 2
                            }}]
                        }};
                        
                        new Chart(document.getElementById('modelPieChart_{div_id}'), {{
                            type: 'pie',
                            data: modelData,
                            options: {{
                                responsive: true,
                                plugins: {{
                                    legend: {{
                                        position: 'bottom'
                                    }},
                                    tooltip: {{
                                        callbacks: {{
                                            label: function(context) {{
                                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                                return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }});
                        
                        // 模块调用次数饼图
                        const moduleData = {{
                            labels: {[f'"{module_name}"' for module_name in sorted(stat_data[REQ_CNT_BY_MODULE].keys())]},
                            datasets: [{{
                                data: {[stat_data[REQ_CNT_BY_MODULE][module_name] for module_name in sorted(stat_data[REQ_CNT_BY_MODULE].keys())]},
                                backgroundColor: colors[:len(stat_data[REQ_CNT_BY_MODULE])],
                                borderColor: colors[:len(stat_data[REQ_CNT_BY_MODULE])],
                                borderWidth: 2
                            }}]
                        }};
                        
                        new Chart(document.getElementById('modulePieChart_{div_id}'), {{
                            type: 'pie',
                            data: moduleData,
                            options: {{
                                responsive: true,
                                plugins: {{
                                    legend: {{
                                        position: 'bottom'
                                    }},
                                    tooltip: {{
                                        callbacks: {{
                                            label: function(context) {{
                                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                                return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }});
                        
                        // 请求类型分布饼图
                        const typeData = {{
                            labels: {[f'"{req_type}"' for req_type in sorted(stat_data[REQ_CNT_BY_TYPE].keys())]},
                            datasets: [{{
                                data: {[stat_data[REQ_CNT_BY_TYPE][req_type] for req_type in sorted(stat_data[REQ_CNT_BY_TYPE].keys())]},
                                backgroundColor: colors[:len(stat_data[REQ_CNT_BY_TYPE])],
                                borderColor: colors[:len(stat_data[REQ_CNT_BY_TYPE])],
                                borderWidth: 2
                            }}]
                        }};
                        
                        new Chart(document.getElementById('typePieChart_{div_id}'), {{
                            type: 'pie',
                            data: typeData,
                            options: {{
                                responsive: true,
                                plugins: {{
                                    legend: {{
                                        position: 'bottom'
                                    }},
                                    tooltip: {{
                                        callbacks: {{
                                            label: function(context) {{
                                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                                return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }});
                        
                        // 聊天消息分布饼图
                        const chatData = {{
                            labels: {[f'"{self.name_mapping[chat_id][0]}"' for chat_id in sorted(stat_data[MSG_CNT_BY_CHAT].keys())]},
                            datasets: [{{
                                data: {[stat_data[MSG_CNT_BY_CHAT][chat_id] for chat_id in sorted(stat_data[MSG_CNT_BY_CHAT].keys())]},
                                backgroundColor: colors[:len(stat_data[MSG_CNT_BY_CHAT])],
                                borderColor: colors[:len(stat_data[MSG_CNT_BY_CHAT])],
                                borderWidth: 2
                            }}]
                        }};
                        
                        new Chart(document.getElementById('chatPieChart_{div_id}'), {{
                            type: 'pie',
                            data: chatData,
                            options: {{
                                responsive: true,
                                plugins: {{
                                    legend: {{
                                        position: 'bottom'
                                    }},
                                    tooltip: {{
                                        callbacks: {{
                                            label: function(context) {{
                                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                                return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }});
                    }}

            </div>
            """

        tab_content_list = [
            _format_stat_data(stat[period[0]], period[0], now - period[1])
            for period in self.stat_period
            if period[0] != "all_time"
        ]

        tab_content_list.append(
            _format_stat_data(stat["all_time"], "all_time", datetime.fromtimestamp(local_storage["deploy_time"]))  # type: ignore
        )

        # 不再添加版本对比内容
        # 添加图表内容
        chart_data = self._generate_chart_data(stat)
        tab_content_list.append(self._generate_chart_tab(chart_data))

        joined_tab_list = "\n".join(tab_list)
        joined_tab_content = "\n".join(tab_content_list)

        html_template = (
            """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MaiBot运行统计报告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f4f7f6;
            color: #333;
            line-height: 1.6;
        }
        .container {
            max-width: 900px;
            margin: 20px auto;
            background-color: #fff;
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1, h2 {
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
            margin-top: 0;
        }
        h1 {
            text-align: center;
            font-size: 2em;
        }
        h2 {
            font-size: 1.5em;
            margin-top: 30px;
        }
        p {
            margin-bottom: 10px;
        }
        .info-item {
            background-color: #ecf0f1;
            padding: 8px 12px;
            border-radius: 4px;
            margin-bottom: 8px;
            font-size: 0.95em;
        }
        .info-item strong {
            color: #2980b9;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            font-size: 0.9em;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 10px;
            text-align: left;
        }
        th {
            background-color: #3498db;
            color: white;
            font-weight: bold;
        }
        tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        .footer {
            text-align: center;
            margin-top: 30px;
            font-size: 0.8em;
            color: #7f8c8d;
        }
        .tabs {
            overflow: hidden;
            background: #ecf0f1;
            display: flex;
        }
        .tabs button {
            background: inherit; border: none; outline: none;
            padding: 14px 16px; cursor: pointer;
            transition: 0.3s; font-size: 16px;
        }
        .tabs button:hover {
            background-color: #d4dbdc;
        }
        .tabs button.active {
            background-color: #b3bbbd;
        }
        .tab-content {
            display: none;
            padding: 20px;
            background-color: #fff;
            border: 1px solid #ccc;
        }
        .tab-content.active {
            display: block;
        }
    </style>
</head>
<body>
"""
            + f"""
    <div class="container">
        <h1>MaiBot运行统计报告</h1>
        <p class="info-item"><strong>统计截止时间:</strong> {now.strftime("%Y-%m-%d %H:%M:%S")}</p>

        <div class="tabs">
            {joined_tab_list}
        </div>

        {joined_tab_content}
    </div>
"""
            + """
<script>
    let i, tab_content, tab_links;
    tab_content = document.getElementsByClassName("tab-content");
    tab_links = document.getElementsByClassName("tab-link");
    
    tab_content[0].classList.add("active");
    tab_links[0].classList.add("active");

    function showTab(evt, tabName) {{
        for (i = 0; i < tab_content.length; i++) tab_content[i].classList.remove("active");
        for (i = 0; i < tab_links.length; i++) tab_links[i].classList.remove("active");
        document.getElementById(tabName).classList.add("active");
        evt.currentTarget.classList.add("active");
    }}
</script>
</body>
</html>
        """
        )

        with open(self.record_file_path, "w", encoding="utf-8") as f:
            f.write(html_template)

    def _generate_chart_data(self, stat: dict[str, Any]) -> dict:
        """生成图表数据"""
        now = datetime.now()
        chart_data = {}

        # 支持多个时间范围
        time_ranges = [
            ("6h", 6, 10),  # 6小时，10分钟间隔
            ("12h", 12, 15),  # 12小时，15分钟间隔
            ("24h", 24, 15),  # 24小时，15分钟间隔
            ("48h", 48, 30),  # 48小时，30分钟间隔
        ]

        for range_key, hours, interval_minutes in time_ranges:
            range_data = self._collect_interval_data(now, hours, interval_minutes)
            chart_data[range_key] = range_data

        return chart_data

    def _collect_interval_data(self, now: datetime, hours: int, interval_minutes: int) -> dict:
        """收集指定时间范围内每个间隔的数据"""
        # 生成时间点
        start_time = now - timedelta(hours=hours)
        time_points = []
        current_time = start_time

        while current_time <= now:
            time_points.append(current_time)
            current_time += timedelta(minutes=interval_minutes)

        # 初始化数据结构
        total_cost_data = [0] * len(time_points)
        cost_by_model = {}
        cost_by_module = {}
        message_by_chat = {}
        time_labels = [t.strftime("%H:%M") for t in time_points]

        interval_seconds = interval_minutes * 60

        # 查询LLM使用记录
        query_start_time = start_time
        for record in LLMUsage.select().where(LLMUsage.timestamp >= query_start_time):  # type: ignore
            record_time = record.timestamp

            # 找到对应的时间间隔索引
            time_diff = (record_time - start_time).total_seconds()
            interval_index = int(time_diff // interval_seconds)

            if 0 <= interval_index < len(time_points):
                # 累加总花费数据
                cost = record.cost or 0.0
                total_cost_data[interval_index] += cost  # type: ignore

                # 累加按模型分类的花费
                model_name = record.model_name or "unknown"
                if model_name not in cost_by_model:
                    cost_by_model[model_name] = [0] * len(time_points)
                cost_by_model[model_name][interval_index] += cost

                # 累加按模块分类的花费
                request_type = record.request_type or "unknown"
                module_name = request_type.split(".")[0] if "." in request_type else request_type
                if module_name not in cost_by_module:
                    cost_by_module[module_name] = [0] * len(time_points)
                cost_by_module[module_name][interval_index] += cost

        # 查询消息记录
        query_start_timestamp = start_time.timestamp()
        for message in Messages.select().where(Messages.time >= query_start_timestamp):  # type: ignore
            message_time_ts = message.time

            # 找到对应的时间间隔索引
            time_diff = message_time_ts - query_start_timestamp
            interval_index = int(time_diff // interval_seconds)

            if 0 <= interval_index < len(time_points):
                # 确定聊天流名称
                chat_name = None
                if message.chat_info_group_id:
                    chat_name = message.chat_info_group_name or f"群{message.chat_info_group_id}"
                elif message.user_id:
                    chat_name = message.user_nickname or f"用户{message.user_id}"
                else:
                    continue

                if not chat_name:
                    continue

                # 累加消息数
                if chat_name not in message_by_chat:
                    message_by_chat[chat_name] = [0] * len(time_points)
                message_by_chat[chat_name][interval_index] += 1

        return {
            "time_labels": time_labels,
            "total_cost_data": total_cost_data,
            "cost_by_model": cost_by_model,
            "cost_by_module": cost_by_module,
            "message_by_chat": message_by_chat,
        }

    def _generate_chart_tab(self, chart_data: dict) -> str:
        # sourcery skip: extract-duplicate-method, move-assign-in-block
        """生成图表选项卡HTML内容"""

        # 生成不同颜色的调色板
        colors = [
            "#3498db",
            "#e74c3c",
            "#2ecc71",
            "#f39c12",
            "#9b59b6",
            "#1abc9c",
            "#34495e",
            "#e67e22",
            "#95a5a6",
            "#f1c40f",
        ]

        # 默认使用24小时数据生成数据集
        default_data = chart_data["24h"]

        # 为每个模型生成数据集
        model_datasets = []
        for i, (model_name, cost_data) in enumerate(default_data["cost_by_model"].items()):
            color = colors[i % len(colors)]
            model_datasets.append(f"""{{
                label: '{model_name}',
                data: {cost_data},
                borderColor: '{color}',
                backgroundColor: '{color}20',
                tension: 0.4,
                fill: false
            }}""")

        ",\n                    ".join(model_datasets)

        # 为每个模块生成数据集
        module_datasets = []
        for i, (module_name, cost_data) in enumerate(default_data["cost_by_module"].items()):
            color = colors[i % len(colors)]
            module_datasets.append(f"""{{
                label: '{module_name}',
                data: {cost_data},
                borderColor: '{color}',
                backgroundColor: '{color}20',
                tension: 0.4,
                fill: false
            }}""")

        ",\n                    ".join(module_datasets)

        # 为每个聊天流生成消息数据集
        message_datasets = []
        for i, (chat_name, message_data) in enumerate(default_data["message_by_chat"].items()):
            color = colors[i % len(colors)]
            message_datasets.append(f"""{{
                label: '{chat_name}',
                data: {message_data},
                borderColor: '{color}',
                backgroundColor: '{color}20',
                tension: 0.4,
                fill: false
            }}""")

        ",\n                    ".join(message_datasets)

        return f"""
        <div id="charts" class="tab-content">
            <h2>数据图表</h2>
            
            <!-- 时间范围选择按钮 -->
            <div style="margin: 20px 0; text-align: center;">
                <label style="margin-right: 10px; font-weight: bold;">时间范围:</label>
                <button class="time-range-btn" onclick="switchTimeRange('6h')">6小时</button>
                <button class="time-range-btn" onclick="switchTimeRange('12h')">12小时</button>
                <button class="time-range-btn active" onclick="switchTimeRange('24h')">24小时</button>
                <button class="time-range-btn" onclick="switchTimeRange('48h')">48小时</button>
            </div>
            
            <div style="margin-top: 20px;">
                <div style="margin-bottom: 40px;">
                    <canvas id="totalCostChart" width="800" height="400"></canvas>
                </div>
                <div style="margin-bottom: 40px;">
                    <canvas id="costByModuleChart" width="800" height="400"></canvas>
                </div>
                <div style="margin-bottom: 40px;">
                    <canvas id="costByModelChart" width="800" height="400"></canvas>
                </div>
                <div>
                    <canvas id="messageByChatChart" width="800" height="400"></canvas>
                </div>
            </div>
            
            <style>
                .time-range-btn {{
                    background-color: #ecf0f1;
                    border: 1px solid #bdc3c7;
                    color: #2c3e50;
                    padding: 8px 16px;
                    margin: 0 5px;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 14px;
                    transition: all 0.3s ease;
                }}
                
                .time-range-btn:hover {{
                    background-color: #d5dbdb;
                }}
                
                .time-range-btn.active {{
                    background-color: #3498db;
                    color: white;
                    border-color: #2980b9;
                }}
            </style>
            
            <script>
                const allChartData = {chart_data};
                let currentCharts = {{}};
                
                // 图表配置模板
                const chartConfigs = {{
                    totalCost: {{
                        id: 'totalCostChart',
                        title: '总花费',
                        yAxisLabel: '花费 (¥)',
                        dataKey: 'total_cost_data',
                        fill: true
                    }},
                    costByModule: {{
                        id: 'costByModuleChart', 
                        title: '各模块花费',
                        yAxisLabel: '花费 (¥)',
                        dataKey: 'cost_by_module',
                        fill: false
                    }},
                    costByModel: {{
                        id: 'costByModelChart',
                        title: '各模型花费', 
                        yAxisLabel: '花费 (¥)',
                        dataKey: 'cost_by_model',
                        fill: false
                    }},
                    messageByChat: {{
                        id: 'messageByChatChart',
                        title: '各聊天流消息数',
                        yAxisLabel: '消息数',
                        dataKey: 'message_by_chat',
                        fill: false
                    }},
                    focusCyclesByAction: {{
                        id: 'focusCyclesByActionChart',
                        title: 'Focus循环按Action类型',
                        yAxisLabel: '循环数',
                        dataKey: 'focus_cycles_by_action',
                        fill: false
                    }},
                    focusTimeByStage: {{
                        id: 'focusTimeByStageChart',
                        title: 'Focus各阶段累计时间',
                        yAxisLabel: '时间 (秒)',
                        dataKey: 'focus_time_by_stage',
                        fill: false
                    }}
                }};
                
                function switchTimeRange(timeRange) {{
                    // 更新按钮状态
                    document.querySelectorAll('.time-range-btn').forEach(btn => {{
                        btn.classList.remove('active');
                    }});
                    event.target.classList.add('active');
                    
                    // 更新图表数据
                    const data = allChartData[timeRange];
                    updateAllCharts(data, timeRange);
                }}
                
                function updateAllCharts(data, timeRange) {{
                    // 销毁现有图表
                    Object.values(currentCharts).forEach(chart => {{
                        if (chart) chart.destroy();
                    }});
                    
                    currentCharts = {{}};
                    
                    // 重新创建图表
                    createChart('totalCost', data, timeRange);
                    createChart('costByModule', data, timeRange);
                    createChart('costByModel', data, timeRange);
                    createChart('messageByChat', data, timeRange);
                }}
                
                function createChart(chartType, data, timeRange) {{
                    const config = chartConfigs[chartType];
                    const colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#34495e', '#e67e22', '#95a5a6', '#f1c40f'];
                    
                    let datasets = [];
                    
                    if (chartType === 'totalCost') {{
                        datasets = [{{
                            label: config.title,
                            data: data[config.dataKey],
                            borderColor: colors[0],
                            backgroundColor: 'rgba(52, 152, 219, 0.1)',
                            tension: 0.4,
                            fill: config.fill
                        }}];
                    }} else {{
                        let i = 0;
                        Object.entries(data[config.dataKey]).forEach(([name, chartData]) => {{
                            datasets.push({{
                                label: name,
                                data: chartData,
                                borderColor: colors[i % colors.length],
                                backgroundColor: colors[i % colors.length] + '20',
                                tension: 0.4,
                                fill: config.fill
                            }});
                            i++;
                        }});
                    }}
                    
                    currentCharts[chartType] = new Chart(document.getElementById(config.id), {{
                        type: 'line',
                        data: {{
                            labels: data.time_labels,
                            datasets: datasets
                        }},
                        options: {{
                            responsive: true,
                            plugins: {{
                                title: {{
                                    display: true,
                                    text: timeRange + '内' + config.title + '趋势',
                                    font: {{ size: 16 }}
                                }},
                                legend: {{
                                    display: chartType !== 'totalCost',
                                    position: 'top'
                                }}
                            }},
                            scales: {{
                                x: {{
                                    title: {{
                                        display: true,
                                        text: '时间'
                                    }},
                                    ticks: {{
                                        maxTicksLimit: 12
                                    }}
                                }},
                                y: {{
                                    title: {{
                                        display: true,
                                        text: config.yAxisLabel
                                    }},
                                    beginAtZero: true
                                }}
                            }},
                            interaction: {{
                                intersect: false,
                                mode: 'index'
                            }}
                        }}
                    }});
                }}
                
                // 初始化图表（默认24小时）
                document.addEventListener('DOMContentLoaded', function() {{
                    updateAllCharts(allChartData['24h'], '24h');
                }});
            </script>
        </div>
        """


class AsyncStatisticOutputTask(AsyncTask):
    """完全异步的统计输出任务 - 更高性能版本"""

    def __init__(self, record_file_path: str = "maibot_statistics.html"):
        # 延迟0秒启动，运行间隔300秒
        super().__init__(task_name="Async Statistics Data Output Task", wait_before_start=0, run_interval=300)

        # 直接复用 StatisticOutputTask 的初始化逻辑
        temp_stat_task = StatisticOutputTask(record_file_path)
        self.name_mapping = temp_stat_task.name_mapping
        self.record_file_path = temp_stat_task.record_file_path
        self.stat_period = temp_stat_task.stat_period

    async def run(self):
        """完全异步执行统计任务"""

        async def _async_collect_and_output():
            try:
                now = datetime.now()
                loop = asyncio.get_event_loop()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    logger.info("正在后台收集统计数据...")

                    # 数据收集任务
                    collect_task = asyncio.create_task(
                        loop.run_in_executor(executor, self._collect_all_statistics, now)  # type: ignore
                    )

                    stats = await collect_task
                    logger.info("统计数据收集完成")

                    # 创建并发的输出任务
                    output_tasks = [
                        asyncio.create_task(loop.run_in_executor(executor, self._statistic_console_output, stats, now)),  # type: ignore
                        asyncio.create_task(loop.run_in_executor(executor, self._generate_html_report, stats, now)),  # type: ignore
                    ]

                    # 等待所有输出任务完成
                    await asyncio.gather(*output_tasks)

                logger.info("统计数据后台输出完成")
            except Exception as e:
                logger.exception(f"后台统计数据输出过程中发生异常：{e}")

        # 创建后台任务，立即返回
        asyncio.create_task(_async_collect_and_output())

    # 复用 StatisticOutputTask 的所有方法
    def _collect_all_statistics(self, now: datetime):
        return StatisticOutputTask._collect_all_statistics(self, now)  # type: ignore

    def _statistic_console_output(self, stats: Dict[str, Any], now: datetime):
        return StatisticOutputTask._statistic_console_output(self, stats, now)  # type: ignore

    def _generate_html_report(self, stats: dict[str, Any], now: datetime):
        return StatisticOutputTask._generate_html_report(self, stats, now)  # type: ignore

    # 其他需要的方法也可以类似复用...
    @staticmethod
    def _collect_model_request_for_period(collect_period: List[Tuple[str, datetime]]) -> Dict[str, Any]:
        return StatisticOutputTask._collect_model_request_for_period(collect_period)

    @staticmethod
    def _collect_online_time_for_period(collect_period: List[Tuple[str, datetime]], now: datetime) -> Dict[str, Any]:
        return StatisticOutputTask._collect_online_time_for_period(collect_period, now)

    def _collect_message_count_for_period(self, collect_period: List[Tuple[str, datetime]]) -> Dict[str, Any]:
        return StatisticOutputTask._collect_message_count_for_period(self, collect_period)  # type: ignore

    @staticmethod
    def _format_total_stat(stats: Dict[str, Any]) -> str:
        return StatisticOutputTask._format_total_stat(stats)

    @staticmethod
    def _format_model_classified_stat(stats: Dict[str, Any]) -> str:
        return StatisticOutputTask._format_model_classified_stat(stats)

    def _format_chat_stat(self, stats: Dict[str, Any]) -> str:
        return StatisticOutputTask._format_chat_stat(self, stats)  # type: ignore

    def _generate_chart_data(self, stat: dict[str, Any]) -> dict:
        return StatisticOutputTask._generate_chart_data(self, stat)  # type: ignore

    def _collect_interval_data(self, now: datetime, hours: int, interval_minutes: int) -> dict:
        return StatisticOutputTask._collect_interval_data(self, now, hours, interval_minutes)  # type: ignore

    def _generate_chart_tab(self, chart_data: dict) -> str:
        return StatisticOutputTask._generate_chart_tab(self, chart_data)  # type: ignore

    def _get_chat_display_name_from_id(self, chat_id: str) -> str:
        return StatisticOutputTask._get_chat_display_name_from_id(self, chat_id)  # type: ignore

    def _convert_defaultdict_to_dict(self, data):
        return StatisticOutputTask._convert_defaultdict_to_dict(self, data)  # type: ignore
