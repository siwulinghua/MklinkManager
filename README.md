# MklinkManager

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)

**Windows `mklink` 命令的图形化前端** — 安全、直观地管理文件/文件夹的符号链接、硬链接和目录联接。

## ✨ 功能

- 🗂️ **文件 / 文件夹**模式自由切换
- 🔗 支持三种链接类型：**符号链接**（推荐）、**目录联接**、**硬链接**
- 🚛 **智能移动**：自动将数据搬到目标位置，在原位创建链接
- 🔙 **撤销链接**：一键删除链接并可选搬回数据
- 📜 **历史记录**：持久化保存，支持清空和撤销
- 🛡️ **管理员提权**：自动检测并在需要时以管理员身份重启
- 📝 **自动生成日志**：每次创建后在目标位置写入 `README_链接信息.txt`


## 🔧 安装

### 从 Release 下载

1. 前往 [Releases](https://github.com/siwulinghua/MklinkManager/releases) 页面
2. 下载最新版 `MklinkManager.zip`
3. 解压后双击 `MklinkManager.exe` 即可运行

### 从源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/siwulinghua/MklinkManager.git
cd MklinkManager

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python MklinkManager.py
```

## 📖 使用说明

```
原文件/文件夹位置    ← 你希望链接出现在哪里（如桌面）
希望实际存放位置     ← 数据真正存在哪里（如 D 盘）
```

| 链接类型 | 适用模式 | 说明 |
|---------|:---:|------|
| 符号链接 | 文件 / 文件夹 | 推荐，类似快捷方式但程序透明访问 |
| 目录联接 | 文件夹 | Windows 原生，系统视为真实目录 |
| 硬链接 | 文件 | 同一文件的两个名字，改一个另一个也变 |

## 🛡️ 防篡改验证

下载后请验证 exe 完整性，防止供应链攻击或传输损坏：

```powershell
# SHA-256 验证
Get-FileHash .\MklinkManager.exe -Algorithm SHA256 | Format-List
```

**应与以下值完全一致：**

```
SHA-256: aca43cd54ca4baabaf253907e3ed69d0eee65ef6bd0384fe9f45a27d7188331a
```

> ✅ 哈希匹配 = 文件完整未被篡改 | ❌ 哈希不匹配 = 请勿运行，立即删除

## 📄 许可证

本项目采用 [MIT License](LICENSE)。

---

> ⚠️ 本工具调用 Windows `mklink` 命令，部分操作需要**管理员权限**。

## 🙏 致谢

本项目灵感来源于 [lWaterLite/MklinkGUI](https://github.com/lWaterLite/MklinkGUI)（MIT License），使用 Python + CustomTkinter 重写。
