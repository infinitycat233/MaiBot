import os
from typing import Dict, Any, Optional, Union, cast
import logging
from urllib.parse import quote_plus

from sqlalchemy import create_engine, MetaData, Engine
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.engine import URL

# MongoDB支持
from pymongo import MongoClient
from pymongo.database import Database as MongoDatabase

from rich.traceback import install

install(extra_lines=3)

logger = logging.getLogger(__name__)

# SQLAlchemy基础配置
DeclarativeBase = declarative_base()
metadata = DeclarativeBase.metadata

# 数据库引擎和会话
_engines: Dict[str, Engine] = {}
_sessions: Dict[str, scoped_session] = {}
_mongo_clients: Dict[str, MongoClient] = {}
_mongo_dbs: Dict[str, MongoDatabase] = {}

# 默认数据库名称
DEFAULT_DB_NAME = "main"


class DatabaseConfig:
    """数据库配置类"""
    
    def __init__(
        self,
        db_type: str,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        database: str = "MegBot",
        uri: Optional[str] = None,
        auth_source: Optional[str] = None,
        **kwargs
    ):
        self.db_type = db_type.lower()  # sqlite, mysql, postgresql, mongodb
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.database = database
        self.uri = uri
        self.auth_source = auth_source
        self.extra_params = kwargs


def create_db_url(config: DatabaseConfig) -> Optional[Union[str, URL]]:
    """根据配置创建数据库URL"""
    
    # 如果提供了URI，直接使用
    if config.uri:
        # 确保URI是有效格式
        if isinstance(config.uri, str) and ("://" in config.uri):
            return config.uri
        else:
            logger.warning(f"提供的URI格式无效: {config.uri}")
    
    if config.db_type == "sqlite":
        # SQLite可以使用相对路径或内存数据库
        if config.database == ":memory:":
            return "sqlite:///:memory:"
        
        # 确保数据库文件名有.db后缀
        db_path = config.database if config.database.endswith(".db") else f"{config.database}.db"
        
        # 如果是绝对路径，直接使用；否则，使用相对路径
        if os.path.isabs(db_path):
            return f"sqlite:///{db_path}"
        else:
            # 确保路径存在
            db_dir = os.path.dirname(db_path) if os.path.dirname(db_path) else "."
            if not os.path.exists(db_dir) and db_dir != ".":
                try:
                    os.makedirs(db_dir, exist_ok=True)
                except Exception as e:
                    logger.warning(f"创建SQLite数据库目录失败: {e}")
            
            return f"sqlite:///{db_path}"
    
    elif config.db_type == "mongodb":
        # MongoDB不使用SQLAlchemy URL
        return None
    
    # 对于MySQL和PostgreSQL构建URL
    driver_map = {
        "mysql": "mysql+pymysql",
        "mariadb": "mysql+pymysql",  # MariaDB使用相同的MySQL驱动
        "postgresql": "postgresql+psycopg2",
    }
    
    # 获取合适的驱动
    driver = driver_map.get(config.db_type)
    if not driver:
        logger.error(f"不支持的数据库类型: {config.db_type}")
        raise ValueError(f"不支持的数据库类型: {config.db_type}")
    
    # 检查必要的连接参数
    if not config.host or config.host.strip() == "":
        config.host = "localhost"  # 使用默认主机名
        logger.info(f"主机名为空，使用默认值: localhost")
    
    # 构建认证部分
    auth = ""
    if config.username:
        auth = quote_plus(config.username)
        if config.password:
            auth += f":{quote_plus(config.password)}"
        auth += "@"
    
    # 构建主机部分
    host_part = config.host
    if config.port:
        host_part = f"{host_part}:{config.port}"
    
    # 构建额外参数
    params = []
    if config.auth_source:
        params.append(f"authSource={config.auth_source}")
    
    # 添加特定参数 - 但跳过echo参数，它会在创建引擎时使用
    extra_params = config.extra_params.copy()
    if 'echo' in extra_params:
        del extra_params['echo']
    
    for key, value in extra_params.items():
        params.append(f"{key}={value}")
    
    params_str = ""
    if params:
        params_str = "?" + "&".join(params)
    
    # 生成最终URL
    try:
        url = f"{driver}://{auth}{host_part}/{config.database}{params_str}"
        return url
    except Exception as e:
        logger.error(f"构建数据库URL时出错: {e}")
        # 在无法构建URL时，返回None而不是抛出异常
        return None


