# tg-media-link-hoster
A Telegram bot could convert incoming media to string link and reverse the operation.
我自己部署下来填了相关信息还是有问题，我用AI修了一下能用了

一个媒体链接互转 TG 机器人，向它发送媒体可以获得代码链接，发送代码链接可以取回对应的媒体。
支持生成一次性链接、命名、搜索，可用于内容存储、分享、网盘等用途。

[DEMO](https://t.me/mlkautobot)&nbsp;&nbsp; [使用说明](https://github.com/reizhi/tg-media-link-hoster-v2/wiki/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E)
简单来说部署需要这几步
### 前置：
1. 至少1个账号 至多3个账号，每个账号开一个超级群（创建后转公开群再转回私有即可），超级群的id开头应当是 -100。
2. 如果为了安全，可以再开一个号创建机器人，获得机器人token
3. 确保机器人和几个账号在各个群都加入了
4. 申请一个api_id 及 api_hash ：https://my.telegram.org/apps ，这个申请有点看运气、ip、申请的账号手机号和ip要一致。apiid只要有一个就可以，也不必是前面的三个账号申请的。


### 安装：
1. 下载仓库到服务器并放到一个文件夹里
3. 安装python虚拟环境（后面操作可都在虚拟环境中进行）
4. 使用mysql创建一个叫 mlkbot 的数据库，导入仓库sql文件
5. 配置每个mlbot文件，填写机器人、apiid、数据库信息、mlbot.py的下面机器人链接更改2处
6. 安装各个依赖（我都安装的最新版）
8. 使用screen测试 mlbot.py 能否正常启动，机器人有无响应，正常后，停止运行


可添加更多账号
9. 配置ml2bot.py中appid和数据库
10. 添加脚本并设置定时任务（1分钟一次）

### 正式启动：
建议配置进程守护，不要用screen，下面是AI写的

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
```

