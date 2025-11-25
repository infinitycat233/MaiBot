import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
from pathlib import Path
import threading
import toml
from datetime import datetime
from collections import defaultdict
import os
import time


class LogIndex:
    """日志索引，用于快速检索和过滤"""

    def __init__(self):
        self.entries = []  # 所有日志条目
        self.module_index = defaultdict(list)  # 按模块索引
        self.level_index = defaultdict(list)  # 按级别索引
        self.filtered_indices = []  # 当前过滤结果的索引
        self.total_entries = 0

    def add_entry(self, index, entry):
        """添加日志条目到索引"""
        if index >= len(self.entries):
            self.entries.extend([None] * (index - len(self.entries) + 1))

        self.entries[index] = entry
        self.total_entries = max(self.total_entries, index + 1)

        # 更新各种索引
        logger_name = entry.get("logger_name", "")
        level = entry.get("level", "")

        self.module_index[logger_name].append(index)
        self.level_index[level].append(index)

    def filter_entries(self, modules=None, level=None, search_text=None):
        """根据条件过滤日志条目"""
        if not modules and not level and not search_text:
            self.filtered_indices = list(range(self.total_entries))
            return self.filtered_indices

        candidate_indices = set(range(self.total_entries))

        # 模块过滤
        if modules and "全部" not in modules:
            module_indices = set()
            for module in modules:
                module_indices.update(self.module_index.get(module, []))
            candidate_indices &= module_indices

        # 级别过滤
        if level and level != "全部":
            level_indices = set(self.level_index.get(level, []))
            candidate_indices &= level_indices

        # 文本搜索过滤
        if search_text:
            search_text = search_text.lower()
            text_indices = set()
            for i in candidate_indices:
                if i < len(self.entries) and self.entries[i]:
                    entry = self.entries[i]
                    text_content = f"{entry.get('logger_name', '')} {entry.get('event', '')}".lower()
                    if search_text in text_content:
                        text_indices.add(i)
            candidate_indices &= text_indices

        self.filtered_indices = sorted(list(candidate_indices))
        return self.filtered_indices

    def get_filtered_count(self):
        """获取过滤后的条目数量"""
        return len(self.filtered_indices)

    def get_entry_at_filtered_position(self, position):
        """获取过滤结果中指定位置的条目"""
        if 0 <= position < len(self.filtered_indices):
            index = self.filtered_indices[position]
            return self.entries[index] if index < len(self.entries) else None
        return None


