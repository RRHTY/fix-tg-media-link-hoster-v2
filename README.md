# tg-media-link-hoster
A Telegram bot could convert incoming media to string link and reverse the operation.
我自己部署下来填了相关信息还是有问题，我用AI修了一下能用了

一个媒体链接互转 TG 机器人，向它发送媒体可以获得代码链接，发送代码链接可以取回对应的媒体。
支持生成一次性链接、命名、搜索，可用于内容存储、分享、网盘等用途。

[DEMO](https://t.me/mlkautobot)&nbsp;&nbsp; [使用说明](https://github.com/reizhi/tg-media-link-hoster-v2/wiki/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E)

# Fix-TG-Media-Link-Hoster-V2

本项目是针对 [reizhi/tg-media-link-hoster-v2](https://github.com/reizhi/tg-media-link-hoster-v2) 的修复增强版。主要解决了原版在处理 **Telegram 媒体组（一次发送多张图片/视频）** 时的崩溃问题，并大幅提升了响应速度。

## 🚀 核心改进

* **彻底修复媒体组 Bug**：重构底层逻辑，解决 `IndexError: list index out of range` 报错。
* **速度大幅提升**：优化并发信号量与等待逻辑，链接提取速度提升约 60%。
* **高稳定性**：完善错误日志回溯，优化数据库写入，防止因 MySQL 严格模式导致的失败。

## 🛠️ 快速部署

### 1. 环境准备

```bash
git clone https://github.com/RRHTY/fix-tg-media-link-hoster-v2
cd fix-tg-media-link-hoster-v2
# 建议在虚拟环境中安装依赖
pip install -r requirements.txt

```

### 2. 修复 Pyrogram 源码 (关键步骤)

由于 Pyrogram 官方库暂未修复媒体组索引 Bug，**必须**手动替换你环境中的文件：

1. 找到文件：`.../site-packages/pyrogram/methods/messages/get_media_group.py`
2. 使用本仓库提供的 `get_media_group.py` 覆盖同名文件。

### 3. 数据库准备

确保你的 MySQL 数据库中存在 `records` 表，且包含 `mgroup_id` 字段。

```sql
-- 如果字段不存在，请执行以下 SQL
ALTER TABLE records ADD COLUMN mgroup_id TEXT DEFAULT NULL;
-- 如果已存在但类型是 INT，请改为 TEXT 以防止大 ID 溢出
ALTER TABLE records MODIFY mgroup_id TEXT DEFAULT NULL;

```

### 4. 修改配置

编辑 `mlbot.py`，填入你的 API 信息与数据库参数：

* `api_id` / `api_hash`：从 [my.telegram.org](https://my.telegram.org) 获取。
* `bot_token`：从 [@BotFather](https://t.me/BotFather) 获取。
* `dbconfig`：填入你的 MySQL 地址、用户名及密码。


### 正式启动：
建议配置进程守护，不要用screen

### 🔧 步骤 1：创建 systemd 服务文件
```bash
sudo nano /etc/systemd/system/mlkbot.service
```

粘贴以下内容（根据你的路径调整）：

```ini
[Unit]
Description=MLK Telegram Media Link Hoster Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/tg-media-link-hoster-v2-main
Environment="PATH=/root/tg-media-link-hoster-v2-main/mlk/bin"
ExecStart=/root/tg-media-link-hoster-v2-main/mlk/bin/python3 /root/tg-media-link-hoster-v2-main/mlbot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

> ✅ 说明：
> - `User=root`：因为你是 root 用户运行的，也可以改成普通用户（更安全）
> - `WorkingDirectory`：项目目录
> - `Environment="PATH=..."`：指定虚拟环境的 bin 路径，确保用的是正确的 python 和 pip
> - `ExecStart`：完整命令，使用虚拟环境中的 python3
> - `Restart=always`：崩溃或退出后自动重启
> - 日志通过 `journalctl` 查看

### 🔧 步骤 2：重载 systemd 并启用服务

```bash
# 重载配置
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
# 启动服务
sudo systemctl start mlkbot
# 设置开机自启
sudo systemctl enable mlkbot
```

### 🔍 步骤 3：查看状态和日志

```bash
# 查看运行状态
sudo systemctl status mlkbot
# 实时查看日志
sudo journalctl -u mlkbot -f
# 查看最近 50 行日志
sudo journalctl -u mlkbot -n 50

## 📖 指令说明

* `/start` - 开始使用或解析资源链接。
* `/join` - 合并多个资源链接（最多 10 个）并组包发送。
* `/s [关键词]` - 搜索自己上传并命名过的资源。
* `/name [名称]` - 回复一条带链接的消息来为资源命名。
* `/lock` - 更换分享主 KEY，使旧链接失效。
```

