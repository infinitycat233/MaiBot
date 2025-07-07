import asyncio
import hashlib
import os
from dotenv import load_dotenv

if os.path.exists(".env"):
    load_dotenv(".env", override=True)
    print("成功加载环境变量配置")
else:
    print("未找到.env文件，请确保程序所需的环境变量被正确设置")
import sys
import time
import platform
import traceback
from pathlib import Path
from rich.traceback import install

# maim_message imports for console input
from maim_message import Seg, UserInfo, BaseMessageInfo, MessageBase
from src.chat.message_receive.bot import chat_bot

# 最早期初始化日志系统，确保所有后续模块都使用正确的日志格式
from src.common.logger import initialize_logging, get_logger, shutdown_logging
from src.main import MainSystem
from src.manager.async_task_manager import async_task_manager

initialize_logging()

logger = get_logger("main")


install(extra_lines=3)

# 设置工作目录为脚本所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
logger.info(f"已设置工作目录为: {script_dir}")


confirm_logger = get_logger("confirm")
# 获取没有加载env时的环境变量
env_mask = {key: os.getenv(key) for key in os.environ}

uvicorn_server = None
driver = None
app = None
loop = None


async def request_shutdown() -> bool:
    """请求关闭程序"""
    try:
        if loop and not loop.is_closed():
            try:
                loop.run_until_complete(graceful_shutdown())
            except Exception as ge:  # 捕捉优雅关闭时可能发生的错误
                logger.error(f"优雅关闭时发生错误: {ge}")
                return False
        return True
    except Exception as e:
        logger.error(f"请求关闭程序时发生错误: {e}")
        return False


def easter_egg():
    # 彩蛋
    from colorama import init, Fore

    init()
    text = "多年以后，面对AI行刑队，张三将会回想起他2023年在会议上讨论人工智能的那个下午"
    rainbow_colors = [Fore.RED, Fore.YELLOW, Fore.GREEN, Fore.CYAN, Fore.BLUE, Fore.MAGENTA]
    rainbow_text = ""
    for i, char in enumerate(text):
        rainbow_text += rainbow_colors[i % len(rainbow_colors)] + char
    print(rainbow_text)


def scan_provider(env_config: dict):
    provider = {}

    # 利用未初始化 env 时获取的 env_mask 来对新的环境变量集去重
    # 避免 GPG_KEY 这样的变量干扰检查
    env_config = dict(filter(lambda item: item[0] not in env_mask, env_config.items()))

    # 遍历 env_config 的所有键
    for key in env_config:
        # 检查键是否符合 {provider}_BASE_URL 或 {provider}_KEY 的格式
        if key.endswith("_BASE_URL") or key.endswith("_KEY"):
            # 提取 provider 名称
            provider_name = key.split("_", 1)[0]  # 从左分割一次，取第一部分

            # 初始化 provider 的字典（如果尚未初始化）
            if provider_name not in provider:
                provider[provider_name] = {"url": None, "key": None}

            # 根据键的类型填充 url 或 key
            if key.endswith("_BASE_URL"):
                provider[provider_name]["url"] = env_config[key]
            elif key.endswith("_KEY"):
                provider[provider_name]["key"] = env_config[key]

    # 检查每个 provider 是否同时存在 url 和 key
    for provider_name, config in provider.items():
        if config["url"] is None or config["key"] is None:
            logger.error(f"provider 内容：{config}\nenv_config 内容：{env_config}")
            raise ValueError(f"请检查 '{provider_name}' 提供商配置是否丢失 BASE_URL 或 KEY 环境变量")


async def graceful_shutdown():
    try:
        logger.info("正在优雅关闭麦麦...")

        # 停止所有异步任务
        await async_task_manager.stop_and_wait_all_tasks()

        # 获取所有剩余任务，排除当前任务
        remaining_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

        if remaining_tasks:
            logger.info(f"正在取消 {len(remaining_tasks)} 个剩余任务...")

            # 取消所有剩余任务
            for task in remaining_tasks:
                if not task.done():
                    task.cancel()

            # 等待所有任务完成，设置超时
            try:
                await asyncio.wait_for(asyncio.gather(*remaining_tasks, return_exceptions=True), timeout=15.0)
                logger.info("所有剩余任务已成功取消")
            except asyncio.TimeoutError:
                logger.warning("等待任务取消超时，强制继续关闭")
            except Exception as e:
                logger.error(f"等待任务取消时发生异常: {e}")

        logger.info("麦麦优雅关闭完成")

        # 关闭日志系统，释放文件句柄
        shutdown_logging()

    except Exception as e:
        logger.error(f"麦麦关闭失败: {e}", exc_info=True)


