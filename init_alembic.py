#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Alembic数据库迁移初始化工具

此脚本用于初始化Alembic迁移环境，自动生成迁移脚本，
并执行数据库升级/降级操作。适用于管理SQLAlchemy模型的数据库结构变更。
"""

import os
import sys
import argparse
import shutil
import subprocess
import importlib
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress

# 添加项目根目录到Python路径
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.append(root_path)

# 导入数据库模块
from src.db import (
    DatabaseConfig, metadata, create_db_url
)
# 导入所有模型以确保它们被元数据加载
from src.db import models

# 尝试导入alembic模块
try:
    from alembic.config import Config
    from alembic import command
    ALEMBIC_AVAILABLE = True
except ImportError:
    ALEMBIC_AVAILABLE = False


def get_sql_config():
    """获取SQL数据库配置"""
    db_type = os.getenv("SQL_DB_TYPE", "sqlite").lower()
    
    config = DatabaseConfig(
        db_type=db_type,
        host=os.getenv("SQL_DB_HOST"),
        port=int(os.getenv("SQL_DB_PORT")) if os.getenv("SQL_DB_PORT") else None,
        username=os.getenv("SQL_DB_USERNAME"),
        password=os.getenv("SQL_DB_PASSWORD"),
        database=os.getenv("SQL_DB_NAME", "megbot_sql"),
        uri=os.getenv("SQL_DB_URI"),
        auth_source=os.getenv("SQL_DB_AUTH_SOURCE"),
        echo=os.getenv("SQL_DB_ECHO", "False").lower() == "true"
    )
    
    return config


def init_alembic(force=False):
    """初始化Alembic环境"""
    console = Console()
    
    if not ALEMBIC_AVAILABLE:
        console.print("[bold red]错误: 未安装alembic模块，请先运行 pip install alembic[/bold red]")
        return False
    
    # 检查是否已有alembic目录
    if os.path.exists('alembic') and not force:
        console.print("[yellow]Alembic目录已存在。使用--force参数覆盖现有目录。[/yellow]")
        return False
    
    if os.path.exists('alembic') and force:
        console.print("[yellow]正在删除现有Alembic目录...[/yellow]")
        shutil.rmtree('alembic')
    
    # 创建alembic.ini文件和alembic目录
    console.print("[bold]正在初始化Alembic环境...[/bold]")
    
    try:
        # 使用Python API初始化alembic
        command.init(Config(), 'alembic', package=True)  # 使用package=True创建__init__.py文件
        console.print("[green]Alembic环境初始化成功[/green]")
        
        # 确保versions目录存在并添加.gitkeep文件，以便Git能够跟踪空目录
        versions_dir = Path('alembic/versions')
        versions_dir.mkdir(exist_ok=True)
        gitkeep_file = versions_dir / '.gitkeep'
        gitkeep_file.touch()
        console.print("[green]已创建versions目录并添加.gitkeep文件[/green]")
        
        # 获取数据库配置并更新alembic.ini
        sql_config = get_sql_config()
        db_url = create_db_url(sql_config)
        
        update_alembic_config(db_url)
        console.print("[green]已更新alembic.ini中的数据库URL[/green]")
        
        # 更新env.py文件以使用我们的模型
        update_env_py()
        console.print("[green]已更新env.py以使用项目模型[/green]")
        
        return True
    except Exception as e:
        console.print(f"[bold red]Alembic初始化失败: {str(e)}[/bold red]")
        import traceback
        console.print(traceback.format_exc())
        return False


def update_alembic_config(db_url):
    """更新alembic.ini配置文件"""
    alembic_ini_path = Path('alembic.ini')
    
    if not alembic_ini_path.exists():
        raise FileNotFoundError("未找到alembic.ini文件")
    
    # 读取配置文件内容
    content = alembic_ini_path.read_text(encoding='utf-8')
    
    # 更新sqlalchemy.url
    if 'sqlalchemy.url =' in content:
        content = content.replace(
            'sqlalchemy.url = driver://user:pass@localhost/dbname',
            f'sqlalchemy.url = {db_url}'
        )
    
    # 写回文件
    alembic_ini_path.write_text(content, encoding='utf-8')


def update_env_py():
    """更新alembic/env.py文件"""
    env_py_path = Path('alembic/env.py')
    
    if not env_py_path.exists():
        raise FileNotFoundError("未找到alembic/env.py文件")
    
    # 读取文件内容
    content = env_py_path.read_text(encoding='utf-8')
    
    # 添加导入语句
    import_section = """