class LogFormatter:
    """日志格式化器"""

    def __init__(self, config, custom_module_colors=None, custom_level_colors=None):
        self.config = config

        # 日志级别颜色
        self.level_colors = {
            "debug": "#FFA500",
            "info": "#0000FF",
            "success": "#008000",
            "warning": "#FFFF00",
            "error": "#FF0000",
            "critical": "#800080",
        }

        # 模块颜色映射
        self.module_colors = {
            "api": "#00FF00",
            "emoji": "#00FF00",
            "chat": "#0080FF",
            "config": "#FFFF00",
            "common": "#FF00FF",
            "tools": "#00FFFF",
            "lpmm": "#00FFFF",
            "plugin_system": "#FF0080",
            "experimental": "#FFFFFF",
            "person_info": "#008000",
            "individuality": "#000080",
            "manager": "#800080",
            "llm_models": "#008080",
            "plugins": "#800000",
            "plugin_api": "#808000",
            "remote": "#8000FF",
        }

        # 应用自定义颜色
        if custom_module_colors:
            self.module_colors.update(custom_module_colors)
        if custom_level_colors:
            self.level_colors.update(custom_level_colors)

        # 根据配置决定颜色启用状态
        color_text = self.config.get("color_text", "full")
        if color_text == "none":
            self.enable_colors = False
            self.enable_module_colors = False
            self.enable_level_colors = False
        elif color_text == "title":
            self.enable_colors = True
            self.enable_module_colors = True
            self.enable_level_colors = False
        elif color_text == "full":
            self.enable_colors = True
            self.enable_module_colors = True
            self.enable_level_colors = True
        else:
            self.enable_colors = True
            self.enable_module_colors = True
            self.enable_level_colors = False

    def format_log_entry(self, log_entry):
        """格式化日志条目，返回格式化后的文本和样式标签"""
        timestamp = log_entry.get("timestamp", "")
        level = log_entry.get("level", "info")
        logger_name = log_entry.get("logger_name", "")
        event = log_entry.get("event", "")

        # 格式化时间戳
        formatted_timestamp = self.format_timestamp(timestamp)

        # 构建输出部分
        parts = []
        tags = []

        # 日志级别样式配置
        log_level_style = self.config.get("log_level_style", "lite")

        # 时间戳
        if formatted_timestamp:
            if log_level_style == "lite" and self.enable_level_colors:
                parts.append(formatted_timestamp)
                tags.append(f"level_{level}")
            else:
                parts.append(formatted_timestamp)
                tags.append("timestamp")

        # 日志级别显示
        if log_level_style == "full":
            level_text = f"[{level.upper():>8}]"
            parts.append(level_text)
            if self.enable_level_colors:
                tags.append(f"level_{level}")
            else:
                tags.append("level")
        elif log_level_style == "compact":
            level_text = f"[{level.upper()[0]:>8}]"
            parts.append(level_text)
            if self.enable_level_colors:
                tags.append(f"level_{level}")
            else:
                tags.append("level")

        # 模块名称
        if logger_name:
            module_text = f"[{logger_name}]"
            parts.append(module_text)
            if self.enable_module_colors:
                tags.append(f"module_{logger_name}")
            else:
                tags.append("module")

        # 消息内容
        if isinstance(event, str):
            parts.append(event)
        elif isinstance(event, dict):
            try:
                parts.append(json.dumps(event, ensure_ascii=False, indent=None))
            except (TypeError, ValueError):
                parts.append(str(event))
        else:
            parts.append(str(event))
        tags.append("message")

        return parts, tags

    def format_timestamp(self, timestamp):
        """格式化时间戳"""
        if not timestamp:
            return ""

        try:
            if "T" in timestamp:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                return timestamp

            date_style = self.config.get("date_style", "m-d H:i:s")
            format_map = {
                "Y": "%Y",
                "m": "%m",
                "d": "%d",
                "H": "%H",
                "i": "%M",
                "s": "%S",
            }

            python_format = date_style
            for php_char, python_char in format_map.items():
                python_format = python_format.replace(php_char, python_char)

            return dt.strftime(python_format)
        except Exception:
            return timestamp


