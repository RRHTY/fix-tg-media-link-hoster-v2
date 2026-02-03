# Fix-TG-Media-Link-Hoster-V2

本项目是针对 [reizhi/tg-media-link-hoster-v2](https://github.com/reizhi/tg-media-link-hoster-v2) 的AI深度修复与性能增强版。

这是一个基于 Pyrogram 编写的 Telegram 机器人，实现媒体与代码链接互转，便于资源的储存、索引和分享。本版本重点引入了**高可用容灾架构**与**批量处理能力**。

### 🌟 本版本核心改进

* **🛡️ 容灾热切换 (High Availability)**：
* 引入 `desta` (主), `destb` (备1), `destc` (备2) 多副本存储架构。
* **智能取回逻辑**：当主存储群组 (Group A) 的消息被删除或机器人无法访问时，系统会自动无缝切换至备份群组 (Group B/C) 取回资源，确保分享链接永久有效。


* **🚀 批量处理模式 (Batch Mode)**：
* 新增 `/start_batch` 和 `/end_batch` 指令。
* 支持一次性转发数百条消息或多个文件夹，机器人会静默处理并打包生成一个**文件夹链接**，彻底告别单条刷屏。


* **🧩 完美支持媒体组**：
* 重构底层逻辑，彻底解决原版处理媒体组（一次发送多张图片/视频）时的 `IndexError` 崩溃问题。


* **⚡ 性能大幅提升**：
* 引入 **MySQL 连接池 (Pooling)**，在高并发下数据库连接更稳定。
* 新增 **防刷屏缓冲区 (Debounce Buffer)**：非批量模式下瞬间转发大量文件，机器人会智能拦截并提示使用批量模式，防止 API 被限制。


* **🤖 多账号联动优化**：
* 修复了副账号 (`ml2bot`, `ml3bot`) 的协作报错，实现了主从机器人的资源自动同步。



---

## 🛠️ 准备工作

1. **服务器**：一台能够访问 Telegram 的服务器（推荐欧洲地区），内存不小于 1GB。
2. **账号与 Bot**：
* **主账号**：用于申请 API ID、API Hash。
* **Bot Token**：向 [@BotFather](https://t.me/botfather) 申请。
* **存储群组**：需准备 **3个** 频道/群组（建议私密**超级群**，私密群公开再私有即可转换为私密超级群）：
* `GROUPS[0]`：主存储群（主 Bot 写入）。
* `GROUPS[1]`：备份群 B（副账号 1 同步）。
* `GROUPS[2]`：备份群 C（副账号 2 同步）。


* **注意**：主 Bot 和所有副账号必须加入以上 **所有** 群组，并拥有发送/读取消息的权限。


3. **MySQL 数据库**：
* 本项目依赖 MySQL 存储索引，需提前安装并创建数据库。



---

## ⚙️ 环境搭建与部署

### 1. 基础环境

```bash
# 安装系统依赖 (Debian/Ubuntu)
apt update && apt install python3 python3-pip python3-venv git mysql-server -y

# 克隆仓库
git clone https://github.com/RRHTY/fix-tg-media-link-hoster-v2
cd fix-tg-media-link-hoster-v2

# 创建并激活虚拟环境
python3 -m venv mlk
source mlk/bin/activate

# 安装项目依赖
pip3 install -r requirements.txt

```

### 2. 数据库配置

请登录 MySQL 并执行以下 SQL 语句以创建必要的表结构（适配本版本的容灾字段）：

```sql
CREATE DATABASE mlkauto CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE mlkauto;

CREATE TABLE `records` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `mlk` varchar(48) NOT NULL COMMENT '资源索引Hash',
  `mkey` varchar(8) NOT NULL COMMENT '主Key',
  `skey` varchar(8) NOT NULL COMMENT '一次性Key',
  `owner` bigint(20) NOT NULL COMMENT '上传者ID',
  `mgroup_id` varchar(32) DEFAULT NULL COMMENT '媒体组ID',
  `pack_id` varchar(32) DEFAULT NULL COMMENT '文件夹包ID',
  `desta` bigint(20) DEFAULT NULL COMMENT '主群消息ID',
  `destb` bigint(20) DEFAULT NULL COMMENT '备份群B消息ID',
  `destc` bigint(20) DEFAULT NULL COMMENT '备份群C消息ID',
  `name` varchar(64) DEFAULT NULL COMMENT '资源别名',
  `views` int(11) DEFAULT '0' COMMENT '浏览次数',
  `exp` datetime DEFAULT NULL COMMENT '过期时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `mlk` (`mlk`),
  KEY `owner` (`owner`),
  KEY `pack_id` (`pack_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

```

### 3. 配置文件修改

编辑 `mlbot.py`, `ml2bot.py`, `ml3bot.py`，修改顶部的配置区域：

```python
# --- 核心配置区 ---
API_ID = 12345678                  # 你的 API ID
API_HASH = "your_api_hash"         # 你的 API HASH
BOT_TOKEN = "123456:ABC-DEF..."    # 主 Bot Token

# 数据库配置
DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",                # 数据库用户名
    "password": "your_password",   # 数据库密码
    "database": "mlkauto"
}

# 存储群组 ID 列表 [主群, 备份B, 备份C]
# 请确保 ID 填写正确且 Bot 已入群
GROUPS = [-1001111111111, -1002222222222, -1003333333333]

```

### 4. 修复 Pyrogram 源码 (必须步骤)

由于 Pyrogram 官方库对 `get_media_group` 的处理存在已知 Bug，会导致部分媒体组获取失败。
请找到虚拟环境中的 `get_media_group.py` 文件：

```bash
# 查找文件路径
find mlk/ -name "get_media_group.py"
# 通常位于 mlk/lib/python3.x/site-packages/pyrogram/methods/messages/get_media_group.py

```

**修改方法**：
打开该文件，找到 `get_chunk` 或循环获取消息的部分，确保它能够正确处理非连续的消息 ID。或者直接使用本项目提供的 `patched/get_media_group.py` 覆盖（如果有提供），或参考社区 Issue 进行修复。

---

## 🚀 运行机器人

建议使用 `systemd` 或 `screen` 后台运行。

1. **启动主程序** (负责交互、存储到主群、容灾取回)：
```bash
python3 mlbot.py

```


2. **启动备份同步程序** (负责将资源同步到备份群)：
* 需配置额外的 UserBot Session（第一次运行需登录）


```bash
python3 ml2bot.py  # 负责同步到 destb
python3 ml3bot.py  # 负责同步到 destc

```



---

## 📖 使用指南

### 基础指令

* `/start` - 唤醒机器人或查看帮助。
* `/help` - 查看详细指令说明。
* `直接发送文件/视频/图片` - 机器人会返回资源的分享链接（单条模式）。

### ⚡ 批量模式 (推荐)

当需要上传大量文件时，请务必使用此模式，避免触发 TG 限制。

1. 发送 `/start_batch` 开启批量模式。
2. **转发** 或 **发送** 多条消息、媒体组给机器人（此时机器人会静默接收）。
3. 发送 `/end_batch` 结束。
4. 机器人将生成一个**文件夹链接** (`pack_xxxx`)，点击即可翻页查看所有资源。

### 🔍 搜索与管理

* `/name [资源名]` - 回复一条资源链接消息，给它起个别名。
* `/s [关键词]` - 搜索你自己命名的资源。
* `/lock` - 回复某条资源，强制轮换主 Key（旧链接失效，生成新链接）。
* `/top` - 查看你自己被访问次数最多的资源。

### 🧩 组包功能

* `/join [链接1] [链接2]...` - 将多个已生成的资源链接合并为一个媒体组发送。

---

## ⚠️ 注意事项

1. **权限检查**：如果机器人提示 `ChatWriteForbidden` 或 `The message doesn't belong to a media group`，请首先检查主 Bot 和副账号是否都在所有备份群组中，且未被禁言。
2. **容灾逻辑**：容灾是自动触发的。只有当主群 (`GROUPS[0]`) 读取失败时，机器人均才会尝试读取 `GROUPS[1]` 或 `GROUPS[2]`。
3. **防刷屏**：在非批量模式下，请勿瞬间转发超过 5 条消息，否则机器人会拒绝处理并提示使用批量模式。

---

## 🤝 致谢

* 原作者: [reizhi](https://github.com/reizhi)
* [Gemini Pro](https://gemini.google.com)