from src.db import metadata
import src.db.models
"""
    
    # 替换target_metadata = None
    if 'target_metadata = None' in content:
        content = content.replace(
            'target_metadata = None',
            'target_metadata = metadata'
        )
    
    # 添加导入语句到文件顶部
    if 'from logging.config import fileConfig' in content:
        content = content.replace(
            'from logging.config import fileConfig',
            'from logging.config import fileConfig\n' + import_section
        )
    
    # 写回文件
    env_py_path.write_text(content, encoding='utf-8')


def generate_migration(message=None, autogenerate=True):
    """生成迁移脚本"""
    console = Console()
    
    if not ALEMBIC_AVAILABLE:
        console.print("[bold red]错误: 未安装alembic模块，请先运行 pip install alembic[/bold red]")
        return False
    
    if not os.path.exists('alembic'):
        console.print("[bold red]Alembic环境未初始化，请先运行 python init_alembic.py --init[/bold red]")
        return False
    
    # 确保versions目录存在
    versions_dir = Path('alembic/versions')
    if not versions_dir.exists():
        console.print("[yellow]创建缺失的versions目录...[/yellow]")
        versions_dir.mkdir(exist_ok=True)
        # 添加.gitkeep文件以便Git能够跟踪此目录
        (versions_dir / '.gitkeep').touch()
    
    try:
        console.print("[bold]正在生成迁移脚本...[/bold]")
        alembic_cfg = Config("alembic.ini")
        
        # 生成迁移脚本
        if autogenerate:
            command.revision(alembic_cfg, message=message or "自动生成迁移", autogenerate=True)
        else:
            command.revision(alembic_cfg, message=message or "空迁移脚本")
        
        console.print("[green]迁移脚本生成成功[/green]")
        return True
    except Exception as e:
        console.print(f"[bold red]生成迁移脚本失败: {str(e)}[/bold red]")
        return False


def upgrade_database(revision='head'):
    """升级数据库到指定版本"""
    console = Console()
    
    if not ALEMBIC_AVAILABLE:
        console.print("[bold red]错误: 未安装alembic模块，请先运行 pip install alembic[/bold red]")
        return False
    
    if not os.path.exists('alembic'):
        console.print("[bold red]Alembic环境未初始化，请先运行 python init_alembic.py --init[/bold red]")
        return False
    
    try:
        console.print(f"[bold]正在升级数据库到版本: {revision}...[/bold]")
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, revision)
        console.print("[green]数据库升级成功[/green]")
        return True
    except Exception as e:
        console.print(f"[bold red]数据库升级失败: {str(e)}[/bold red]")
        return False


def downgrade_database(revision='-1'):
    """降级数据库到指定版本"""
    console = Console()
    
    if not ALEMBIC_AVAILABLE:
        console.print("[bold red]错误: 未安装alembic模块，请先运行 pip install alembic[/bold red]")
        return False
    
    if not os.path.exists('alembic'):
        console.print("[bold red]Alembic环境未初始化，请先运行 python init_alembic.py --init[/bold red]")
        return False
    
    try:
        console.print(f"[bold]正在降级数据库到版本: {revision}...[/bold]")
        alembic_cfg = Config("alembic.ini")
        command.downgrade(alembic_cfg, revision)
        console.print("[green]数据库降级成功[/green]")
        return True
    except Exception as e:
        console.print(f"[bold red]数据库降级失败: {str(e)}[/bold red]")
        return False


def show_history(verbose=False):
    """显示迁移历史"""
    console = Console()
    
    if not ALEMBIC_AVAILABLE:
        console.print("[bold red]错误: 未安装alembic模块，请先运行 pip install alembic[/bold red]")
        return False
    
    if not os.path.exists('alembic'):
        console.print("[bold red]Alembic环境未初始化，请先运行 python init_alembic.py --init[/bold red]")
        return False
    
    try:
        console.print("[bold]迁移历史:[/bold]")
        alembic_cfg = Config("alembic.ini")
        
        # 因为history命令输出直接打印到控制台，我们无法捕获它
        # 但我们可以直接调用API
        command.history(alembic_cfg, verbose=verbose)
        return True
    except Exception as e:
        console.print(f"[bold red]获取迁移历史失败: {str(e)}[/bold red]")
        return False


def show_current():
    """显示当前版本"""
    console = Console()
    
    if not ALEMBIC_AVAILABLE:
        console.print("[bold red]错误: 未安装alembic模块，请先运行 pip install alembic[/bold red]")
        return False
    
    if not os.path.exists('alembic'):
        console.print("[bold red]Alembic环境未初始化，请先运行 python init_alembic.py --init[/bold red]")
        return False
    
    try:
        console.print("[bold]当前数据库版本:[/bold]")
        alembic_cfg = Config("alembic.ini")
        command.current(alembic_cfg, verbose=True)
        return True
    except Exception as e:
        console.print(f"[bold red]获取当前版本失败: {str(e)}[/bold red]")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Alembic数据库迁移工具")
    
    # 命令组 - 只能使用其中一个
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--init', action='store_true', help='初始化Alembic环境')
    group.add_argument('--generate', action='store_true', help='生成新的迁移脚本')
    group.add_argument('--upgrade', action='store_true', help='升级数据库')
    group.add_argument('--downgrade', action='store_true', help='降级数据库')
    group.add_argument('--history', action='store_true', help='显示迁移历史')
    group.add_argument('--current', action='store_true', help='显示当前版本')
    
    # 其他选项
    parser.add_argument('--force', action='store_true', help='强制初始化，覆盖现有Alembic目录')
    parser.add_argument('-m', '--message', help='迁移脚本的描述信息')
    parser.add_argument('--no-autogenerate', action='store_true', help='不自动生成迁移内容')
    parser.add_argument('--revision', default='head', help='指定升级/降级的版本，默认为head')
    parser.add_argument('-v', '--verbose', action='store_true', help='显示详细信息')
    
    args = parser.parse_args()
    
    console = Console()
    console.print(Panel.fit("[bold yellow]Alembic数据库迁移工具[/bold yellow]", border_style="green"))
    
    # 检查Alembic是否已安装
    if not ALEMBIC_AVAILABLE:
        console.print("[bold red]错误: 未安装alembic模块，请先运行 pip install alembic[/bold red]")
        return 1
    
    try:
        if args.init:
            init_alembic(args.force)
            
        elif args.generate:
            generate_migration(args.message, not args.no_autogenerate)
            
        elif args.upgrade:
            upgrade_database(args.revision)
            
        elif args.downgrade:
            downgrade_database(args.revision)
            
        elif args.history:
            show_history(args.verbose)
            
        elif args.current:
            show_current()
        
    except Exception as e:
        console.print(f"[bold red]错误: {str(e)}[/bold red]")
        import traceback
        console.print(traceback.format_exc())
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main()) 