def init_database(config: DatabaseConfig, db_name: str = DEFAULT_DB_NAME) -> Union[scoped_session, MongoDatabase]:
    """初始化数据库连接"""
    
    global _engines, _sessions, _mongo_clients, _mongo_dbs
    
    if config.db_type == "mongodb":
        # MongoDB特殊处理
        if db_name in _mongo_dbs:
            return _mongo_dbs[db_name]
        
        try:
            if config.uri:
                if config.uri.startswith(("mongodb://", "mongodb+srv://")):
                    client = MongoClient(config.uri)
                else:
                    logger.error(
                        "无效的MongoDB URI格式。URI必须以'mongodb://'或'mongodb+srv://'开头。"
                        "对于MongoDB Atlas，使用'mongodb+srv://'格式。"
                        "参见: https://www.mongodb.com/docs/manual/reference/connection-string/"
                    )
                    raise ValueError("无效的MongoDB URI格式")
            elif config.username and config.password:
                # 使用认证连接
                client = MongoClient(
                    config.host or "localhost",
                    config.port or 27017,
                    username=config.username,
                    password=config.password,
                    authSource=config.auth_source or "admin"
                )
            else:
                # 无认证连接
                client = MongoClient(config.host or "localhost", config.port or 27017)
            
            _mongo_clients[db_name] = client
            _mongo_dbs[db_name] = client[config.database]
            logger.info(f"已初始化MongoDB连接: {db_name}")
            return _mongo_dbs[db_name]
        except Exception as e:
            logger.error(f"初始化MongoDB连接失败: {e}")
            raise
    
    else:
        # SQLAlchemy数据库处理
        if db_name in _sessions:
            return _sessions[db_name]
        
        try:
            # 生成数据库URL
            db_url = create_db_url(config)
            if db_url is None:
                raise ValueError(f"无法为数据库类型 {config.db_type} 创建连接URL")
            
            # 创建引擎
            logger.debug(f"创建数据库引擎，类型: {config.db_type}，URL: {db_url}")
            engine_args = {
                "pool_pre_ping": True,
                "pool_recycle": 3600,
            }
            
            # 从extra_params获取echo参数
            if 'echo' in config.extra_params:
                engine_args['echo'] = config.extra_params['echo']
            
            # 添加数据库特定参数
            if config.db_type in ["mysql", "mariadb"]:
                # 添加MySQL/MariaDB池大小参数
                if "pool_size" in config.extra_params:
                    engine_args["pool_size"] = config.extra_params["pool_size"]
            
            engine = create_engine(db_url, **engine_args)
            
            _engines[db_name] = engine
            
            # 创建会话
            session_factory = sessionmaker(bind=engine, autoflush=True, autocommit=False)
            _sessions[db_name] = scoped_session(session_factory)
            
            # 如果是SQLite且数据库不存在，则创建表
            if config.db_type == "sqlite" and config.database != ":memory:" and not os.path.exists(config.database):
                try:
                    logger.info(f"SQLite数据库文件不存在，创建表结构: {config.database}")
                    metadata.create_all(engine)
                except Exception as table_err:
                    logger.error(f"创建SQLite表结构失败: {table_err}")
            
            logger.info(f"已初始化{config.db_type.upper()}连接: {db_name}")
            return _sessions[db_name]
        except Exception as e:
            logger.error(f"初始化数据库连接失败 ({config.db_type}): {e}")
            raise


def get_session(db_name: str = DEFAULT_DB_NAME) -> Session:
    """获取SQLAlchemy会话"""
    if db_name not in _sessions:
        raise ValueError(f"数据库'{db_name}'未初始化，请先调用init_database")
    return cast(Session, _sessions[db_name])


def get_mongo_db(db_name: str = DEFAULT_DB_NAME) -> MongoDatabase:
    """获取MongoDB数据库实例"""
    if db_name not in _mongo_dbs:
        raise ValueError(f"MongoDB数据库'{db_name}'未初始化，请先调用init_database")
    return _mongo_dbs[db_name]


