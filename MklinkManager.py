"""
MklinkManager - Windows mklink 命令的图形化前端
基于 CustomTkinter 重写，改进自 C# WPF 版本

功能：
- 支持文件/文件夹的符号链接、硬链接、目录联接点
- 智能移动：自动复制数据后删除源，在原位置创建链接
- 执行历史记录
- 管理员权限检测与提权
- 路径选择对话框
- 成功后在目标位置自动生成 README_链接信息.txt 日志

设计：
  两个输入字段：
    ① 原文件/文件夹位置（链接将出现在这里）
    ② 希望实际存放位置（数据实际存储的地方）

  执行时根据两边路径的存在状态，自动判断以下场景：
    A. 希望实际位置存在，原位置不存在或已是链接 → 直接创建链接
    B. 原位置有数据，希望实际位置不存在 → 确认后移动数据，在原位置创建链接（最常见）
    C. 两边都有数据 → 弹窗让用户选择保留哪边
    D. 两边都不存在 → 文件夹模式询问新建，文件模式报错

  硬链接特殊处理：不支持移动，原文件必须存在
"""

import os
import shutil
import subprocess
import threading
import ctypes
import sys
from pathlib import Path
from datetime import datetime
from tkinter import filedialog, messagebox

import customtkinter as ctk

# ============================================================
# 配置
# ============================================================
ctk.set_appearance_mode("System")  # "System" | "Dark" | "Light"
ctk.set_default_color_theme("blue")


# ============================================================
# 工具函数
# ============================================================

