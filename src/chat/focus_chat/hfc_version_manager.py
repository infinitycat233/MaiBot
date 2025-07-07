"""
HFC性能记录版本号管理器

用于管理HFC性能记录的内部版本号，支持：
1. 默认版本号设置
2. 启动时版本号配置
3. 版本号验证和格式化
"""

import os
import re
from datetime import datetime
from typing import Optional
from src.common.logger import get_logger

logger = get_logger("hfc_version")


class HFCVersionManager:
    """HFC版本号管理器"""

    # 默认版本号
    DEFAULT_VERSION = "v5.0.0"

    # 当前运行时版本号
    _current_version: Optional[str] = None

    @classmethod
    def set_version(cls, version: str) -> bool:
        """
        设置当前运行时版本号

        参数:
            version: 版本号字符串，格式如 v1.0.0 或 1.0.0

        返回:
            bool: 设置是否成功
        """
        try:
            validated_version = cls._validate_version(version)
            if validated_version:
                cls._current_version = validated_version
                logger.info(f"HFC性能记录版本已设置为: {validated_version}")
                return True
            else:
                logger.warning(f"无效的版本号格式: {version}")
                return False
        except Exception as e:
            logger.error(f"设置版本号失败: {e}")
            return False

    @classmethod
    def get_version(cls) -> str:
        """
        获取当前版本号

        返回:
            str: 当前版本号
        """
        if cls._current_version:
            return cls._current_version

        # 尝试从环境变量获取
        env_version = os.getenv("HFC_PERFORMANCE_VERSION")
        if env_version:
            if cls.set_version(env_version):
                return cls._current_version

        # 返回默认版本号
        return cls.DEFAULT_VERSION

    @classmethod
    def auto_generate_version(cls, base_version: str = None) -> str:
        """
        自动生成版本号（基于时间戳）

        参数:
            base_version: 基础版本号，如果不提供则使用默认版本

        返回:
            str: 生成的版本号
        """
        if not base_version:
            base_version = cls.DEFAULT_VERSION

        # 提取基础版本号的主要部分
        base_match = re.match(r"v?(\d+\.\d+)", base_version)
        if base_match:
            base_part = base_match.group(1)
        else:
            base_part = "1.0"

        # 添加时间戳
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        generated_version = f"v{base_part}.{timestamp}"

        cls.set_version(generated_version)
        logger.info(f"自动生成版本号: {generated_version}")

        return generated_version

    @classmethod
    def _validate_version(cls, version: str) -> Optional[str]:
        """
        验证版本号格式

        参数:
            version: 待验证的版本号

        返回:
            Optional[str]: 验证后的版本号，失败返回None
        """
        if not version or not isinstance(version, str):
            return None

        version = version.strip()

        # 支持的格式：
        # v1.0.0, 1.0.0, v1.0, 1.0, v1.0.0.20241222_1530 等
        patterns = [
            r"^v?(\d+\.\d+\.\d+)$",  # v1.0.0 或 1.0.0
            r"^v?(\d+\.\d+)$",  # v1.0 或 1.0
            r"^v?(\d+\.\d+\.\d+\.\w+)$",  # v1.0.0.build 或 1.0.0.build
            r"^v?(\d+\.\d+\.\w+)$",  # v1.0.build 或 1.0.build
        ]

        for pattern in patterns:
            match = re.match(pattern, version)
            if match:
                # 确保版本号以v开头
                if not version.startswith("v"):
                    version = "v" + version
                return version

        return None

    @classmethod
    def reset_version(cls):
        """重置版本号为默认值"""
        cls._current_version = None
        logger.info("HFC版本号已重置为默认值")

    @classmethod
    def get_version_info(cls) -> dict:
        """
        获取版本信息

        返回:
            dict: 版本相关信息
        """
        current = cls.get_version()
        return {
            "current_version": current,
            "default_version": cls.DEFAULT_VERSION,
            "is_custom": current != cls.DEFAULT_VERSION,
            "env_version": os.getenv("HFC_PERFORMANCE_VERSION"),
            "timestamp": datetime.now().isoformat(),
        }


# 全局函数，方便使用
def set_hfc_version(version: str) -> bool:
    """设置HFC性能记录版本号"""
    return HFCVersionManager.set_version(version)


def get_hfc_version() -> str:
    """获取当前HFC性能记录版本号"""
    return HFCVersionManager.get_version()


def auto_generate_hfc_version(base_version: str = None) -> str:
    """自动生成HFC版本号"""
    return HFCVersionManager.auto_generate_version(base_version)


def reset_hfc_version():
    """重置HFC版本号"""
    HFCVersionManager.reset_version()


# 在模块加载时显示当前版本信息
if __name__ != "__main__":
    current_version = HFCVersionManager.get_version()
    logger.debug(f"HFC性能记录模块已加载，当前版本: {current_version}")