def close_all_connections():
    """关闭所有数据库连接"""
    # 关闭SQLAlchemy会话
    for name, session in _sessions.items():
        try:
            session.remove()
            logger.debug(f"已关闭SQLAlchemy会话: {name}")
        except Exception as e:
            logger.error(f"关闭SQLAlchemy会话'{name}'时出错: {e}")
    
    # 关闭SQLAlchemy引擎
    for name, engine in _engines.items():
        try:
            engine.dispose()
            logger.debug(f"已关闭数据库引擎: {name}")
        except Exception as e:
            logger.error(f"关闭数据库引擎'{name}'时出错: {e}")
    
    # 关闭MongoDB客户端
    for name, client in _mongo_clients.items():
        try:
            client.close()
            logger.debug(f"已关闭MongoDB客户端: {name}")
        except Exception as e:
            logger.error(f"关闭MongoDB客户端'{name}'时出错: {e}")
    
    # 清空缓存
    _engines.clear()
    _sessions.clear()
    _mongo_clients.clear()
    _mongo_dbs.clear()


def init_from_env():
    """从环境变量初始化数据库连接"""
    db_type = os.getenv("DB_TYPE", "sqlite").lower()
    
    # 定义支持的数据库类型
    supported_dbs = ["sqlite", "mysql", "mariadb", "postgresql", "mongodb"]
    
    if db_type not in supported_dbs:
        logger.warning(f"不支持的数据库类型: {db_type}，将使用默认的SQLite")
        db_type = "sqlite"
    
    # 统一获取不同数据库的环境变量
    # 格式: DB_{参数名} 或 {DB_TYPE}_{参数名}
    def get_db_env(param_name, default=None):
        """获取数据库环境变量
        
        优先级:
        1. {DB_TYPE}_{参数名} (如 MYSQL_HOST, MONGODB_PORT)
        2. DB_{参数名} (如 DB_HOST, DB_PORT)
        3. 默认值
        """
        type_specific = os.getenv(f"{db_type.upper()}_{param_name}")
        if type_specific is not None:
            return type_specific
        
        generic = os.getenv(f"DB_{param_name}")
        if generic is not None:
            return generic
        
        return default
    
    # 处理端口环境变量
    port_str = get_db_env("PORT")
    port = int(port_str) if port_str and port_str.isdigit() else None
    
    # 确保数据库名称有默认值
    db_name = get_db_env("NAME", "MegBot")
    if db_type == "sqlite" and not db_name.endswith(".db"):
        db_name = f"{db_name}.db"
    
    # 检查是否有直接的URI配置
    uri = get_db_env("URI")
    if uri and isinstance(uri, str) and uri.startswith((
        'sqlite://', 
        'mysql+pymysql://', 
        'postgresql+psycopg2://', 
        'mssql+pyodbc://'
    )):
        logger.info(f"使用直接配置的数据库URI: {uri}")
        config = DatabaseConfig(
            db_type=db_type,
            database=db_name,
            uri=uri
        )
    else:
        # 创建统一的数据库配置
        config = DatabaseConfig(
            db_type=db_type,
            host=get_db_env("HOST", "localhost"),  # 默认使用localhost作为主机名
            port=port,
            username=get_db_env("USERNAME"),
            password=get_db_env("PASSWORD"),
            database=db_name,
            uri=None,  # 这里不使用URI，强制通过组件构建
            auth_source=get_db_env("AUTH_SOURCE"),
            echo=get_db_env("ECHO", "False").lower() == "true"
        )
        
        # 兼容MongoDB旧的环境变量格式
        if db_type == "mongodb":
            # 处理DATABASE_NAME特殊环境变量
            if os.getenv("DATABASE_NAME"):
                database_name = os.getenv("DATABASE_NAME")
                if database_name:  # 确保不是None
                    config.database = database_name
        
        # 数据库特定的额外参数
        extra_params = {}
        
        # MariaDB/MySQL特定配置
        if db_type in ["mariadb", "mysql"]:
            charset = get_db_env("CHARSET", "utf8mb4")
            collation = get_db_env("COLLATION", "utf8mb4_unicode_ci")
            extra_params.update({
                "charset": charset,
                "collation": collation
            })
            
            # 池大小设置
            pool_size_str = get_db_env("POOL_SIZE", "10")
            if pool_size_str and pool_size_str.isdigit():
                extra_params["pool_size"] = int(pool_size_str)
        
        # PostgreSQL特定配置
        elif db_type == "postgresql":
            # 客户端编码
            client_encoding = get_db_env("CLIENT_ENCODING", "utf8")
            if client_encoding:
                extra_params["client_encoding"] = client_encoding
        
        # 添加额外参数到配置
        if extra_params:
            config.extra_params.update(extra_params)
    
    # 日志输出当前配置
    logger.info(f"初始化数据库连接: 类型={config.db_type}, 主机={config.host}, 端口={config.port}, 数据库={config.database}")
    
    # 验证基本配置
    if db_type != "sqlite" and db_type != "mongodb" and not config.host:
        logger.warning(f"未设置{db_type}数据库主机地址，将使用默认值'localhost'")
        config.host = "localhost"
    
    # 尝试检查URI格式
    db_url = None
    try:
        db_url = create_db_url(config)
        if db_url and isinstance(db_url, str):
            logger.debug(f"生成的数据库URL: {db_url}")
        elif db_url is None and db_type != "mongodb":
            logger.warning(f"无法生成有效的数据库URL，将使用默认SQLite配置")
            # 如果是SQLite，提供默认URL
            if db_type == "sqlite":
                db_url = f"sqlite:///{config.database}"
                logger.info(f"使用默认SQLite URL: {db_url}")
                config.uri = db_url
    except Exception as e:
        logger.error(f"生成数据库URL时出错: {e}")
        # 如果是SQLite，提供默认URL
        if db_type == "sqlite":
            db_url = f"sqlite:///{config.database}"
            logger.info(f"使用默认SQLite URL: {db_url}")
            config.uri = db_url
    
    try:
        db_instance = init_database(config)
        
        # 如果是非MongoDB数据库，尝试自动检查表结构
        # 这里只导入需要时才使用的模块，避免循环导入问题
        if db_type != "mongodb" and os.getenv("AUTO_CHECK_DB", "true").lower() == "true":
            try:
                from .database_checker import DatabaseChecker
                checker = DatabaseChecker()
                # 仅执行检查，不自动迁移，避免在此处执行可能耗时的操作
                missing_tables = checker.get_missing_tables()
                if missing_tables:
                    logger.warning(f"检测到数据库缺少表: {', '.join(missing_tables)}")
                    logger.info("系统启动时将尝试自动迁移数据库")
            except Exception as e:
                logger.warning(f"数据库表结构检查失败: {e}")
        
        return db_instance
    except Exception as e:
        logger.error(f"初始化数据库连接失败: {e}")
        if db_type == "sqlite":
            # SQLite出错时尝试创建内存数据库作为后备
            logger.warning("尝试使用SQLite内存数据库作为后备...")
            memory_config = DatabaseConfig(
                db_type="sqlite",
                database=":memory:",
                echo=True  # 内存数据库打开调试以便追踪问题
            )
            try:
                return init_database(memory_config)
            except Exception as mem_error:
                logger.error(f"创建内存数据库也失败: {mem_error}")
        
        # 重新抛出异常
        raise


# 默认数据库实例 - 兼容旧代码的全局访问点
db = init_from_env()


class DBWrapper:
    """数据库代理类，保持接口兼容性"""
    
    def __init__(self, db_name: str = DEFAULT_DB_NAME):
        self.db_name = db_name
    
    def __getattr__(self, name):
        if self.db_name in _mongo_dbs:
            return getattr(_mongo_dbs[self.db_name], name)
        elif self.db_name in _sessions:
            return getattr(_sessions[self.db_name], name)
        raise AttributeError(f"数据库'{self.db_name}'未初始化")
    
    def __getitem__(self, key):
        if self.db_name in _mongo_dbs:
            return _mongo_dbs[self.db_name][key]
        raise AttributeError(f"只有MongoDB支持此操作") 