def is_admin() -> bool:
    """检查是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def run_as_admin():
    """以管理员权限重新启动程序"""
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, __file__, None, 1
    )


def build_mklink_command(mode: str, link_type: str, link_path: str, target_path: str) -> str:
    """
    根据模式和链接类型生成 mklink 命令
    mode: "file" | "folder"
    link_type: "symbolic" | "hard" | "junction"

    mklink 参数说明：
      mklink        → 文件符号链接（默认，无参数）
      mklink /H     → 文件硬链接（同一文件数据的多个目录项）
      mklink /D     → 文件夹符号链接
      mklink /J     → 目录联接点（junction，类似快捷方式但对程序透明）
    """
    if link_type == "hard":
        param = "/H"
    elif link_type == "junction":
        param = "/J"
    else:  # symbolic
        # 文件符号链接无参数，文件夹符号链接用 /D
        param = "/D" if mode == "folder" else ""

    return f'mklink {param} "{link_path}" "{target_path}"'


def run_mklink(command: str) -> tuple[bool, str]:
    """执行 mklink 命令，返回 (成功?, 输出信息)"""
    try:
        # shell=True 让 cmd.exe 直接解析完整命令字符串，避免路径带空格时引号被吞
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="gbk",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return True, "✅ 链接创建成功！"
        else:
            return False, f"❌ 执行失败\n{output}"
    except Exception as e:
        return False, f"❌ 异常错误\n{str(e)}"


def _build_log_info(link_type: str, link_path: str, target: str, action: str, overwrite: bool) -> dict:
    """构建日志信息字典，供 _on_result 写入 txt 文件"""
    type_names = {"symbolic": "符号链接", "hard": "硬链接", "junction": "目录联接"}
    return {
        "link_type": type_names.get(link_type, link_type),
        "link_path": link_path,
        "target": target,
        "action": action,
        "overwrite": overwrite,
    }


# ============================================================
# 主应用类
# ============================================================

class MklinkApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # ---------- 窗口设置 ----------
        self.title("MklinkManager - 链接管理工具")
        self.geometry("560x680")
        self.minsize(500, 580)

        # ---------- 状态变量 ----------
        self.mode = ctk.StringVar(value="folder")        # "file" | "folder"
        self.link_type = ctk.StringVar(value="symbolic") # "symbolic" | "hard" | "junction"
        self.link_path = ctk.StringVar(value="")       # 链接路径（原文件/文件夹位置，链接将出现在这里）
        self.target_path = ctk.StringVar(value="")      # 希望实际存放位置（希望数据实际存储的地方）
        self.note = ctk.StringVar(value="")              # 用户备注，显示在历史记录中
        self.history: list[str] = []
        self._log_info: dict = {}                       # 当前操作的记录信息，成功后写入日志文件
        self._selected_history_index: int | None = None  # 当前选中的历史记录行索引
        # 优先放在可执行文件旁边（PyInstaller 打包后 sys.executable 是 .exe 路径，开发时 __file__ 是 .py 路径）
        import sys as _sys
        if getattr(_sys, 'frozen', False):
            _base_dir = os.path.dirname(_sys.executable)
        else:
            _base_dir = os.path.dirname(os.path.abspath(__file__))
        self.history_file = os.path.join(_base_dir, "history.json")

        # ---------- 管理员检测 ----------
        self._admin = is_admin()

        # ---------- 构建 UI ----------
        self._build_ui()

        # ---------- 加载持久化历史 ----------
        self._load_history()

    # ========================================================
    # UI 构建
    # ========================================================

    def _build_ui(self):
        """构建完整界面"""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---- 顶部标题栏 ----
        title_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        title_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=(10, 0))
        title_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            title_frame,
            text="MklinkManager",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        if not self._admin:
            admin_btn = ctk.CTkButton(
                title_frame,
                text="⚡ 以管理员运行",
                width=140,
                height=28,
                font=ctk.CTkFont(size=12),
                fg_color="#E67E22",
                hover_color="#D35400",
                command=self._restart_as_admin,
            )
            admin_btn.grid(row=0, column=1, sticky="e", padx=(10, 0))

        # ---- 主内容区 ----
        content = ctk.CTkScrollableFrame(self, corner_radius=10)
        content.grid(row=1, column=0, sticky="nsew", padx=15, pady=(10, 15))
        content.grid_columnconfigure(0, weight=1)

        # 2. 链接类型选择
        self._build_type_section(content)

        # 1. 模式选择（类型按钮已创建，_on_mode_change 内部调用 _update_type_availability 不会报错）
        self._build_mode_section(content)

        # 分隔线
        ctk.CTkFrame(content, height=2, fg_color=("gray70", "gray30")).grid(
            row=2, column=0, sticky="ew", pady=(5, 10)
        )

        # 备注输入
        self._build_note_section(content)

        # 3. 源文件文件夹路径
        self._build_link_path_section(content)

        # 4. 希望实际位置
        self._build_target_section(content)

        # 分隔线
        ctk.CTkFrame(content, height=2, fg_color=("gray70", "gray30")).grid(
            row=6, column=0, sticky="ew", pady=(5, 10)
        )

        # 5. 执行按钮
        self._build_execute_section(content)

        # 6. 结果输出
        self._build_result_section(content)

        # 7. 历史记录
        self._build_history_section(content)

        # 初始化 UI 状态（所有控件已就绪）
        self._on_mode_change("folder")

    def _build_mode_section(self, parent):
        """模式选择：文件 / 文件夹"""
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        # 空列吸收多余空间，保持内容列紧凑不随窗口移动
        frame.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            frame, text="链接模式", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, padx=(15, 20), pady=12, sticky="w")

        # 文件夹模式 RadioButton（左边，默认选中）
        self.mode_radio_folder = ctk.CTkRadioButton(
            frame,
            text="文件夹模式",
            variable=self.mode,
            value="folder",
            command=lambda: self._on_mode_change("folder"),
            font=ctk.CTkFont(size=13),
        )
        self.mode_radio_folder.grid(row=0, column=1, sticky="w", pady=12)

        # 文件模式 RadioButton（紧挨着文件夹模式）
        self.mode_radio_file = ctk.CTkRadioButton(
            frame,
            text="文件模式",
            variable=self.mode,
            value="file",
            command=lambda: self._on_mode_change("file"),
            font=ctk.CTkFont(size=13),
        )
        self.mode_radio_file.grid(row=0, column=2, sticky="w", pady=12, padx=(15, 0))

        # 提示文字放在下方独立一行，始终可见，自动换行
        # text 为空占位，具体内容在 _on_mode_change 中动态设置
        self.mode_hint = ctk.CTkLabel(
            frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"),
            wraplength=460,
            justify="left",
        )
        self.mode_hint.grid(row=1, column=1, columnspan=3, sticky="w", padx=(0, 15), pady=(4, 12))

    def _build_type_section(self, parent):
        """链接类型选择（RadioButton 组）"""
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        # 空列吸收多余空间，保持内容列紧凑不随窗口移动
        frame.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(
            frame, text="链接类型", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, padx=(15, 20), pady=12, sticky="w")

        self.type_radio_symbolic = ctk.CTkRadioButton(
            frame,
            text="符号链接",
            variable=self.link_type,
            value="symbolic",
            command=lambda: self._on_type_change("symbolic"),
            font=ctk.CTkFont(size=13),
        )
        self.type_radio_symbolic.grid(row=0, column=1, padx=(0, 15), pady=12)

        self.type_radio_junction = ctk.CTkRadioButton(
            frame,
            text="目录联接",
            variable=self.link_type,
            value="junction",
            command=lambda: self._on_type_change("junction"),
            font=ctk.CTkFont(size=13),
        )
        self.type_radio_junction.grid(row=0, column=2, padx=(0, 15), pady=12)

        self.type_radio_hard = ctk.CTkRadioButton(
            frame,
            text="硬链接",
            variable=self.link_type,
            value="hard",
            command=lambda: self._on_type_change("hard"),
            font=ctk.CTkFont(size=13),
        )
        self.type_radio_hard.grid(row=0, column=3, sticky="w", pady=12)

        # 第二行：提示文字（始终可见，自动换行）
        self.type_hint = ctk.CTkLabel(
            frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"),
            wraplength=460,
            justify="left",
        )
        self.type_hint.grid(row=1, column=1, columnspan=4, sticky="w", padx=(0, 15), pady=(4, 12))

        # 初始状态：文件夹模式，默认符号链接，禁用硬链接
        self._update_type_availability()
        self._on_type_change("symbolic")

    def _build_note_section(self, parent):
        """备注输入（可选，用于在历史记录中识别链接用途）"""
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame, text="备注", font=ctk.CTkFont(size=14, weight="bold"), width=120, anchor="w"
        ).grid(row=0, column=0, padx=(15, 20), pady=12, sticky="w")

        self.note_entry = ctk.CTkEntry(
            frame,
            textvariable=self.note,
            placeholder_text="可选：填写备注（如用途、项目名），方便在历史记录中查找...",
            font=ctk.CTkFont(size=13),
        )
        self.note_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=12)

        # 占位标签，宽度与浏览按钮一致，使备注输入栏右侧与其他输入行对齐
        ctk.CTkLabel(frame, text="", width=80).grid(row=0, column=2, padx=(0, 15))

    def _build_link_path_section(self, parent):
        """原文件/文件夹位置（链接将出现在这里）"""
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        frame.grid_columnconfigure(1, weight=1)

        self.link_label = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=14, weight="bold"), width=120, anchor="w"# text 为空占位，原文件夹位置字样在 _on_mode_change 中动态设置
        )
        self.link_label.grid(row=0, column=0, padx=(15, 20), pady=12, sticky="w")

        self.link_entry = ctk.CTkEntry(
            frame,
            textvariable=self.link_path,
            placeholder_text="选择原文件夹，链接将创建在这里...",
            font=ctk.CTkFont(size=13),
        )
        self.link_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=12)

        ctk.CTkButton(
            frame,
            text="📂 浏览",
            width=80,
            font=ctk.CTkFont(size=13),
            command=self._browse_link_path,
        ).grid(row=0, column=2, padx=(0, 15), pady=12)

    def _build_target_section(self, parent):
        """希望实际存放位置（希望数据实际存储的地方）"""
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        frame.grid_columnconfigure(1, weight=1)

        self.target_label = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=14, weight="bold"), width=120, anchor="w"# text 为空占位，希望实际存放位置字样在 _on_mode_change 中动态设置
        )
        self.target_label.grid(row=0, column=0, padx=(15, 20), pady=12, sticky="w")

        self.target_entry = ctk.CTkEntry(
            frame,
            textvariable=self.target_path,
            placeholder_text="选择希望实际存放的父文件夹，自动用原名创建到此文件夹下...",
            font=ctk.CTkFont(size=13),
        )
        self.target_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=12)

        ctk.CTkButton(
            frame,
            text="📂 浏览",
            width=80,
            font=ctk.CTkFont(size=13),
            command=self._browse_target,
        ).grid(row=0, column=2, padx=(0, 15), pady=12)

    def _build_execute_section(self, parent):
        """执行按钮 + 进度条"""
        frame = ctk.CTkFrame(parent, corner_radius=8, fg_color="transparent")
        frame.grid(row=7, column=0, sticky="ew", pady=(5, 8))
        frame.grid_columnconfigure(0, weight=1)

        self.execute_btn = ctk.CTkButton(
            frame,
            text="🚀 执行 mklink",
            font=ctk.CTkFont(size=16, weight="bold"),
            height=45,
            corner_radius=8,
            command=self._execute_mklink,
        )
        self.execute_btn.grid(row=0, column=0, sticky="ew", padx=50)

        # 进度条（初始隐藏，复制/移动时显示）
        self.progress_bar = ctk.CTkProgressBar(frame, height=10, corner_radius=5)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=50, pady=(8, 0))
        self.progress_bar.set(0)
        self.progress_bar.grid_remove()

    def _build_result_section(self, parent):
        """结果输出区域"""
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=8, column=0, sticky="ew", pady=(0, 8))
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame, text="执行结果", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")

        self.result_text = ctk.CTkTextbox(
            frame,
            height=80,
            font=ctk.CTkFont(size=12),
            wrap="word",
            state="disabled",
        )
        self.result_text.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 10))
        self._set_result("等待执行...", "gray")

    def _build_history_section(self, parent):
        """历史记录区域"""
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=9, column=0, sticky="ew", pady=(0, 8))
        frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=15, pady=(10, 5))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="历史记录", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            header,
            text="清空",
            width=60,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray80"),
            command=self._clear_history,
        ).grid(row=0, column=1, sticky="e")

        # 删除按钮（初始隐藏，选中有效记录后显示）
        self.undo_btn = ctk.CTkButton(
            header,
            text="删除链接",
            width=70,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#E74C3C",
            hover_color="#C0392B",
            command=self._undo_link,
        )

        self.history_text = ctk.CTkTextbox(
            frame,
            height=100,
            font=ctk.CTkFont(size=11),
            wrap="word",
            state="disabled",
        )
        self.history_text.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 10))

        # 点击历史条目选中
        self.history_text.bind("<Button-1>", self._on_history_click)

    # ========================================================
    # 事件处理 —— 模式 / 类型切换
    # ========================================================

    def _on_mode_change(self, value: str):
        """模式切换（value 是 "file" 或 "folder"）"""
        # 防御性 set：Radiobutton 可能尚未更新 StringVar 就触发了 command
        self.mode.set(value)
        if value == "file":
            self.link_label.configure(text="原文件位置")
            self.link_entry.configure(placeholder_text="选择原文件，链接将创建在这里...")
            self.target_label.configure(text="希望实际存放位置")
            self.target_entry.configure(placeholder_text="选择希望实际存放的文件夹，自动用原文件名创建到此文件夹下...")
            self.mode_hint.configure(text="为单个文件创建链接")
        else:
            self.link_label.configure(text="原文件夹位置")
            self.link_entry.configure(placeholder_text="选择原文件夹，链接将创建在这里...")
            self.target_label.configure(text="希望实际存放位置")
            self.target_entry.configure(placeholder_text="选择希望实际存放的父文件夹，自动用原名创建到此文件夹下...")
            self.mode_hint.configure(text="为整个文件夹创建链接")

        # 更新类型可用性，自动切换到兼容类型
        self._update_type_availability()
        # 刷新类型提示文字（符号链接的提示依赖模式）
        self._on_type_change(self.link_type.get())

    def _update_type_availability(self):
        """根据当前模式，禁用不兼容的链接类型"""
        current_mode = self.mode.get()
        current_type = self.link_type.get()

        if current_mode == "file":
            # 文件模式：硬链接 ✅  符号链接 ✅  目录联接 ❌
            self.type_radio_hard.configure(state="normal")
            self.type_radio_symbolic.configure(state="normal")
            self.type_radio_junction.configure(state="disabled")
            # 如果当前选中了目录联接，自动切到符号链接
            if current_type == "junction":
                self.link_type.set("symbolic")
                self._on_type_change("symbolic")
        else:  # folder
            # 文件夹模式：符号链接 ✅  目录联接 ✅  硬链接 ❌
            self.type_radio_hard.configure(state="disabled")
            self.type_radio_symbolic.configure(state="normal")
            self.type_radio_junction.configure(state="normal")
            # 如果当前选中了硬链接，自动切到符号链接
            if current_type == "hard":
                self.link_type.set("symbolic")
                self._on_type_change("symbolic")

    def _on_type_change(self, value: str):
        """链接类型切换（value 是 "symbolic" / "hard" / "junction"）"""
        hint_map = {
            "symbolic": (
                '推荐选择。\n'
                '链接就像"快捷方式"，访问时自动跳转到实际位置。\n'
                '修改实际位置的内容，链接也跟着变；\n'
                '不需要时可像删除快捷方式一样删除链接，不影响实际文件。'
                if self.mode.get() == "folder"
                else '推荐选择。\n链接就像"快捷方式"，访问时自动跳转到实际文件。'
            ),
            "hard": (
                '⚠️ 高级选项。\n'
                '给同一个文件起两个名字，改任何一个内容都一样。删除一个，另一个还在。\n'
                '不确定用途时请选符号链接。'
            ),
            "junction": (
                '类似"快捷方式"，\n'
                'windows系统也会以为这就是实际文件夹本身，可用于系统目录重定向。\n'
                '不确定用途时请选符号链接。'
            ),
        }
        self.link_type.set(value)
        self.type_hint.configure(text=hint_map.get(value, ""))

    # ========================================================
    # 事件处理 —— 路径浏览
    # ========================================================

    def _browse_link_path(self):
        """选择原文件/文件夹位置"""
        if self.mode.get() == "file":
            path = filedialog.askopenfilename(title="选择原文件")
        else:
            path = filedialog.askdirectory(title="选择原文件夹")
        if path:
            self.link_path.set(path)
            # 自动拼接希望实际存放位置
            self._auto_fill_target()

    def _browse_target(self):
        """选择希望实际存放的父目录（自动用原名创建到此文件夹下）"""
        parent_dir = filedialog.askdirectory(title="选择希望实际存放的父文件夹")
        if not parent_dir:
            return
        link_path = self.link_path.get().strip()
        if link_path:
            name = Path(link_path).name
            self.target_path.set(os.path.join(parent_dir, name))
        else:
            self.target_path.set(parent_dir)

    def _auto_fill_target(self):
        """
        选择原位置后，自动将原名拼接到希望实际存放位置。
        场景 B（最常见）的辅助：用户选了原位置，再选目标父目录时
        _browse_target 会自动拼接原名，这里先预填一个默认值。
        """
        link_path = self.link_path.get().strip()
        target = self.target_path.get().strip()
        if link_path and not target:
            name = Path(link_path).name
            parent = os.path.dirname(link_path) or os.path.abspath(".")
            self.target_path.set(os.path.join(parent, name))

    # ========================================================
    # 事件处理 —— 执行 & 后台线程
    # ========================================================

    def _execute_mklink(self):
        """
        执行 mklink 命令（智能模式：自动判断移动/链接/覆盖）

        四种场景（符号链接 & 目录联接）：
          A. 希望实际位置存在，原位置不存在或已是链接 → 直接创建链接
          B. 原位置有数据，希望实际位置不存在 → 确认后复制数据到目标 → 删源 → 创建链接（最常见）
          C. 两边都有数据 → 弹窗让用户选择保留哪边
          D. 两边都不存在 → 文件夹模式询问新建，文件模式报错

        硬链接特殊处理：不支持移动，原文件必须存在
        """
        link_path = self.link_path.get().strip()
        target = self.target_path.get().strip()
        mode = self.mode.get()
        link_type = self.link_type.get()

        # 验证输入
        if not link_path:
            messagebox.showwarning("输入不完整", "请选择原文件/文件夹位置")
            return
        if not target:
            messagebox.showwarning("输入不完整", "请选择希望实际存放位置")
            return

        # 防止原位置和希望实际位置相同（_auto_fill_target 会预填相同路径，用户可能直接点执行）
        if os.path.normpath(link_path) == os.path.normpath(target):
            messagebox.showerror(
                "路径错误",
                f"原位置和希望实际存放位置不能相同:\n{link_path}\n\n"
                "请点击希望实际存放位置的「📂 浏览」选择一个不同的文件夹。"
            )
            return

        link_exists = os.path.exists(link_path)
        target_exists = os.path.exists(target)
        # 注意：Windows 上 os.path.islink() 只检测符号链接，不检测目录联接（junction）
        # 因此如果原位置是 junction，会被当作"普通文件夹"处理
        link_is_link = os.path.islink(link_path) if link_exists else False

        # 硬链接特殊处理：原文件必须存在，在希望目标位置创建硬链接入口
        # 硬链接 = 同一文件数据的两个目录项，通过 inode 关联
        # 注意：硬链接参数语义与非硬链接相反 ——
        #   新入口在 target（希望目标位置），数据在 link_path（原文件位置）
        #   mklink /H "新入口(target)" "已有文件(link_path)"
        if link_type == "hard":
            if not link_exists:
                messagebox.showerror("路径错误", f"原文件不存在:\n{link_path}")
                return
            action = "创建硬链接入口"
            overwrite = False
            if target_exists:
                if not messagebox.askyesno("确认覆盖", f"希望目标位置已存在:\n{target}\n\n是否覆盖？"):
                    return
                os.remove(target)
                action = "覆盖目标位置后创建硬链接入口"
                overwrite = True
            self._log_info = _build_log_info(link_type, target, link_path, action, overwrite)
            # 硬链接命令顺序：mklink /H "新链接(target)" "已有文件(link_path)"
            self._do_mklink(target, link_path)
            return

        # ---- 场景判断（符号链接 & 目录联接） ----
        need_move = False
        move_src = None
        move_dst = None

        if target_exists and (not link_exists or link_is_link):
            # 场景 A：希望实际位置存在，原位置不存在或已是链接 → 直接创建链接
            action = "直接创建链接（原位置不存在）"
            if link_exists and link_is_link:
                if not messagebox.askyesno("确认覆盖", f"原位置已是链接:\n{link_path}\n\n是否覆盖？"):
                    return
                os.remove(link_path)
                action = "覆盖已有链接后重新创建"
            self._log_info = _build_log_info(link_type, link_path, target, action, False)
            self._do_mklink(link_path, target)
            return

        elif link_exists and not link_is_link and not target_exists:
            # 场景 B：原位置有数据，希望实际位置不存在 → 移动 + 链接（最常见）
            if not messagebox.askyesno(
                "确认移动",
                f"即将把原位置数据移动到希望实际存放位置，\n"
                f"然后在原位置创建链接。\n\n"
                f"原位置: {link_path}\n"
                f"→ 实际存放位置: {target}\n\n"
                f"是否继续？"
            ):
                return
            self._log_info = _build_log_info(link_type, link_path, target, "移动数据后在原位置创建链接", True)
            need_move = True
            move_src = link_path
            move_dst = target

        elif link_exists and not link_is_link and target_exists:
            # 场景 C：两边都有数据 → 弹窗选择
            item_name = "文件夹" if mode == "folder" else "文件"
            choice = messagebox.askyesnocancel(
                "位置冲突",
                f"原位置已有数据:\n{link_path}\n\n"
                f"希望实际位置也存在:\n{target}\n\n"
                f"● [是] = 用原位置{item_name}覆盖希望实际位置，再创建链接\n"
                f"● [否] = 删除原位置，保留希望实际位置的{item_name}，并创建链接\n"
                f"● [取消] = 不做任何操作"
            )
            if choice is None:
                return  # 取消
            if choice:
                # 是：用原位置覆盖实际位置 → 删除实际位置，然后移动原位置数据过去，再创建链接
                if mode == "folder":
                    shutil.rmtree(target)
                else:
                    os.remove(target)
                self._log_info = _build_log_info(link_type, link_path, target, "用原位置数据覆盖希望实际位置后创建链接", True)
                need_move = True
                move_src = link_path
                move_dst = target
                # 不 return，继续走到下面的移动+链接代码
            else:
                # 否：保留希望实际位置的数据 → 删除原位置，直接创建链接
                if mode == "folder":
                    shutil.rmtree(link_path)
                else:
                    os.remove(link_path)
                self._log_info = _build_log_info(link_type, link_path, target, "删除原位置数据，在希望实际位置创建链接", True)
                self._do_mklink(link_path, target)
                return  # "否"分支到此结束，不需要移动

        else:
            # 场景 D：两边都不存在（或原位置是「断了」的符号链接，目标已丢失）
            if mode == "folder":
                # 文件夹模式：询问是否创建新文件夹
                if not messagebox.askyesno(
                    "新建文件夹",
                    f"原位置不存在:\n{link_path}\n\n"
                    f"希望实际位置也不存在:\n{target}\n\n"
                    f"是否在希望实际位置创建新文件夹，并在原位置创建链接？"
                ):
                    return
                try:
                    os.makedirs(target)
                except OSError as e:
                    messagebox.showerror("创建失败", f"无法创建文件夹:\n{target}\n\n{e}")
                    return
                # 新文件夹创建成功，直接创建链接
                self._log_info = _build_log_info(link_type, link_path, target, "新建文件夹后创建链接", False)
                self._do_mklink(link_path, target)
            else:
                # 文件模式：直接报错
                messagebox.showerror(
                    "路径错误",
                    f"原文件不存在:\n{link_path}\n\n希望实际位置也不存在:\n{target}\n\n至少需要一边有数据。"
                )
            return

        # 执行移动 + 链接
        if need_move and move_src and move_dst:
            self.execute_btn.configure(state="disabled", text="⏳ 移动中...")
            self._set_result(f"正在移动...\n{move_src}\n→ {move_dst}", "gray")
            threading.Thread(target=self._do_move_and_link, args=(move_src, move_dst, link_path), daemon=True).start()

    def _do_move_and_link(self, src: str, dst: str, link_path: str):
        """
        后台线程：复制（带进度） → 验证 → 删源 → 创建链接
        复制和删除分两步捕获错误，让用户知道数据在哪一步出了问题
        """
        is_dir = os.path.isdir(src)
        total = self._count_files(src, is_dir)
        self.after(0, self._show_progress)

        # ---- 第 1 步：复制（带进度回调）----
        copied = [0]  # 用列表实现闭包可变计数器
        def _progress_copy(src_path, dst_path, *, follow_symlinks=True):
            shutil.copy2(src_path, dst_path, follow_symlinks=follow_symlinks)
            copied[0] += 1
            # 每 ~1% 或最后一项时更新进度条，避免过多排队
            step = max(1, total // 100)
            if copied[0] % step == 0 or copied[0] == total:
                self.after(0, self._update_progress, copied[0], total)

        try:
            dst_parent = os.path.dirname(dst)
            if dst_parent and not os.path.exists(dst_parent):
                os.makedirs(dst_parent)
            if is_dir:
                shutil.copytree(src, dst, copy_function=_progress_copy)
            else:
                shutil.copy2(src, dst)
                self.after(0, self._update_progress, 1, 1)
            if not os.path.exists(dst):
                raise OSError(f"复制后目标路径不存在：{dst}")
        except PermissionError as e:
            self.after(0, self._on_copy_permission_error, str(e), src, dst)
            return
        except OSError as e:
            self.after(0, self._on_copy_os_error, str(e), src, dst)
            return
        except Exception as e:
            self.after(0, self._on_copy_error, str(e), src, dst)
            return

        self.after(0, self._hide_progress)
        # ---- 第 2 步：删除源数据（失败则终止，原位置被占着无法创建链接）----
        try:
            if is_dir:
                shutil.rmtree(src)
            else:
                os.remove(src)
        except (PermissionError, OSError, Exception) as e:
            self.after(0, self._on_delete_source_failed, str(e), src, dst, is_dir)
            return
        # ---- 第 3 步：创建链接 ----
        self.after(0, self._do_mklink, link_path, dst)

    def _on_copy_permission_error(self, error: str, src: str, dst: str):
        """复制阶段权限错误：数据安全在原处"""
        self._hide_progress()
        item_name = "文件夹" if os.path.isdir(src) else "文件"
        self.execute_btn.configure(state="normal", text="🚀 执行 mklink")
        self._set_result(f"❌ 复制失败 — 权限不足\n{error}", "red")
        self._add_history(f"❌ 复制失败(权限): {src} → {dst}")
        messagebox.showerror(
            "复制失败 — 权限不足",
            f"复制阶段出错，原数据未受影响。\n\n"
            f"可能原因：目标目录无写入权限 或 源文件被占用。\n"
            f"数据仍在原位置：{src}\n\n"
            f"解决方案：\n"
            f"  1. 关闭占用文件的程序\n"
            f"  2. 以管理员身份重新运行本程序后重试\n"
            f"  3. 或手动移动上述{item_name}到：{dst}"
        )

    def _on_copy_os_error(self, error: str, src: str, dst: str):
        """复制阶段系统错误：数据安全在原处"""
        self._hide_progress()
        item_name = "文件夹" if os.path.isdir(src) else "文件"
        self.execute_btn.configure(state="normal", text="🚀 执行 mklink")
        self._set_result(f"❌ 复制失败\n{error}", "red")
        self._add_history(f"❌ 复制失败: {src} → {dst}")
        messagebox.showerror(
            "复制失败",
            f"复制阶段出错，原数据未受影响。\n\n"
            f"数据仍在：{src}\n"
            f"目标位置：{dst}\n\n"
            f"错误：{error}\n\n"
            f"请手动移动上述{item_name}到目标位置。"
        )

    def _on_copy_error(self, error: str, src: str, dst: str):
        """复制阶段未知错误：数据安全在原处"""
        self._hide_progress()
        self.execute_btn.configure(state="normal", text="🚀 执行 mklink")
        self._set_result(f"❌ 复制失败\n{error}", "red")
        self._add_history(f"❌ 复制失败: {src} → {dst}")

    def _on_delete_source_failed(self, error: str, src: str, dst: str, is_dir: bool):
        """删源失败（复制已成功，但原位置被占着无法创建链接）"""
        self._hide_progress()
        item_name = "文件夹" if is_dir else "文件"
        self.execute_btn.configure(state="normal", text="🚀 执行 mklink")
        self._set_result(f"⚠️ 复制成功，但删除源失败，链接未创建\n{error}", "red")
        self._add_history(f"⚠️ 目标位置已有数据，删除源失败: {src}\n请手动删除源后重试")
        messagebox.showwarning(
            "删除源数据失败",
            f"数据已成功复制到目标位置，\n"
            f"但无法自动删除源数据，因此无法在原位置创建链接。\n\n"
            f"源数据：{src}\n"
            f"目标位置：{dst}\n\n"
            f"错误：{error}\n\n"
            f"请手动删除上述{item_name}（确认目标位置数据完整后），\n"
            f"然后重新执行本程序创建链接。"
        )

    def _do_mklink(self, link_path: str, target: str):
        """
        生成 mklink 命令字符串，然后提交到后台线程执行
        不直接操作文件系统，只拼命令 → 调 cmd.exe 执行
        """
        self._hide_progress()
        command = build_mklink_command(
            self.mode.get(),
            self.link_type.get(),
            link_path,
            target,
        )
        self.execute_btn.configure(state="disabled", text="⏳ 执行中...")
        self._set_result(f"正在执行...\n{command}", "gray")
        threading.Thread(target=self._run_command, args=(command,), daemon=True).start()

    # ========================================================
    # UI 辅助方法 —— 结果输出 / 历史记录 / 管理员提权
    # ========================================================

    def _run_command(self, command: str):
        """后台线程执行命令"""
        success, output = run_mklink(command)
        self.after(0, self._on_result, success, output, command)

    def _on_result(self, success: bool, output: str, command: str):
        """命令执行完成后的 UI 更新"""
        self.execute_btn.configure(state="normal", text="🚀 执行 mklink")

        if success:
            self._set_result(output, "green")
            # 在希望实际位置写入日志文件
            self._write_log_file()
        else:
            self._set_result(output, "red")

        # 添加到历史
        ts = datetime.now().strftime("%H:%M:%S")
        status = "✅" if success else "❌"
        note_text = self.note.get().strip()
        note_part = f"【{note_text}】 " if note_text else ""
        self._add_history(f"[{ts}] {status} {note_part}{command}")

    def _write_log_file(self):
        """链接创建成功后，在希望实际位置写入日志 txt 文件"""
        info = self._log_info
        if not info:
            return
        try:
            target_dir = info["target"]
            # 确定日志文件路径：文件夹在内部，文件在旁边
            if os.path.isdir(target_dir):
                log_path = os.path.join(target_dir, "README_链接信息.txt")
            else:
                log_path = target_dir + "_README_链接信息.txt"

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            overwrite_text = "是" if info["overwrite"] else "否"
            lines = [
                "=" * 50,
                "MklinkManager 链接信息",
                "=" * 50,
                f"创建时间: {ts}",
                "链接方式: " + info["link_type"],
                "原文件/文件夹位置 (链接): " + info["link_path"],
                "实际存放位置 (数据): " + info["target"],
                "操作摘要: " + info["action"],
                "是否发生覆盖/移动: " + overwrite_text,
                "",
                "此文件由 MklinkManager 自动生成。",
            ]
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            pass  # 写日志失败不应影响主流程

    # ========================================================
    # 进度条辅助方法
    # ========================================================

    def _count_files(self, src: str, is_dir: bool) -> int:
        """统计待复制的文件总数（文件夹递归，文件返回 1）"""
        if not is_dir:
            return 1
        return sum(1 for _ in Path(src).rglob('*') if _.is_file())

    def _show_progress(self):
        """显示进度条"""
        self.progress_bar.set(0)
        self.progress_bar.grid()

    def _update_progress(self, current: int, total: int):
        """更新进度条（主线程安全）"""
        if total > 0:
            self.progress_bar.set(current / total)

    def _hide_progress(self):
        """隐藏进度条"""
        self.progress_bar.grid_remove()

    def _set_result(self, text: str, color: str):
        """设置结果文本框内容"""
        color_map = {
            "green": "#2ECC71",
            "red": "#E74C3C",
            "gray": ("gray50", "gray70"),
        }
        self.result_text.configure(state="normal")
        self.result_text.delete("0.0", "end")
        self.result_text.insert("0.0", text)
        self.result_text.configure(state="disabled")
        self.result_text.configure(text_color=color_map.get(color, ("gray50", "gray70")))

    def _add_history(self, text: str, save: bool = True):
        """添加历史记录"""
        self.history.append(text)
        self.history_text.configure(state="normal")
        self.history_text.insert("end", text + "\n")
        self.history_text.see("end")
        self.history_text.configure(state="disabled")
        if save:
            self._save_history()

    def _clear_history(self):
        """清空历史记录"""
        self.history.clear()
        self._selected_history_index = None
        self.undo_btn.grid_forget()
        self.history_text.configure(state="normal")
        self.history_text.delete("0.0", "end")
        self.history_text.configure(state="disabled")
        self._save_history()

    def _load_history(self):
        """启动时从文件加载历史记录"""
        import json
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, str):
                            self._add_history(entry, save=False)
        except Exception:
            pass

    def _save_history(self):
        """保存历史记录到文件"""
        import json
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_history_click(self, event):
        """点击历史记录条目：高亮选中行，显示操作按钮"""
        import re
        # 获取点击位置对应的行号
        index = self.history_text.index(f"@{event.x},{event.y}")
        line_num = int(index.split(".")[0]) - 1  # 0-based

        # 清除之前的高亮
        self.history_text.tag_remove("selected", "1.0", "end")

        if line_num < 0 or line_num >= len(self.history):
            self._selected_history_index = None
            self.undo_btn.grid_forget()
            return

        entry = self.history[line_num]

        # 高亮选中行
        start = f"{line_num + 1}.0"
        end = f"{line_num + 1}.end"
        self.history_text.tag_add("selected", start, end)

        if "✅" in entry:
            self.history_text.tag_config("selected", background="#3498DB", foreground="white")
            self.undo_btn.configure(text="删除链接", fg_color="#E74C3C", hover_color="#C0392B")
        else:
            self.history_text.tag_config("selected", background="#7F8C8D", foreground="white")
            self.undo_btn.configure(text="删除记录", fg_color="#95A5A6", hover_color="#7F8C8D")

        self._selected_history_index = line_num
        # 显示操作按钮
        self.undo_btn.grid(row=0, column=2, sticky="e", padx=(4, 0))

    def _undo_link(self):
        """撤销链接：删除链接文件 → 可选搬回数据 → 移除历史记录"""
        import re

        idx = self._selected_history_index
        if idx is None or idx >= len(self.history):
            return

        entry = self.history[idx]

        # ---- 失败记录：只删记录，不操作文件 ----
        if "❌" in entry:
            if not messagebox.askyesno("确认删除", f"将删除此条历史记录：\n{entry}\n\n不会操作任何文件。\n是否继续？"):
                return
            self._remove_history_entry(idx)
            messagebox.showinfo("已删除", "历史记录已删除。")
            return

        # ---- 成功记录：删除链接，可选自动搬回数据 ----
        # mklink [/D|/H|/J] "link_path" "target_path"
        match = re.search(r'mklink\s+(/[DHJ]\s+)?\s*"([^"]+)"\s*"([^"]+)"', entry)
        if not match:
            messagebox.showwarning("解析失败", "无法从历史记录中解析出链接路径。")
            return

        param = (match.group(1) or "").strip()  # "/D" | "/H" | "/J" | ""
        link_path = match.group(2)
        target_path = match.group(3)
        is_dir = param in ("/D", "/J")
        is_hardlink = param == "/H"

        link_exists = os.path.exists(link_path)
        target_exists = os.path.exists(target_path)

        # 判断 link_path 是否真的是链接（而非真实文件/目录）
        # 硬链接在系统层面就是真实文件，跳过此检测
        is_actually_link = (os.path.islink(link_path) or (
            is_dir and Path(link_path).is_junction()
        )) if link_exists and not is_hardlink else False

        # ---- 链接已不是链接（变成真实文件/目录）→ 重定向到对应情况 ----
        # 硬链接本身就是真实文件，跳过此检测
        if not is_hardlink and link_exists and not is_actually_link:
            if target_exists:
                # 两边都是真实数据 → 询问是否搬回或仅删记录
                choice = messagebox.askyesnocancel(
                    "原位置已不是链接",
                    f"原位置已不是链接，而是真实数据：\n{link_path}\n\n"
                    f"希望实际位置有数据：\n{target_path}\n\n"
                    f"● [是] = 搬回数据到原位置（覆盖原位置现有数据）\n"
                    f"● [否] = 仅移除历史记录，不操作文件\n"
                    f"● [取消] = 不做任何操作"
                )
                if choice is None:
                    return
                if choice:
                    self.undo_btn.configure(state="disabled", text="搬回中...")
                    self._set_result(f"正在搬回数据...\n{target_path}\n→ {link_path}", "gray")
                    threading.Thread(
                        target=self._do_move_back,
                        args=(target_path, link_path, is_dir, idx),
                        daemon=True,
                    ).start()
                else:
                    self._remove_history_entry(idx)
                    messagebox.showinfo("已删除", "历史记录已删除。")
                return
            else:
                # link 变成真实数据，target 丢了 → 当作情况4：仅删记录
                if messagebox.askyesno(
                    "确认删除记录",
                    f"原位置已不是链接，而是真实数据：\n{link_path}\n\n"
                    f"希望实际位置也已不存在：\n{target_path}\n\n"
                    f"是否仅移除历史记录？"
                ):
                    self._remove_history_entry(idx)
                    messagebox.showinfo("已删除", "历史记录已删除。")
                return

        # ---- 情况 4：链接和目标都不存在 → 仅删除记录 ----
        if not link_exists and not target_exists:
            if messagebox.askyesno(
                "确认删除记录",
                f"原位置链接和希望实际位置均已不存在：\n"
                f"  原位置：{link_path}\n"
                f"  希望实际位置：{target_path}\n\n"
                f"是否仅移除历史记录？"
            ):
                self._remove_history_entry(idx)
                messagebox.showinfo("已删除", "历史记录已删除。")
            return

        # ---- 情况 3：链接不存在，目标存在 ----
        if not link_exists and target_exists:
            if is_hardlink:
                # 硬链接：硬链接入口已删除，只剩原始文件 → 仅清理记录
                if messagebox.askyesno(
                    "确认清理",
                    f"硬链接希望实际位置已不存在：\n{link_path}\n\n"
                    f"原始文件仍在：\n{target_path}\n\n"
                    f"是否仅移除历史记录？"
                ):
                    self._remove_history_entry(idx)
                    messagebox.showinfo("已删除", "历史记录已删除。")
            else:
                if messagebox.askyesno(
                    "搬回数据",
                    f"原位置链接已不存在：\n{link_path}\n\n"
                    f"数据仍在希望实际位置：\n{target_path}\n\n"
                    f"是否将数据搬回原位置？"
                ):
                    self.undo_btn.configure(state="disabled", text="搬回中...")
                    self._set_result(f"正在搬回数据...\n{target_path}\n→ {link_path}", "gray")
                    threading.Thread(
                        target=self._do_move_back,
                        args=(target_path, link_path, is_dir, idx),
                        daemon=True,
                    ).start()
            return

        # ---- 情况 2：链接存在，目标不存在 ----
        if link_exists and not target_exists:
            if is_hardlink:
                # 硬链接：原始文件已删除，只剩硬链接入口 → 仅清理记录
                if messagebox.askyesno(
                    "确认清理",
                    f"硬链接文件位置已不存在：\n{target_path}\n\n"
                    f"希望实际位置仍在：\n{link_path}\n\n"
                    f"是否仅移除历史记录？"
                ):
                    self._remove_history_entry(idx)
                    messagebox.showinfo("已删除", "历史记录已删除。")
            else:
                if messagebox.askyesno(
                    "希望实际位置已丢失",
                    f"希望实际位置已不存在：\n{target_path}\n\n"
                    f"原位置链接仍在：\n{link_path}\n\n"
                    f"是否删除此链接并移除历史记录？"
                ):
                    if self._delete_link_file(link_path, is_dir):
                        self._remove_history_entry(idx)
                    messagebox.showinfo("已完成", "链接及历史记录已清理。")
            return

        # ---- 情况 1：链接和目标都存在 → 正常流程 ----
        # 步骤 1：确认删除链接
        if is_hardlink:
            # 硬链接：两边都是入口，问删哪个
            # mklink /H "新入口(link_path)" "原始文件(target_path)"
            choice = messagebox.askyesnocancel(
                "选择删除",
                f"原位置和希望目标位置均为硬链接入口，\n"
                f"数据相同，删除任意一个不影响数据：\n\n"
                f"硬链接入口：{link_path}\n"
                f"原始文件：{target_path}\n\n"
                f"● [是] = 删除硬链接入口（保留原始文件）\n"
                f"● [否] = 删除原始文件（保留硬链接入口）\n"
                f"● [取消] = 不做任何操作"
            )
            if choice is None:
                return  # 取消
            if choice:
                # 是：删除硬链接入口（link_path）
                if self._delete_link_file(link_path, is_dir):
                    messagebox.showinfo("完成", f"已删除硬链接入口。\n数据仍在：\n{target_path}")
                    self._remove_history_entry(idx)
            else:
                # 否：删除原始文件（target_path）
                if self._delete_link_file(target_path, is_dir):
                    messagebox.showinfo("完成", f"已删除原始文件。\n数据仍在：\n{link_path}")
                    self._remove_history_entry(idx)
            return
        else:
            confirm_msg = (
                f"将删除链接：\n{link_path}\n\n"
                f"实际数据在：\n{target_path}\n\n是否继续？"
            )
        if not messagebox.askyesno("确认撤销", confirm_msg):
            return

        # 步骤 2：删除链接（先删，腾出原位置）
        if not self._delete_link_file(link_path, is_dir):
            return

        # 步骤 3（非硬链接）：询问是否搬回
        if not is_hardlink:
            if messagebox.askyesno(
                "搬回数据",
                f"链接已删除。\n\n"
                f"数据在：{target_path}\n\n"
                f"是否搬回原位置？\n{link_path}\n\n"
                f"选「否」则数据保留在目标位置。"
            ):
                self.undo_btn.configure(state="disabled", text="搬回中...")
                self._set_result(f"正在搬回数据...\n{target_path}\n→ {link_path}", "gray")
                threading.Thread(
                    target=self._do_move_back,
                    args=(target_path, link_path, is_dir, idx),
                    daemon=True,
                ).start()
                return

        # 步骤 4：提示结果 + 移除记录（用户选了不搬回）
        messagebox.showinfo("完成", f"链接已删除。\n数据仍在：\n{target_path}")
        self._remove_history_entry(idx)

    def _delete_link_file(self, link_path: str, is_dir: bool) -> bool:
        """删除一个链接文件/目录。返回 True 表示删除成功。"""
        try:
            if is_dir:
                os.rmdir(link_path)
            else:
                os.remove(link_path)
            return True
        except OSError as e:
            err_msg = str(e)
            if "directory is not empty" in err_msg.lower() or "目录不是空的" in err_msg:
                messagebox.showerror(
                    "删除失败",
                    f"目录无法删除：\n{link_path}\n\n"
                    f"此前检测为链接，但删除时发现内部有文件。\n"
                    f"这通常是极罕见的竞态条件（检测与删除之间被写入了数据）。\n\n"
                    f"请检查该目录内容，确认后手动处理。"
                )
            else:
                messagebox.showerror("删除失败", f"无法删除链接：\n{link_path}\n\n{e}")
            return False
        except Exception as e:
            messagebox.showerror("删除失败", f"无法删除链接：\n{link_path}\n\n{e}")
            return False

    def _do_move_back(self, src: str, dst: str, is_dir: bool, idx: int):
        """后台线程：复制（带进度） → 验证 → 删源。复制和删除分两步捕获错误"""
        import shutil as _shutil
        total = self._count_files(src, is_dir)
        self.after(0, self._show_progress)

        # ---- 第 1 步：复制（带进度回调）----
        copied = [0]
        def _progress_copy(src_path, dst_path, *, follow_symlinks=True):
            _shutil.copy2(src_path, dst_path, follow_symlinks=follow_symlinks)
            copied[0] += 1
            step = max(1, total // 100)
            if copied[0] % step == 0 or copied[0] == total:
                self.after(0, self._update_progress, copied[0], total)

        try:
            dst_parent = os.path.dirname(dst)
            if dst_parent and not os.path.exists(dst_parent):
                os.makedirs(dst_parent)
            if is_dir:
                _shutil.copytree(src, dst, copy_function=_progress_copy)
            else:
                _shutil.copy2(src, dst)
                self.after(0, self._update_progress, 1, 1)
            if not os.path.exists(dst):
                raise OSError(f"复制后目标路径不存在：{dst}")
        except PermissionError as e:
            self.after(0, self._on_copy_back_permission_error, str(e), src, dst, is_dir)
            return
        except OSError as e:
            self.after(0, self._on_copy_back_os_error, str(e), src, dst, is_dir)
            return
        except Exception as e:
            self.after(0, self._on_copy_back_error, str(e), src, dst, is_dir)
            return

        self.after(0, self._hide_progress)
        # ---- 第 2 步：删除源数据（失败只警告，不阻止完成）----
        try:
            if is_dir:
                _shutil.rmtree(src)
            else:
                os.remove(src)
        except (PermissionError, OSError, Exception) as e:
            self.after(0, self._on_delete_source_back_failed, str(e), src, dst, is_dir, idx)
            return
        self.after(0, self._on_move_back_success, dst, idx)

    def _on_move_back_success(self, dst: str, idx: int):
        """搬回成功回调"""
        self._hide_progress()
        self.undo_btn.configure(state="normal", text="删除链接", fg_color="#E74C3C", hover_color="#C0392B")
        self._set_result(f"✅ 数据已搬回：\n{dst}", "green")
        self._remove_history_entry(idx)
        messagebox.showinfo("完成", f"链接已删除，数据已搬回：\n{dst}")

    def _on_copy_back_permission_error(self, error: str, src: str, dst: str, is_dir: bool):
        """搬回-复制阶段权限错误：数据安全在目标位置"""
        self._hide_progress()
        item_name = "文件夹" if is_dir else "文件"
        self.undo_btn.configure(state="normal", text="删除链接", fg_color="#E74C3C", hover_color="#C0392B")
        self._set_result(f"❌ 搬回复制失败 — 权限不足\n{error}", "red")
        messagebox.showerror(
            "搬回复制失败 — 权限不足",
            f"复制阶段出错，数据未受影响。\n\n"
            f"数据仍在：{src}\n\n"
            f"可能原因：目标目录无写入权限 或 源文件被占用（如 DLL 被加载）。\n"
            f"解决方案：\n"
            f"  1. 关闭占用文件的程序\n"
            f"  2. 以管理员身份重新运行本程序后重试撤销\n"
            f"  3. 或手动移动上述{item_name}到：{dst}"
        )

    def _on_copy_back_os_error(self, error: str, src: str, dst: str, is_dir: bool):
        """搬回-复制阶段系统错误：数据安全在目标位置"""
        self._hide_progress()
        item_name = "文件夹" if is_dir else "文件"
        self.undo_btn.configure(state="normal", text="删除链接", fg_color="#E74C3C", hover_color="#C0392B")
        self._set_result(f"❌ 搬回复制失败\n{error}", "red")
        messagebox.showerror(
            "搬回复制失败",
            f"复制阶段出错，数据未受影响。\n\n"
            f"链接已删除，数据仍在：{src}\n"
            f"目标位置：{dst}\n\n"
            f"错误：{error}\n\n"
            f"请手动移动上述{item_name}到目标位置后重试删除记录。"
        )

    def _on_copy_back_error(self, error: str, src: str, dst: str, is_dir: bool):
        """搬回-复制阶段未知错误：数据安全在目标位置"""
        self._hide_progress()
        item_name = "文件夹" if is_dir else "文件"
        self.undo_btn.configure(state="normal", text="删除链接", fg_color="#E74C3C", hover_color="#C0392B")
        self._set_result(f"❌ 搬回复制失败\n{error}", "red")
        messagebox.showerror(
            "搬回复制失败",
            f"复制阶段出错，数据未受影响。\n\n"
            f"链接已删除，数据仍在：{src}\n"
            f"目标位置：{dst}\n\n"
            f"错误：{error}\n\n"
            f"请手动移动上述{item_name}到目标位置后重试删除记录。"
        )

    def _on_delete_source_back_failed(self, error: str, src: str, dst: str, is_dir: bool, idx: int):
        """搬回-删源失败（复制已成功）：移除历史，仅提示用户手动清理源"""
        self._hide_progress()
        item_name = "文件夹" if is_dir else "文件"
        self.undo_btn.configure(state="normal", text="删除链接", fg_color="#E74C3C", hover_color="#C0392B")
        self._set_result(f"⚠️ 数据已搬回，但删除源失败\n{error}", "red")
        self._remove_history_entry(idx)
        messagebox.showwarning(
            "删除源数据失败",
            f"数据已成功搬回原位置。\n\n"
            f"但无法自动删除源数据：{src}\n\n"
            f"错误：{error}\n\n"
            f"请确认搬回的数据完整后，手动删除上述{item_name}。"
        )

    def _remove_history_entry(self, idx: int):
        """从历史列表和文本框中移除一条记录"""
        self.history.pop(idx)
        self._selected_history_index = None
        self.undo_btn.grid_forget()

        self.history_text.configure(state="normal")
        self.history_text.delete("1.0", "end")
        for item in self.history:
            self.history_text.insert("end", item + "\n")
        self.history_text.configure(state="disabled")
        self.history_text.see("end")

        self._save_history()

    def _restart_as_admin(self):
        """以管理员权限重启"""
        if messagebox.askyesno(
            "管理员权限",
            "某些操作（如在 C:\\ 下创建链接）需要管理员权限。\n\n是否以管理员身份重新启动？",
        ):
            run_as_admin()
            self.quit()


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    app = MklinkApp()
    app.mainloop()