# Fix-TG-Media-Link-Hoster-V2

本项目是针对 [reizhi/tg-media-link-hoster-v2](https://github.com/reizhi/tg-media-link-hoster-v2) 的深度修复与性能增强版。

一个基于 Pyrogram 编写的 Telegram 机器人，实现媒体与代码链接互转，便于资源的储存、索引和分享。

### 🌟 本版本核心改进

* **完美支持媒体组**：重构底层逻辑，彻底解决原版处理媒体组（一次发送多张图片/视频）时的 `IndexError` 崩溃问题。
* **性能大幅提升**：并发上传任务数提升至 **5**，优化了防抖锁定逻辑，生成链接的速度快约 60%。
* **多账号联动优化**：修复了副账号 (`ml2bot`, `ml3bot`) 的协作报错，增强了多副本备份的可靠性。
* **日志回溯系统**：引入 `traceback` 记录，所有异步任务错误均可追溯，方便排查权限或网络问题。

---

## 🛠️ 准备工作

1. **服务器**：一台能够访问 Telegram 的服务器（推荐欧洲地区），内存不小于 1GB。
2. **账号与 Bot**：
* **主账号（账号1）**：用于申请 API ID、API Hash 及创建主 Bot。
* **TG Bot**：向 [@BotFather](https://t.me/botfather) 申请并获取 `bot_token`。
* **存储群组（群1）**：创建一个 Supergroup，将机器人加入并设为管理员。


3. **[可选] 备份账号**：额外准备 **账号2** 和 **账号3**，并分别创建 **群2** 和 **群3** 用于多副本负载均衡。
4. **API 凭证**：前往 [my.telegram.org](https://my.telegram.org) 获取 `api_id` 和 `api_hash`。

---

## ⚙️ 环境搭建

### 1. 基础环境

```bash
apt update && apt install python3 python3-pip python3-venv screen -y
mkdir mlbot && cd mlbot
python3 -m venv mlk
source mlk/bin/activate
# 使用仓库提供的 requirements.txt 快速安装依赖
pip3 install -r requirements.txt

```

### 2. 修复 Pyrogram 源码 (部署核心)

由于 Pyrogram 官方库暂未修复媒体组索引 Bug，**必须**手动替换你环境中的底层文件：

1. 找到文件：`find / -name "get_media_group.py"`（通常位于虚拟环境的 `pyrogram/methods/messages/` 目录下）。
2. 使用本仓库提供的 `get_media_group.py` 覆盖原文件。此修改通过动态匹配 `message_id` 彻底解决了原版教程中修改 `range` 依然报错的问题。

### 3. 数据库初始化

```sql
CREATE DATABASE mlkauto;
USE mlkauto;
-- 导入仓库中的 mlbot.sql 结构
SOURCE /path/to/mlbot.sql;
-- 必须确保 mgroup_id 字段存在且为 TEXT 类型，以兼容大 ID
ALTER TABLE records MODIFY mgroup_id TEXT DEFAULT NULL;

```

---

## 📝 配置参数

### 主 Bot 配置 (`mlbot.py`)

编辑文件填入以下参数：

* `api_id` / `api_hash`：你的 API 凭证。
* `bot_token`：从 @BotFather 获取的 Token。
* `groups`：填入群1 ID（如 `-1001145143333`）。
* `dbconfig`：填写你的 MySQL 数据库连接信息。

### 副账号备份配置 (`ml2bot.py` / `ml3bot.py`)

1. 确保 **账号1、2、3 及 Bot 都在群1中**。
2. `ml2bot.py`：配置账号2的 API 信息，`groups` 填入 `[群1_ID, 群2_ID]`。
3. `ml3bot.py`：配置账号3的 API 信息，`groups` 填入 `[群1_ID, 群2_ID, 群3_ID]`。
4. **首次登录**：分别手动执行 `python3 ml2bot.py` 和 `ml3bot.py`，根据提示输入手机号完成验证码登录。

---

## 🚀 运行机器人

使用 **Systemd** 进行进程守护，可在程序崩溃时自动重启。

---

## 🛠️ 使用 Systemd 守护主进程

### 1. 创建服务文件

使用 root 权限创建一个新的服务配置文件：

```bash
sudo nano /etc/systemd/system/mlkbot.service

```

### 2. 写入配置信息

将以下内容复制并粘贴到文件中。**注意修改路径和用户名**：

```ini
[Unit]
Description=MLK Telegram Media Link Hoster Bot
After=network.target mysql.service

[Service]
# 修改为你的实际运行用户，通常是 root 或你的用户名
User=root
Group=root

# 修改为你的项目根目录
WorkingDirectory=/root/mlbot

# 路径说明：
# 1. 必须指向虚拟环境中的 python 解释器
# 2. -u 参数确保日志实时刷新，方便 journalctl 查看
ExecStart=/root/mlbot/mlk/bin/python3 -u mlbot.py

# 崩溃后 5 秒自动重启
Restart=always
RestartSec=5

# 环境变量设置（可选）
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target

```

### 3. 激活并启动服务

执行以下命令使配置生效并启动机器人：

```bash
# 重新加载系统服务配置
sudo systemctl daemon-reload

# 设置开机自启
sudo systemctl enable mlkbot

# 立即启动服务
sudo systemctl start mlkbot

```

---

## 📊 常用管理命令

配置完成后，你可以通过以下指令轻松管理机器人进程：

| 操作 | 命令 |
| --- | --- |
| **查看实时日志** | `sudo journalctl -u mlkbot -f` |
| **查看运行状态** | `sudo systemctl status mlkbot` |
| **重启机器人** | `sudo systemctl restart mlkbot` |
| **停止机器人** | `sudo systemctl stop mlkbot` |



### （可选）副账号脚本

**首次必须手动执行**：分别手动执行 `python3 ml2bot.py` 和 `python3 ml3bot.py`，根据提示输入手机号完成验证码登录。

```bash
#!/bin/bash
source /root/mlbot/mlk/bin/activate
cd /root/mlbot
python3 ml2bot.py &
python3 ml3bot.py &

```

赋予执行权限：chmod +x mlhelper.sh

配置定时任务，1分钟执行一次
crontab -e
```bash
*/1 * * * * bash /root/mlbot/mlhelper.sh（改为你的文件地址）
```

## 📖 核心指令说明

* **生成链接**：直接向机器人发送媒体或媒体组，获取 `mkey` 和 `skey`。
* `/start [KEY]`：解析链接并取回对应的媒体资源。
* `/join [KEY1] [KEY2]`：将多个资源链接合并为一个新的媒体组返回。
* `/name [名称]`：(上传者) 回复资源链接进行命名，支持 `/s` 关键词搜索。
* `/lock`：(上传者) 更换主 KEY，使已发出的旧链接立即失效。

---
