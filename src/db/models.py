from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey, BigInteger, Date, UniqueConstraint, Time, JSON
# 注意：将 JSONB 替换为通用的 JSON
from sqlalchemy.orm import relationship, declarative_base

import datetime
import zoneinfo

# 定义上海时区
SHANGHAI_TZ = zoneinfo.ZoneInfo("Asia/Shanghai")

# SQLAlchemy 声明性模型的基础类
Base = declarative_base()

# --- 核心表定义 ---

class User(Base):
    __tablename__ = 'users' # 用户表
    id = Column(Integer, primary_key=True, autoincrement=True, comment='用户表主键ID')
    platform_user_id = Column(String(191), index=True, comment='用户在平台上的唯一ID (例如QQ号)；MySQL InnoDB utf8mb4 下，唯一键长度限制通常为767字节，对应191个字符') # 调整String长度以兼容MySQL旧版本索引限制
    platform = Column(String(50), index=True, comment='平台名称 (例如: qq, wechat)')
    nickname = Column(String(255), comment='用户昵称')
    cardname = Column(String(255), nullable=True, comment='用户群昵称')

    # 联合唯一约束：确保同一平台下的用户ID是唯一的
    __table_args__ = (UniqueConstraint('platform_user_id', 'platform', name='uq_user_platform_id'),)

    # 定义关系: 一个User可以有多个ChatStream, Message, PersonInfo
    chat_streams = relationship("ChatStream", back_populates="user", cascade="all, delete-orphan")
    messages_sent = relationship("Message", back_populates="user", cascade="all, delete-orphan")
    person_infos = relationship("PersonInfo", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, platform='{self.platform}', platform_user_id='{self.platform_user_id}', nickname='{self.nickname}')>"