def check_eula():
    eula_confirm_file = Path("eula.confirmed")
    privacy_confirm_file = Path("privacy.confirmed")
    eula_file = Path("EULA.md")
    privacy_file = Path("PRIVACY.md")

    eula_updated = True
    privacy_updated = True

    eula_confirmed = False
    privacy_confirmed = False

    # 首先计算当前EULA文件的哈希值
    if eula_file.exists():
        with open(eula_file, "r", encoding="utf-8") as f:
            eula_content = f.read()
        eula_new_hash = hashlib.md5(eula_content.encode("utf-8")).hexdigest()
    else:
        logger.error("EULA.md 文件不存在")
        raise FileNotFoundError("EULA.md 文件不存在")

    # 首先计算当前隐私条款文件的哈希值
    if privacy_file.exists():
        with open(privacy_file, "r", encoding="utf-8") as f:
            privacy_content = f.read()
        privacy_new_hash = hashlib.md5(privacy_content.encode("utf-8")).hexdigest()
    else:
        logger.error("PRIVACY.md 文件不存在")
        raise FileNotFoundError("PRIVACY.md 文件不存在")

    # 检查EULA确认文件是否存在
    if eula_confirm_file.exists():
        with open(eula_confirm_file, "r", encoding="utf-8") as f:
            confirmed_content = f.read()
        if eula_new_hash == confirmed_content:
            eula_confirmed = True
            eula_updated = False
    if eula_new_hash == os.getenv("EULA_AGREE"):
        eula_confirmed = True
        eula_updated = False

    # 检查隐私条款确认文件是否存在
    if privacy_confirm_file.exists():
        with open(privacy_confirm_file, "r", encoding="utf-8") as f:
            confirmed_content = f.read()
        if privacy_new_hash == confirmed_content:
            privacy_confirmed = True
            privacy_updated = False
    if privacy_new_hash == os.getenv("PRIVACY_AGREE"):
        privacy_confirmed = True
        privacy_updated = False

    # 如果EULA或隐私条款有更新，提示用户重新确认
    if eula_updated or privacy_updated:
        confirm_logger.critical("EULA或隐私条款内容已更新，请在阅读后重新确认，继续运行视为同意更新后的以上两款协议")
        confirm_logger.critical(
            f'输入"同意"或"confirmed"或设置环境变量"EULA_AGREE={eula_new_hash}"和"PRIVACY_AGREE={privacy_new_hash}"继续运行'
        )
        while True:
            user_input = input().strip().lower()
            if user_input in ["同意", "confirmed"]:
                # print("确认成功，继续运行")
                # print(f"确认成功，继续运行{eula_updated} {privacy_updated}")
                if eula_updated:
                    logger.info(f"更新EULA确认文件{eula_new_hash}")
                    eula_confirm_file.write_text(eula_new_hash, encoding="utf-8")
                if privacy_updated:
                    logger.info(f"更新隐私条款确认文件{privacy_new_hash}")
                    privacy_confirm_file.write_text(privacy_new_hash, encoding="utf-8")
                break
            else:
                confirm_logger.critical('请输入"同意"或"confirmed"以继续运行')
        return
    elif eula_confirmed and privacy_confirmed:
        return


def raw_main():
    # 利用 TZ 环境变量设定程序工作的时区
    if platform.system().lower() != "windows":
        time.tzset()

    check_eula()
    logger.info("检查EULA和隐私条款完成")

    easter_egg()

    env_config = {key: os.getenv(key) for key in os.environ}
    scan_provider(env_config)

    # 返回MainSystem实例
    return MainSystem()


