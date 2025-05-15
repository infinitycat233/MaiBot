#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据库模块初始化

此模块用于组织和初始化数据库相关的组件，
支持SQLite、MySQL、PostgreSQL和MongoDB等数据库引擎。
"""

# 从database模块导出核心组件
from .database import (
    # 数据库配置和连接
    DatabaseConfig, 
    init_database,
    create_db_url,
    get_session,
    get_mongo_db,
    close_all_connections,
    init_from_env,
    
    # SQLAlchemy基础组件
    DeclarativeBase, 
    metadata,
    
    # 全局数据库实例
    db,
    DBWrapper
)

# 延迟导入数据库检查器模块，避免循环导入
# 在函数内部导入，而不是全局导入
def import_checker():
    from .database_checker import check_and_migrate_database
    return check_and_migrate_database

# 确保models模块中的所有模型都被加载，这样元数据会包含所有表定义
# 从而支持正确地创建表结构
from . import models

# 定义公开的API
__all__ = [
    # 数据库配置和连接
    'DatabaseConfig', 
    'init_database',
    'create_db_url',
    'get_session',
    'get_mongo_db', 
    'close_all_connections',
    'init_from_env',
    
    # SQLAlchemy基础组件
    'DeclarativeBase',
    'metadata',
    
    # 全局数据库实例
    'db',
    'DBWrapper',
    
    # 模型模块
    'models',
    
    # 数据库检查器
    'import_checker',
]

# 初始化表结构函数
def init_tables(engine=None, checkfirst=True):
    """
    初始化数据库表结构
    
    当未使用Alembic等迁移工具时，可以调用此函数来创建表结构
    
    Args:
        engine: SQLAlchemy引擎实例，如果为None则使用默认引擎
        checkfirst: 是否在创建表前检查表是否已存在
    """
    from .database import _engines
    
    if engine is None:
        # 使用默认引擎
        if not _engines:
            raise ValueError("数据库引擎未初始化，请先调用init_database函数")
        engine = next(iter(_engines.values()))
    
    # 创建所有表
    metadata.create_all(engine, checkfirst=checkfirst)
    return True 