class VirtualLogDisplay:
    """虚拟滚动日志显示组件"""

    def __init__(self, parent, formatter):
        self.parent = parent
        self.formatter = formatter
        self.line_height = 20  # 每行高度（像素）
        self.visible_lines = 30  # 可见行数

        # 创建主框架
        self.main_frame = ttk.Frame(parent)

        # 创建文本框和滚动条
        self.scrollbar = ttk.Scrollbar(self.main_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text_widget = tk.Text(
            self.main_frame,
            wrap=tk.WORD,
            yscrollcommand=self.scrollbar.set,
            background="#1e1e1e",
            foreground="#ffffff",
            insertbackground="#ffffff",
            selectbackground="#404040",
            font=("Consolas", 10),
        )
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.text_widget.yview)

        # 配置文本标签样式
        self.configure_text_tags()

        # 数据源
        self.log_index = None
        self.current_page = 0
        self.page_size = 500  # 每页显示条数
        self.max_display_lines = 2000  # 最大显示行数

    def pack(self, **kwargs):
        """包装pack方法"""
        self.main_frame.pack(**kwargs)

    def configure_text_tags(self):
        """配置文本标签样式"""
        # 基础标签
        self.text_widget.tag_configure("timestamp", foreground="#808080")
        self.text_widget.tag_configure("level", foreground="#808080")
        self.text_widget.tag_configure("module", foreground="#808080")
        self.text_widget.tag_configure("message", foreground="#ffffff")

        # 日志级别颜色标签
        for level, color in self.formatter.level_colors.items():
            self.text_widget.tag_configure(f"level_{level}", foreground=color)

        # 模块颜色标签
        for module, color in self.formatter.module_colors.items():
            self.text_widget.tag_configure(f"module_{module}", foreground=color)

    def set_log_index(self, log_index):
        """设置日志索引数据源"""
        self.log_index = log_index
        self.current_page = 0
        self.refresh_display()

    def refresh_display(self):
        """刷新显示"""
        if not self.log_index:
            self.text_widget.delete(1.0, tk.END)
            return

        # 清空显示
        self.text_widget.delete(1.0, tk.END)

        # 批量加载和显示日志
        total_count = self.log_index.get_filtered_count()
        if total_count == 0:
            self.text_widget.insert(tk.END, "没有符合条件的日志记录\n")
            return

        # 计算显示范围
        start_index = 0
        end_index = min(total_count, self.max_display_lines)

        # 批量处理和显示
        batch_size = 100
        for batch_start in range(start_index, end_index, batch_size):
            batch_end = min(batch_start + batch_size, end_index)
            self.display_batch(batch_start, batch_end)

            # 让UI有机会响应
            self.parent.update_idletasks()

        # 滚动到底部（如果需要）
        self.text_widget.see(tk.END)

    def display_batch(self, start_index, end_index):
        """批量显示日志条目"""
        for i in range(start_index, end_index):
            log_entry = self.log_index.get_entry_at_filtered_position(i)
            if log_entry:
                self.append_entry(log_entry, scroll=False)

    def append_entry(self, log_entry, scroll=True):
        """将单个日志条目附加到文本小部件"""
        # 检查在添加新内容之前视图是否已滚动到底部
        should_scroll = scroll and self.text_widget.yview()[1] > 0.99

        parts, tags = self.formatter.format_log_entry(log_entry)
        line_text = " ".join(parts) + "\n"

        # 获取插入前的末尾位置
        start_pos = self.text_widget.index(tk.END + "-1c")
        self.text_widget.insert(tk.END, line_text)

        # 为每个部分应用正确的标签
        current_len = 0
        for part, tag_name in zip(parts, tags, strict=False):
            start_index = f"{start_pos}+{current_len}c"
            end_index = f"{start_pos}+{current_len + len(part)}c"
            self.text_widget.tag_add(tag_name, start_index, end_index)
            current_len += len(part) + 1  # 计入空格

        if should_scroll:
            self.text_widget.see(tk.END)


class AsyncLogLoader:
    """异步日志加载器"""

    def __init__(self, callback):
        self.callback = callback
        self.loading = False
        self.should_stop = False

    def load_file_async(self, file_path, progress_callback=None):
        """异步加载日志文件"""
        if self.loading:
            return

        self.loading = True
        self.should_stop = False

        def load_worker():
            try:
                log_index = LogIndex()

                if not os.path.exists(file_path):
                    self.callback(log_index, "文件不存在")
                    return

                file_size = os.path.getsize(file_path)
                processed_size = 0

                with open(file_path, "r", encoding="utf-8") as f:
                    line_count = 0
                    batch_size = 1000  # 批量处理

                    while not self.should_stop:
                        lines = []
                        for _ in range(batch_size):
                            line = f.readline()
                            if not line:
                                break
                            lines.append(line)
                            processed_size += len(line.encode("utf-8"))

                        if not lines:
                            break

                        # 处理这批数据
                        for line in lines:
                            try:
                                log_entry = json.loads(line.strip())
                                log_index.add_entry(line_count, log_entry)
                                line_count += 1
                            except json.JSONDecodeError:
                                continue

                        # 更新进度
                        if progress_callback:
                            progress = min(100, (processed_size / file_size) * 100)
                            progress_callback(progress, line_count)

                if not self.should_stop:
                    self.callback(log_index, None)

            except Exception as e:
                self.callback(None, str(e))
            finally:
                self.loading = False

        thread = threading.Thread(target=load_worker)
        thread.daemon = True
        thread.start()

    def stop_loading(self):
        """停止加载"""
        self.should_stop = True
        self.loading = False


class LogViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("MaiBot日志查看器 (优化版)")
        self.root.geometry("1200x800")

        # 加载配置
        self.load_config()

        # 初始化日志格式化器
        self.formatter = LogFormatter(self.log_config, {}, {})

        # 初始化日志文件路径
        self.current_log_file = Path("logs/app.log.jsonl")
        self.last_file_size = 0
        self.watching_thread = None
        self.is_watching = tk.BooleanVar(value=True)

        # 初始化异步加载器
        self.async_loader = AsyncLogLoader(self.on_file_loaded)

        # 初始化日志索引
        self.log_index = LogIndex()

        # 创建主框架
        self.main_frame = ttk.Frame(root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 创建控制面板
        self.create_control_panel()

        # 创建虚拟滚动日志显示区域
        self.log_display = VirtualLogDisplay(self.main_frame, self.formatter)
        self.log_display.pack(fill=tk.BOTH, expand=True)

        # 模块名映射
        self.module_name_mapping = {
            "api": "API接口",
            "config": "配置",
            "chat": "聊天",
            "plugin": "插件",
            "main": "主程序",
        }

        # 选中的模块集合
        self.selected_modules = set()
        self.modules = set()

        # 绑定事件
        self.level_combo.bind("<<ComboboxSelected>>", self.filter_logs)
        self.search_var.trace("w", self.filter_logs)

        # 初始加载文件
        if self.current_log_file.exists():
            self.load_log_file_async()

    def load_config(self):
        """加载配置文件"""
        self.default_config = {
            "log": {"date_style": "m-d H:i:s", "log_level_style": "lite", "color_text": "full"},
        }

        self.log_config = self.default_config["log"].copy()

        config_path = Path("config/bot_config.toml")
        try:
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    bot_config = toml.load(f)
                    if "log" in bot_config:
                        self.log_config.update(bot_config["log"])
        except Exception as e:
            print(f"加载配置失败: {e}")

    def create_control_panel(self):
        """创建控制面板"""
        # 控制面板
        self.control_frame = ttk.Frame(self.main_frame)
        self.control_frame.pack(fill=tk.X, pady=(0, 5))

        # 文件选择框架
        self.file_frame = ttk.LabelFrame(self.control_frame, text="日志文件")
        self.file_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(0, 5))

        # 当前文件显示
        self.current_file_var = tk.StringVar(value=str(self.current_log_file))
        self.file_label = ttk.Label(self.file_frame, textvariable=self.current_file_var, foreground="blue")
        self.file_label.pack(side=tk.LEFT, padx=5, pady=2)

        # 进度条
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.file_frame, variable=self.progress_var, length=200)
        self.progress_bar.pack(side=tk.LEFT, padx=5, pady=2)
        self.progress_bar.pack_forget()

        # 状态标签
        self.status_var = tk.StringVar(value="就绪")
        self.status_label = ttk.Label(self.file_frame, textvariable=self.status_var)
        self.status_label.pack(side=tk.LEFT, padx=5, pady=2)

        # 按钮区域
        button_frame = ttk.Frame(self.file_frame)
        button_frame.pack(side=tk.RIGHT, padx=5, pady=2)

        ttk.Button(button_frame, text="选择文件", command=self.select_log_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="刷新", command=self.refresh_log_file).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(button_frame, text="实时更新", variable=self.is_watching, command=self.toggle_watching).pack(
            side=tk.LEFT, padx=2
        )

        # 过滤控制框架
        filter_frame = ttk.Frame(self.control_frame)
        filter_frame.pack(fill=tk.X, padx=5)

        # 日志级别选择
        ttk.Label(filter_frame, text="级别:").pack(side=tk.LEFT, padx=2)
        self.level_var = tk.StringVar(value="全部")
        self.level_combo = ttk.Combobox(filter_frame, textvariable=self.level_var, width=8)
        self.level_combo["values"] = ["全部", "debug", "info", "warning", "error", "critical"]
        self.level_combo.pack(side=tk.LEFT, padx=2)

        # 搜索框
        ttk.Label(filter_frame, text="搜索:").pack(side=tk.LEFT, padx=(20, 2))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filter_frame, textvariable=self.search_var, width=20)
        self.search_entry.pack(side=tk.LEFT, padx=2)

        # 模块选择
        ttk.Label(filter_frame, text="模块:").pack(side=tk.LEFT, padx=(20, 2))
        self.module_var = tk.StringVar(value="全部")
        self.module_combo = ttk.Combobox(filter_frame, textvariable=self.module_var, width=15)
        self.module_combo.pack(side=tk.LEFT, padx=2)
        self.module_combo.bind("<<ComboboxSelected>>", self.on_module_selected)

    def on_file_loaded(self, log_index, error):
        """文件加载完成回调"""
        self.progress_bar.pack_forget()

        if error:
            self.status_var.set(f"加载失败: {error}")
            messagebox.showerror("错误", f"加载日志文件失败: {error}")
            return

        self.log_index = log_index
        try:
            self.last_file_size = os.path.getsize(self.current_log_file)
        except OSError:
            self.last_file_size = 0
        self.status_var.set(f"已加载 {log_index.total_entries} 条日志")

        # 更新模块列表
        self.update_module_list()

        # 应用过滤并显示
        self.filter_logs()

        # 如果开启了实时更新，则开始监视
        if self.is_watching.get():
            self.start_watching()

    def on_loading_progress(self, progress, line_count):
        """加载进度回调"""
        self.root.after(0, lambda: self.update_progress(progress, line_count))

    def update_progress(self, progress, line_count):
        """更新进度显示"""
        self.progress_var.set(progress)
        self.status_var.set(f"正在加载... {line_count} 条 ({progress:.1f}%)")

    def load_log_file_async(self):
        """异步加载日志文件"""
        self.stop_watching()  # 停止任何正在运行的监视器

        if not self.current_log_file.exists():
            self.status_var.set("文件不存在")
            return

        # 显示进度条
        self.progress_bar.pack(side=tk.LEFT, padx=5, pady=2, before=self.status_label)
        self.progress_var.set(0)
        self.status_var.set("正在加载...")

        # 清空当前数据
        self.log_index = LogIndex()
        self.modules.clear()
        self.selected_modules.clear()
        self.module_var.set("全部")

        # 开始异步加载
        self.async_loader.load_file_async(str(self.current_log_file), self.on_loading_progress)

    def on_module_selected(self, event=None):
        """模块选择事件"""
        module = self.module_var.get()
        if module == "全部":
            self.selected_modules = {"全部"}
        else:
            self.selected_modules = {module}
        self.filter_logs()

    def filter_logs(self, *args):
        """过滤日志"""
        if not self.log_index:
            return

        # 获取过滤条件
        selected_modules = self.selected_modules if self.selected_modules else None
        level = self.level_var.get() if self.level_var.get() != "全部" else None
        search_text = self.search_var.get().strip() if self.search_var.get().strip() else None

        # 应用过滤
        self.log_index.filter_entries(selected_modules, level, search_text)

        # 更新显示
        self.log_display.set_log_index(self.log_index)

        # 更新状态
        filtered_count = self.log_index.get_filtered_count()
        total_count = self.log_index.total_entries
        if filtered_count == total_count:
            self.status_var.set(f"显示 {total_count} 条日志")
        else:
            self.status_var.set(f"显示 {filtered_count}/{total_count} 条日志")

    def select_log_file(self):
        """选择日志文件"""
        filename = filedialog.askopenfilename(
            title="选择日志文件",
            filetypes=[("JSONL日志文件", "*.jsonl"), ("所有文件", "*.*")],
            initialdir="logs" if Path("logs").exists() else ".",
        )
        if filename:
            new_file = Path(filename)
            if new_file != self.current_log_file:
                self.current_log_file = new_file
                self.current_file_var.set(str(self.current_log_file))
                self.load_log_file_async()

    def refresh_log_file(self):
        """刷新日志文件"""
        self.load_log_file_async()

    def toggle_watching(self):
        """切换实时更新状态"""
        if self.is_watching.get():
            self.start_watching()
        else:
            self.stop_watching()

    def start_watching(self):
        """开始监视文件变化"""
        if self.watching_thread and self.watching_thread.is_alive():
            return  # 已经在监视

        if not self.current_log_file.exists():
            self.is_watching.set(False)
            messagebox.showwarning("警告", "日志文件不存在，无法开启实时更新。")
            return

        self.watching_thread = threading.Thread(target=self.watch_file_loop, daemon=True)
        self.watching_thread.start()

    def stop_watching(self):
        """停止监视文件变化"""
        self.is_watching.set(False)
        # 线程通过检查 is_watching 变量来停止，这里不需要强制干预
        self.watching_thread = None

    def watch_file_loop(self):
        """监视文件循环"""
        while self.is_watching.get():
            try:
                if not self.current_log_file.exists():
                    self.root.after(
                        0,
                        lambda: messagebox.showwarning("警告", "日志文件丢失，已停止实时更新。"),
                    )
                    self.root.after(0, self.is_watching.set, False)
                    break

                current_size = os.path.getsize(self.current_log_file)
                if current_size > self.last_file_size:
                    new_entries = self.read_new_logs(self.last_file_size)
                    self.last_file_size = current_size
                    if new_entries:
                        self.root.after(0, self.append_new_logs, new_entries)
                elif current_size < self.last_file_size:
                    # 文件被截断或替换
                    self.last_file_size = 0
                    self.root.after(0, self.refresh_log_file)
                    break  # 刷新会重新启动监视（如果需要），所以结束当前循环

            except Exception as e:
                print(f"监视日志文件时出错: {e}")
                self.root.after(0, self.is_watching.set, False)
                break

            time.sleep(1)

        self.watching_thread = None

    def read_new_logs(self, from_position):
        """读取新的日志条目并返回它们"""
        new_entries = []
        new_modules_found = False
        with open(self.current_log_file, "r", encoding="utf-8") as f:
            f.seek(from_position)
            line_count = self.log_index.total_entries
            for line in f:
                if line.strip():
                    try:
                        log_entry = json.loads(line)
                        self.log_index.add_entry(line_count, log_entry)
                        new_entries.append(log_entry)

                        logger_name = log_entry.get("logger_name", "")
                        if logger_name and logger_name not in self.modules:
                            self.modules.add(logger_name)
                            new_modules_found = True

                        line_count += 1
                    except json.JSONDecodeError:
                        continue
        if new_modules_found:
            self.root.after(0, self.update_module_list)
        return new_entries

    def append_new_logs(self, new_entries):
        """将新日志附加到显示中"""
        # 检查是否应附加或执行完全刷新（例如，如果过滤器处于活动状态）
        selected_modules = (
            self.selected_modules if (self.selected_modules and "全部" not in self.selected_modules) else None
        )
        level = self.level_var.get() if self.level_var.get() != "全部" else None
        search_text = self.search_var.get().strip() if self.search_var.get().strip() else None

        is_filtered = selected_modules or level or search_text

        if is_filtered:
            # 如果过滤器处于活动状态，我们必须执行完全刷新以应用它们
            self.filter_logs()
            return

        # 如果没有过滤器，只需附加新日志
        for entry in new_entries:
            self.log_display.append_entry(entry)

        # 更新状态
        total_count = self.log_index.total_entries
        self.status_var.set(f"显示 {total_count} 条日志")

    def update_module_list(self):
        """更新模块下拉列表"""
        current_selection = self.module_var.get()
        self.modules = set(self.log_index.module_index.keys())
        module_values = ["全部"] + sorted(list(self.modules))
        self.module_combo["values"] = module_values
        if current_selection in module_values:
            self.module_var.set(current_selection)
        else:
            self.module_var.set("全部")


def main():
    root = tk.Tk()
    LogViewer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