async def _create_console_message_dict(text: str) -> dict:
    """使用配置创建消息字典"""
    timestamp = time.time()

    # --- User & Group Info (hardcoded for console) ---
    user_info = UserInfo(
        platform="console",
        user_id="console_user",
        user_nickname="ConsoleUser",
        user_cardname="",
    )
    # Console input is private chat
    group_info = None

    # --- Base Message Info ---
    message_info = BaseMessageInfo(
        platform="console",
        message_id=f"console_{int(timestamp * 1000)}_{hash(text) % 10000}",
        time=timestamp,
        user_info=user_info,
        group_info=group_info,
        # Other infos can be added here if needed, e.g., FormatInfo
    )

    # --- Message Segment ---
    message_segment = Seg(type="text", data=text)

    # --- Final MessageBase object to convert to dict ---
    message = MessageBase(message_info=message_info, message_segment=message_segment, raw_message=text)

    return message.to_dict()


async def console_input_loop(main_system: MainSystem):
    """异步循环以读取控制台输入并模拟接收消息"""
    logger.info("控制台输入已准备就绪 (模拟接收消息)。输入 'exit()' 来停止。")
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            text = line.strip()

            if not text:
                continue
            if text.lower() == "exit()":
                logger.info("收到 'exit()' 命令，正在停止...")
                break

            # Create message dict and pass to the processor
            message_dict = await _create_console_message_dict(text)
            await chat_bot.message_process(message_dict)
            logger.info(f"已将控制台消息 '{text}' 作为接收消息处理。")

        except asyncio.CancelledError:
            logger.info("控制台输入循环被取消。")
            break
        except Exception as e:
            logger.error(f"控制台输入循环出错: {e}", exc_info=True)
            await asyncio.sleep(1)
    logger.info("控制台输入循环结束。")


if __name__ == "__main__":
    exit_code = 0  # 用于记录程序最终的退出状态
    try:
        # 获取MainSystem实例
        main_system = raw_main()

        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # 执行初始化和任务调度
            loop.run_until_complete(main_system.initialize())
            # Schedule tasks returns a future that runs forever.
            # We can run console_input_loop concurrently.
            main_tasks = loop.create_task(main_system.schedule_tasks())

            # 仅在 TTY 中启用 console_input_loop
            if sys.stdin.isatty():
                logger.info("检测到终端环境，启用控制台输入循环")
                console_task = loop.create_task(console_input_loop(main_system))
                # Wait for all tasks to complete (which they won't, normally)
                loop.run_until_complete(asyncio.gather(main_tasks, console_task))
            else:
                logger.info("非终端环境，跳过控制台输入循环")
                # Wait for all tasks to complete (which they won't, normally)
                loop.run_until_complete(main_tasks)

        except KeyboardInterrupt:
            # loop.run_until_complete(get_global_api().stop())
            logger.warning("收到中断信号，正在优雅关闭...")
            if loop and not loop.is_closed():
                try:
                    loop.run_until_complete(graceful_shutdown())
                except Exception as ge:  # 捕捉优雅关闭时可能发生的错误
                    logger.error(f"优雅关闭时发生错误: {ge}")
        # 新增：检测外部请求关闭

        # except Exception as e: # 将主异常捕获移到外层 try...except
        #     logger.error(f"事件循环内发生错误: {str(e)} {str(traceback.format_exc())}")
        #     exit_code = 1
        # finally: # finally 块移到最外层，确保 loop 关闭和暂停总是执行
        #     if loop and not loop.is_closed():
        #         loop.close()
        #     # 在这里添加 input() 来暂停
        #     input("按 Enter 键退出...") # <--- 添加这行
        #     sys.exit(exit_code) # <--- 使用记录的退出码

    except Exception as e:
        logger.error(f"主程序发生异常: {str(e)} {str(traceback.format_exc())}")
        exit_code = 1  # 标记发生错误
    finally:
        # 确保 loop 在任何情况下都尝试关闭（如果存在且未关闭）
        if "loop" in locals() and loop and not loop.is_closed():
            loop.close()
            logger.info("事件循环已关闭")

        # 关闭日志系统，释放文件句柄
        try:
            shutdown_logging()
        except Exception as e:
            print(f"关闭日志系统时出错: {e}")

        # 在程序退出前暂停，让你有机会看到输出
        # input("按 Enter 键退出...")  # <--- 添加这行
        sys.exit(exit_code)  # <--- 使用记录的退出码
