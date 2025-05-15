#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据库配置检查脚本

此脚本用于检查和修复当前数据库配置，并提供摘要信息。
"""

import os
import sys
import logging
from pathlib import Path
import traceback

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('db_config_check')

# 添加项目根目录到PATH
root_dir = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(root_dir))

try:
    # 导入数据库相关模块
    from src.db.database import create_db_url, DatabaseConfig
except ImportError as e:
    logger.error(f"导入模块失败: {e}")
    logger.error("请确保你在项目根目录下运行此脚本")
    sys.exit(1)

def get_current_db_config():
    """获取当前数据库配置"""
    db_type = os.getenv("DB_TYPE", "sqlite").lower()
    
    # 定义支持的数据库类型
    supported_dbs = ["sqlite", "mysql", "mariadb", "postgresql", "mongodb"]
    
    if db_type not in supported_dbs:
        logger.warning(f"不支持的数据库类型: {db_type}，将使用默认的SQLite")
        db_type = "sqlite"
    
    # 统一获取不同数据库的环境变量
    def get_db_env(param_name, default=None):
        """获取数据库环境变量"""
        type_specific = os.getenv(f"{db_type.upper()}_{param_name}")
        if type_specific is not None:
            return type_specific
        
        generic = os.getenv(f"DB_{param_name}")
        if generic is not None:
            return generic
        
        return default
    
    # 获取基本配置
    host = get_db_env("HOST", "localhost")
    port_str = get_db_env("PORT")
    port = int(port_str) if port_str and port_str.isdigit() else None
    username = get_db_env("USERNAME")
    password = get_db_env("PASSWORD")
    db_name = get_db_env("NAME", "MegBot")
    uri = get_db_env("URI")
    
    # 数据库特定配置
    db_specific = {}
    
    if db_type == "sqlite":
        if not db_name.endswith(".db"):
            db_name = f"{db_name}.db"
        
        # 检查数据库文件是否存在
        if not db_name == ":memory:" and not os.path.isabs(db_name):
            db_path = os.path.join(root_dir, db_name)
            db_specific["file_exists"] = os.path.exists(db_path)
            db_specific["file_path"] = db_path
    
    elif db_type in ["mysql", "mariadb"]:
        db_specific["charset"] = get_db_env("CHARSET", "utf8mb4")
        db_specific["collation"] = get_db_env("COLLATION", "utf8mb4_unicode_ci")
        db_specific["pool_size"] = get_db_env("POOL_SIZE", "10")
    
    elif db_type == "postgresql":
        db_specific["client_encoding"] = get_db_env("CLIENT_ENCODING", "utf8")
    
    elif db_type == "mongodb":
        db_specific["auth_source"] = get_db_env("AUTH_SOURCE", "admin")
        # 兼容旧环境变量
        if os.getenv("DATABASE_NAME"):
            db_name = os.getenv("DATABASE_NAME")
    
    # 创建配置对象
    config = DatabaseConfig(
        db_type=db_type,
        host=host,
        port=port,
        username=username,
        password=password,
        database=db_name,
        uri=uri,
        auth_source=get_db_env("AUTH_SOURCE"),
        **db_specific
    )
    
    # 生成URL
    url = None
    try:
        url = create_db_url(config)
    except Exception as e:
        logger.error(f"生成数据库URL时出错: {e}")
    
    return {
        "type": db_type,
        "host": host,
        "port": port,
        "username": username,
        "password": "***" if password else None,
        "database": db_name,
        "uri": uri,
        "url": url,
        "specific": db_specific
    }

def load_env_file(file_path):
    """加载环境变量文件"""
    if not os.path.exists(file_path):
        logger.error(f"环境变量文件不存在: {file_path}")
        return False
    
    logger.info(f"加载环境变量文件: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过注释和空行
                if not line or line.startswith('#'):
                    continue
                
                # 解析环境变量
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # 去掉可能的引号
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                
                # 设置环境变量
                os.environ[key] = value
        
        logger.info("环境变量加载成功")
        return True
    except Exception as e:
        logger.error(f"加载环境变量文件失败: {e}")
        return False

def check_and_fix_sqlite_config():
    """检查并修复SQLite配置"""
    config = get_current_db_config()
    
    if config["type"] != "sqlite":
        return
    
    # 检查文件是否存在
    db_path = config["specific"].get("file_path")
    if db_path and not config["specific"].get("file_exists", False):
        logger.warning(f"SQLite数据库文件不存在: {db_path}")
        
        # 检查目录是否存在
        dir_path = os.path.dirname(db_path)
        if not os.path.exists(dir_path) and dir_path:
            try:
                os.makedirs(dir_path, exist_ok=True)
                logger.info(f"已创建SQLite数据库目录: {dir_path}")
            except Exception as e:
                logger.error(f"创建SQLite数据库目录失败: {e}")
    
    # 验证URL格式
    url = config["url"]
    if not url or not isinstance(url, str) or not url.startswith("sqlite:///"):
        logger.warning(f"SQLite URL格式无效: {url}")
        
        # 修复URL
        fixed_url = f"sqlite:///{config['database']}"
        logger.info(f"已修复SQLite URL: {fixed_url}")
        
        # 更新环境变量
        os.environ["DB_URI"] = fixed_url
        logger.info("已更新环境变量DB_URI")

def print_config_summary(config):
    """打印配置摘要"""
    print("\n" + "="*60)
    print("数据库配置摘要")
    print("="*60)
    print(f"数据库类型: {config['type']}")
    
    if config["uri"]:
        print(f"URI: {config['uri']}")
    else:
        print(f"主机: {config['host']}")
        print(f"端口: {config['port']}")
        print(f"用户名: {config['username']}")
        print(f"密码: {'已设置' if config['password'] else '未设置'}")
        print(f"数据库名: {config['database']}")
    
    print(f"生成的URL: {config['url']}")
    
    if config["specific"]:
        print("\n特定参数:")
        for key, value in config["specific"].items():
            print(f"  {key}: {value}")
    
    print("="*60)

def suggest_fixes(config):
    """建议修复方案"""
    issues = []
    
    # 检查URL是否有效
    if not config["url"]:
        issues.append("无法生成有效的数据库URL")
    
    # 检查特定问题
    if config["type"] == "sqlite":
        if not config["specific"].get("file_exists", True):
            issues.append(f"SQLite数据库文件不存在: {config['specific'].get('file_path')}")
    
    elif config["type"] in ["mysql", "mariadb", "postgresql"]:
        if not config["host"]:
            issues.append("未设置数据库主机地址")
        
        if not config["port"]:
            issues.append("未设置数据库端口")
        
        if not config["username"]:
            issues.append("未设置数据库用户名")
        
        if not config["password"]:
            issues.append("未设置数据库密码")
    
    # 打印问题和建议
    if issues:
        print("\n检测到以下问题:")
        for issue in issues:
            print(f"  - {issue}")
        
        print("\n建议修复方案:")
        if config["type"] == "sqlite":
            # SQLite建议
            print("  - 使用配置文件: cp template/db_sqlite.env .env")
            print("  - 或设置环境变量:")
            print("    DB_TYPE=sqlite")
            print(f"    DB_NAME={config['database']}")
        
        elif config["type"] in ["mysql", "mariadb"]:
            # MySQL/MariaDB建议
            print(f"  - 使用配置文件: cp template/db_{config['type']}.env .env")
            print("  - 或设置以下环境变量:")
            print(f"    DB_TYPE={config['type']}")
            print("    DB_HOST=数据库主机地址")
            print("    DB_PORT=3306")
            print("    DB_USERNAME=用户名")
            print("    DB_PASSWORD=密码")
            print(f"    DB_NAME={config['database']}")
        
        elif config["type"] == "postgresql":
            # PostgreSQL建议
            print("  - 使用配置文件: cp template/db_postgresql.env .env")
            print("  - 或设置以下环境变量:")
            print("    DB_TYPE=postgresql")
            print("    DB_HOST=数据库主机地址")
            print("    DB_PORT=5432")
            print("    DB_USERNAME=用户名")
            print("    DB_PASSWORD=密码")
            print(f"    DB_NAME={config['database']}")
        
        # 通用建议
        print("\n  - 也可以直接设置数据库URI:")
        if config["type"] == "sqlite":
            print(f"    DB_URI=sqlite:///{config['database']}")
        elif config["type"] == "mysql":
            print("    DB_URI=mysql+pymysql://user:password@localhost:3306/database")
        elif config["type"] == "mariadb":
            print("    DB_URI=mysql+pymysql://user:password@localhost:3306/database")
        elif config["type"] == "postgresql":
            print("    DB_URI=postgresql+psycopg2://user:password@localhost:5432/database")
        
        print("\n  - 或查看模板文件获取更多信息: template/db_config_examples.md")
    
    else:
        print("\n未检测到配置问题。")

def main():
    """主函数"""
    # 处理命令行参数
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help" or sys.argv[1] == "-h":
            print("用法: python scripts/check_db_config.py [选项]")
            print("选项:")
            print("  --env-file=FILE  使用指定的环境变量文件")
            print("  --fix            尝试自动修复常见问题")
            print("  --help, -h       显示此帮助信息")
            return 0
        
        # 处理环境变量文件
        for arg in sys.argv[1:]:
            if arg.startswith("--env-file="):
                env_file = arg.split("=")[1]
                if not os.path.isabs(env_file):
                    env_file = os.path.join(root_dir, env_file)
                if not load_env_file(env_file):
                    return 1
    
    try:
        # 获取当前配置
        config = get_current_db_config()
        
        # 如果指定了修复选项
        if "--fix" in sys.argv:
            if config["type"] == "sqlite":
                check_and_fix_sqlite_config()
                # 重新获取配置
                config = get_current_db_config()
        
        # 打印配置摘要
        print_config_summary(config)
        
        # 建议修复方案
        suggest_fixes(config)
        
        # 列出可用的模板
        print("\n可用的配置模板:")
        for template in ["db_sqlite.env", "db_mysql.env", "db_mariadb.env", "db_postgresql.env", "db_mongodb.env"]:
            template_path = os.path.join(root_dir, "template", template)
            if os.path.exists(template_path):
                print(f"  - {template}")
        
        return 0
    
    except Exception as e:
        logger.error(f"检查数据库配置时出错: {e}")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main()) 