class ChatStream(Base):
    __tablename__ = 'chat_streams' # 聊天流表 (原 chat_streams 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='聊天流主键ID')
    stream_uuid = Column(String(191), unique=True, index=True, comment='聊天流的唯一标识符 (原 stream_id)') # 调整String长度
    create_time = Column(DateTime, default=datetime.datetime.now(SHANGHAI_TZ), comment='聊天流创建时间 (使用上海时区)')
    last_active_time = Column(DateTime, default=datetime.datetime.now(SHANGHAI_TZ), onupdate=datetime.datetime.now(SHANGHAI_TZ), comment='聊天流最后活跃时间 (使用上海时区)')
    platform = Column(String(50), comment='平台名称')
    
    user_id = Column(Integer, ForeignKey('users.id'), comment='关联的用户ID (通常是创建者或主要参与者)')
    user = relationship("User", back_populates="chat_streams") # 与User表建立多对一关系

    # 定义关系: 一个ChatStream可以包含多个Message和ThinkingLog
    messages = relationship("Message", back_populates="chat_stream", cascade="all, delete-orphan")
    thinking_logs = relationship("ThinkingLog", back_populates="chat_stream", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ChatStream(id={self.id}, stream_uuid='{self.stream_uuid}', platform='{self.platform}')>"

class Message(Base):
    __tablename__ = 'messages' # 消息表 (原 messages 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='消息主键ID')
    message_platform_id = Column(String(255), comment='消息在平台上的原始ID (可能是数字或字符串)') # 增加长度以防万一
    time = Column(DateTime, default=datetime.datetime.now(SHANGHAI_TZ), comment='消息发送/接收时间 (使用上海时区)')
    
    chat_stream_id = Column(Integer, ForeignKey('chat_streams.id'), index=True, comment='关联的聊天流ID')
    chat_stream = relationship("ChatStream", back_populates="messages") # 与ChatStream表建立多对一关系
    
    user_id = Column(Integer, ForeignKey('users.id'), index=True, comment='发送消息的用户ID')
    user = relationship("User", back_populates="messages_sent") # 与User表建立多对一关系
    
    processed_plain_text = Column(Text, nullable=True, comment='处理后的纯文本消息内容')
    detailed_plain_text = Column(Text, nullable=True, comment='包含详细信息的纯文本消息 (原 detailed_plain_text)')
    memorized_times = Column(Integer, default=0, comment='消息被记忆的次数')

    def __repr__(self):
        return f"<Message(id={self.id}, chat_stream_id={self.chat_stream_id}, user_id={self.user_id})>"

class Image(Base):
    __tablename__ = 'images' # 图片表 (合并原 images 和部分 emoji 字段)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='图片主键ID')
    hash_value = Column(String(191), unique=True, index=True, comment='图片的哈希值 (原 hash)') # 调整String长度
    description = Column(Text, nullable=True, comment='图片的通用描述')
    path = Column(String(512), comment='图片存储的文件路径')
    timestamp = Column(DateTime, comment='图片记录的时间戳 (建议存储UTC时间)')
    image_type = Column(String(50), comment='图片类型 (例如: emoji, general_image)')
    format = Column(String(20), nullable=True, comment='图片格式 (例如: jpeg, png)')
    full_path = Column(String(512), nullable=True, comment='图片的完整存储路径')

    # 定义关系: 一张Image对应一个EmojiDetail (一对一), 可以有多个ImageDescription
    emoji_detail = relationship("EmojiDetail", back_populates="image", uselist=False, cascade="all, delete-orphan")
    image_descriptions = relationship("ImageDescription", back_populates="image", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Image(id={self.id}, hash_value='{self.hash_value}', type='{self.image_type}')>"

class ImageDescription(Base):
    __tablename__ = 'image_descriptions' # 图片描述表 (原 image_descriptions 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='图片描述主键ID')
    
    image_id = Column(Integer, ForeignKey('images.id'), index=True, comment='关联的图片ID')
    image = relationship("Image", back_populates="image_descriptions") # 与Image表建立多对一关系

    description_text = Column(Text, comment='描述文本内容 (原 description)')
    description_type = Column(String(50), nullable=True, comment='描述类型 (例如: emoji, ocr)')
    timestamp = Column(DateTime, comment='描述记录的时间戳 (建议存储UTC时间)')

    def __repr__(self):
        return f"<ImageDescription(id={self.id}, image_id={self.image_id}, type='{self.description_type}')>"

class GraphNode(Base):
    __tablename__ = 'graph_nodes' # 图节点表 (原 graph_data.nodes 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='图节点主键ID')
    concept = Column(String(191), unique=True, index=True, comment='节点的概念名称') # 调整String长度
    hash_value = Column(BigInteger, nullable=True, comment='节点的哈希值 (原 hash, long类型)')
    created_time = Column(DateTime, comment='节点创建时间 (建议存储UTC时间)')
    last_modified = Column(DateTime, comment='节点最后修改时间 (建议存储UTC时间)')

    # 定义关系: 一个GraphNode可以作为多条边的源节点或目标节点，并拥有多个MemoryItem
    source_edges = relationship("GraphEdge", foreign_keys="[GraphEdge.source_node_id]", back_populates="source_node", cascade="all, delete-orphan")
    target_edges = relationship("GraphEdge", foreign_keys="[GraphEdge.target_node_id]", back_populates="target_node", cascade="all, delete-orphan")
    memory_items = relationship("GraphNodeMemoryItem", back_populates="graph_node", cascade="all, delete-orphan") # 规范化后的 memory_items

    def __repr__(self):
        return f"<GraphNode(id={self.id}, concept='{self.concept}')>"

class GraphEdge(Base):
    __tablename__ = 'graph_edges' # 图边表 (原 graph_data.edges 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='图边主键ID')
    
    source_node_id = Column(Integer, ForeignKey('graph_nodes.id'), index=True, comment='边的源节点ID')
    target_node_id = Column(Integer, ForeignKey('graph_nodes.id'), index=True, comment='边的目标节点ID')
    
    source_node = relationship("GraphNode", foreign_keys=[source_node_id], back_populates="source_edges") # 与GraphNode表建立多对一关系 (源)
    target_node = relationship("GraphNode", foreign_keys=[target_node_id], back_populates="target_edges") # 与GraphNode表建立多对一关系 (目标)
    
    strength = Column(Integer, default=1, comment='边的强度/权重')
    hash_value = Column(BigInteger, nullable=True, comment='边的哈希值 (原 hash, long类型)')
    created_time = Column(DateTime, comment='边创建时间 (建议存储UTC时间)')
    last_modified = Column(DateTime, comment='边最后修改时间 (建议存储UTC时间)')

    def __repr__(self):
        return f"<GraphEdge(id={self.id}, source_id={self.source_node_id}, target_id={self.target_node_id})>"

class LlmUsage(Base):
    __tablename__ = 'llm_usage' # LLM 使用记录表 (原 llm_usage 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='LLM使用记录主键ID')
    model_name = Column(String(255), comment='使用的LLM模型名称')
    user_identifier = Column(String(191), index=True, comment='用户标识 (原 user_id, 可能是 system 或其他)') # 调整String长度
    request_type = Column(String(100), comment='请求类型')
    endpoint = Column(String(255), comment='请求的API端点')
    prompt_tokens = Column(Integer, nullable=True, comment='输入token数量')
    completion_tokens = Column(Integer, nullable=True, comment='输出token数量')
    total_tokens = Column(Integer, nullable=True, comment='总token数量')
    cost = Column(Float, nullable=True, comment='本次请求的成本')
    status = Column(String(50), comment='请求状态 (例如: success, error)')
    timestamp = Column(DateTime, comment='记录时间戳 (原 timestamp.$date) (建议存储UTC时间)')

    def __repr__(self):
        return f"<LlmUsage(id={self.id}, model_name='{self.model_name}', user='{self.user_identifier}')>"

class OnlineTime(Base):
    __tablename__ = 'online_time' # 在线时长表 (原 online_time 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='在线时长记录主键ID')
    timestamp = Column(DateTime, comment='记录时间戳 (原 timestamp.$date) (建议存储UTC时间)')
    duration_seconds = Column(Integer, comment='在线持续时长 (单位: 秒, 原 duration)')

    def __repr__(self):
        return f"<OnlineTime(id={self.id}, timestamp='{self.timestamp}', duration={self.duration_seconds}s)>"

class PersonInfo(Base):
    __tablename__ = 'person_info' # 个人信息表 (原 person_info 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='个人信息主键ID')
    person_uuid = Column(String(191), unique=True, index=True, comment='个人信息的唯一标识符 (原 person_id)') # 调整String长度
    
    user_id = Column(Integer, ForeignKey('users.id'), index=True, comment='关联的用户ID')
    user = relationship("User", back_populates="person_infos") # 与User表建立多对一关系
    
    relationship_value = Column(Integer, default=0, comment='关系值/亲密度等')
    known_time = Column(DateTime, comment='初次认识时间 (原 konw_time, 时间戳) (建议存储UTC时间)')
    msg_interval_avg_seconds = Column(Integer, nullable=True, comment='平均消息间隔 (单位: 秒, 原 msg_interval)')
    person_name_override = Column(String(255), nullable=True, comment='对此人的特定称呼 (原 person_name)')
    name_reason = Column(Text, nullable=True, comment='特定称呼的原因')

    # 定义关系: 一个PersonInfo可以有多条MessageIntervalRecord
    message_intervals = relationship("PersonMessageIntervalRecord", back_populates="person_info", cascade="all, delete-orphan") # 规范化后的 msg_interval_list

    def __repr__(self):
        return f"<PersonInfo(id={self.id}, person_uuid='{self.person_uuid}', user_id={self.user_id})>"

class Schedule(Base):
    __tablename__ = 'schedules' # 日程表 (原 schedule 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='日程主键ID')
    schedule_date = Column(Date, comment='日程对应的日期 (原 date, YYYY-MM-DD 字符串)')
    schedule_text = Column(Text, nullable=True, comment='日程的详细文本内容 (原 schedule)')

    # 定义关系: 一个Schedule可以有多个DoneItem
    done_items = relationship("ScheduleDoneItem", back_populates="schedule", cascade="all, delete-orphan") # 规范化后的 today_done_list

    def __repr__(self):
        return f"<Schedule(id={self.id}, date='{self.schedule_date}')>"

class ThinkingLog(Base):
    __tablename__ = 'thinking_logs' # 思考日志表 (原 thinking_log 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='思考日志主键ID')
    
    chat_stream_id = Column(Integer, ForeignKey('chat_streams.id'), index=True, comment='关联的聊天流ID')
    chat_stream = relationship("ChatStream", back_populates="thinking_logs") # 与ChatStream表建立多对一关系
    
    response_mode = Column(String(100), nullable=True, comment='响应模式')
    trigger_text = Column(Text, nullable=True, comment='触发思考的文本')
    response_text = Column(Text, nullable=True, comment='最终响应的文本')
    
    # 使用通用的 sqlalchemy.JSON 类型
    trigger_info_json = Column(JSON, nullable=True, comment='触发信息 (原 trigger_info, JSON格式)')
    response_info_json = Column(JSON, nullable=True, comment='响应信息 (原 response_info, JSON格式)')
    timing_results_json = Column(JSON, nullable=True, comment='计时结果 (原 timing_results, JSON格式)')
    mode_specific_data_json = Column(JSON, nullable=True, comment='特定模式数据 (原 mode_specific_data, JSON格式)')

    # 定义关系: 一个ThinkingLog可以有多条不同类型的ChatHistoryEntry
    chat_history_entries = relationship("ThinkingLogChatHistoryEntry", back_populates="thinking_log", cascade="all, delete-orphan")
    chat_history_in_thinking_entries = relationship("ThinkingLogChatHistoryInThinkingEntry", back_populates="thinking_log", cascade="all, delete-orphan")
    chat_history_after_response_entries = relationship("ThinkingLogChatHistoryAfterResponseEntry", back_populates="thinking_log", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<ThinkingLog(id={self.id}, chat_stream_id={self.chat_stream_id})>"

# --- 为嵌套结构规范化出来的新表 ---

class EmojiDetail(Base):
    __tablename__ = 'emoji_details' # Emoji 详细信息表 (原 emoji 集合的特有字段)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='Emoji详情主键ID')
    image_id = Column(Integer, ForeignKey('images.id'), unique=True, index=True, comment='关联的图片ID (与Image表一对一)')
    image = relationship("Image", back_populates="emoji_detail") # 与Image表建立一对一关系
    detailed_description = Column(Text, nullable=True, comment='Emoji的详细描述 (原 emoji.description)')
    embedding_json = Column(JSON, nullable=True, comment='Emoji的嵌入向量 (原 embedding, JSON格式)') # 使用通用 JSON
    last_used_time = Column(DateTime, nullable=True, comment='Emoji最后使用时间 (建议存储UTC时间)')
    usage_count = Column(Integer, default=0, comment='Emoji使用次数')

    # 定义关系: 一个EmojiDetail可以有多个Emotion标签
    emotions = relationship("EmojiEmotion", back_populates="emoji_detail", cascade="all, delete-orphan") # 规范化后的 emotion 列表

    def __repr__(self):
        return f"<EmojiDetail(id={self.id}, image_id={self.image_id})>"

class EmojiEmotion(Base):
    __tablename__ = 'emoji_emotions' # Emoji 情感标签表
    id = Column(Integer, primary_key=True, autoincrement=True, comment='Emoji情感标签主键ID')
    emoji_detail_id = Column(Integer, ForeignKey('emoji_details.id'), index=True, comment='关联的Emoji详情ID')
    emoji_detail = relationship("EmojiDetail", back_populates="emotions") # 与EmojiDetail表建立多对一关系
    emotion = Column(String(255), comment='单个情感标签文本')

    def __repr__(self):
        return f"<EmojiEmotion(id={self.id}, emotion='{self.emotion}')>"

class GraphNodeMemoryItem(Base):
    __tablename__ = 'graph_node_memory_items' # 图节点记忆项表
    id = Column(Integer, primary_key=True, autoincrement=True, comment='图节点记忆项主键ID')
    graph_node_id = Column(Integer, ForeignKey('graph_nodes.id'), index=True, comment='关联的图节点ID')
    graph_node = relationship("GraphNode", back_populates="memory_items") # 与GraphNode表建立多对一关系
    item_text = Column(Text, comment='单个记忆项的文本内容')
    order = Column(Integer, nullable=True, comment='可选：用于保持原始列表中的顺序')

    def __repr__(self):
        return f"<GraphNodeMemoryItem(id={self.id}, text='{self.item_text[:50]}...')>"

class PersonMessageIntervalRecord(Base):
    __tablename__ = 'person_message_interval_records' # 个人消息间隔记录表
    id = Column(Integer, primary_key=True, autoincrement=True, comment='消息间隔记录主键ID')
    person_info_id = Column(Integer, ForeignKey('person_info.id'), index=True, comment='关联的个人信息ID')
    person_info = relationship("PersonInfo", back_populates="message_intervals") # 与PersonInfo表建立多对一关系
    timestamp_ms = Column(BigInteger, comment='原始的毫秒级时间戳 (原 msg_interval_list中的项)')

    def __repr__(self):
        return f"<PersonMessageIntervalRecord(id={self.id}, timestamp_ms={self.timestamp_ms})>"

class ScheduleDoneItem(Base):
    __tablename__ = 'schedule_done_items' # 日程已完成项表
    id = Column(Integer, primary_key=True, autoincrement=True, comment='日程已完成项主键ID')
    schedule_id = Column(Integer, ForeignKey('schedules.id'), index=True, comment='关联的日程ID')
    schedule = relationship("Schedule", back_populates="done_items") # 与Schedule表建立多对一关系
    item_timestamp = Column(DateTime, comment='完成项的时间戳 (原 today_done_list中$date字段) (建议存储UTC时间)')
    description = Column(Text, comment='完成项的描述文本')
    order = Column(Integer, nullable=True, comment='可选：用于保持原始列表中的顺序')

    def __repr__(self):
        return f"<ScheduleDoneItem(id={self.id}, timestamp='{self.item_timestamp}', description='{self.description[:50]}...')>"

# 思考日志相关的聊天历史记录表的抽象基类
class ThinkingLogChatHistoryEntryBase(Base):
    __abstract__ = True # 声明此类为抽象基类，不会被映射到数据库表
    id = Column(Integer, primary_key=True, autoincrement=True, comment='聊天历史记录主键ID')
    thinking_log_id = Column(Integer, ForeignKey('thinking_logs.id'), index=True, comment='关联的思考日志ID')
    time = Column(Float, nullable=True, comment='记录时间 (原数据中的浮点数时间戳)') # 注意：浮点数时间戳可能在不同DB中精度处理有差异
    user_nickname = Column(String(255), nullable=True, comment='用户昵称')
    processed_plain_text = Column(Text, nullable=True, comment='处理后的纯文本内容')
    order = Column(Integer, nullable=True, comment='可选：用于保持原始列表中的顺序')

class ThinkingLogChatHistoryEntry(ThinkingLogChatHistoryEntryBase):
    __tablename__ = 'thinking_log_chat_history_entries' # 思考日志的通用聊天历史记录表
    thinking_log = relationship("ThinkingLog", back_populates="chat_history_entries") # 与ThinkingLog表建立多对一关系
    def __repr__(self):
        return f"<ThinkingLogChatHistoryEntry(id={self.id}, nickname='{self.user_nickname}')>"

class ThinkingLogChatHistoryInThinkingEntry(ThinkingLogChatHistoryEntryBase):
    __tablename__ = 'thinking_log_chat_history_in_thinking_entries' # 思考日志的"思考时"聊天历史记录表
    thinking_log = relationship("ThinkingLog", back_populates="chat_history_in_thinking_entries") # 与ThinkingLog表建立多对一关系
    def __repr__(self):
        return f"<ThinkingLogChatHistoryInThinkingEntry(id={self.id}, nickname='{self.user_nickname}')>"

class ThinkingLogChatHistoryAfterResponseEntry(ThinkingLogChatHistoryEntryBase):
    __tablename__ = 'thinking_log_chat_history_after_response_entries' # 思考日志的"响应后"聊天历史记录表
    thinking_log = relationship("ThinkingLog", back_populates="chat_history_after_response_entries") # 与ThinkingLog表建立多对一关系
    def __repr__(self):
        return f"<ThinkingLogChatHistoryAfterResponseEntry(id={self.id}, nickname='{self.user_nickname}')>"

class RecalledMessage(Base):
    __tablename__ = 'recalled_messages' # 撤回消息表 (原 recalled_messages 集合)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='撤回消息主键ID')
    message_platform_id = Column(String(255), comment='消息在平台上的原始ID (可能是数字或字符串)')
    time = Column(DateTime, comment='撤回消息的时间')
    stream_uuid = Column(String(191), index=True, comment='对应的聊天流唯一标识符')

    def __repr__(self):
        return f"<RecalledMessage(id={self.id}, message_platform_id='{self.message_platform_id}', stream_uuid='{self.stream_uuid}')>"


