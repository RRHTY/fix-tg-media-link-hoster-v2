import asyncio
import uvloop
import traceback
import re
import random
import time
import hashlib
import uuid
import math
from datetime import datetime, timedelta
from sys import stderr, stdout
from threading import Timer

# Pyrogram Imports
from pyrogram import Client, filters
from pyrogram.enums import MessageMediaType, ChatType, ParseMode
from pyrogram.errors import FileReferenceExpired, FloodWait, AuthBytesInvalid
from pyrogram.types import (
    InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument,
    ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)
from pyrogram.client import Cache

# Database Imports
import mysql.connector
from mysql.connector import pooling

# --- 初始化异步循环 ---
uvloop.install()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# ==============================================================================
#                               配置区域 (Configuration)
# ==============================================================================

# Telegram API 配置
API_ID = 
API_HASH = ""
BOT_TOKEN = ""

# 机器人信息配置
BOT_USERNAME = "" 
BOT_LINK_PREFIX = f"https://t.me/{BOT_USERNAME}?start="
# 备用BOT暂时无用
SUB_BOT_LINK = "https://t.me/mlk3autobot?start="

# 数据库配置
DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "mlkauto",
    "password": "",
    "database": "mlkauto"
}

# 存储群组配置 (用于容灾备份)

GROUPS = [-100, {}, {}]

# 常量配置
BATCH_TIMEOUT = 300      # 批量模式超时时间 (秒)
EXPIRATION_TIME = 1800   # 缓存过期时间

# ==============================================================================
#                               全局对象初始化
# ==============================================================================

app = Client(
    "mlkauto", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN, 
    max_concurrent_transmissions=1, 
    sleep_threshold=60
)
app.message_cache = Cache(1000000)

# 数据库连接池
connection_pool = pooling.MySQLConnectionPool(pool_name="mypool", pool_size=5, **DB_CONFIG)

# 全局状态缓存
batch_active_users = {}      # 批量模式用户状态 {user_id: {"msgs": [], "timer": task}}
page_cooldown = {}           # 翻页冷却 {user_id: timestamp}
decode_users = {}            # 解析频率限制
processed_media_groups = {}  # 已处理的媒体组

# --- 非批量模式的防刷缓冲区 ---
# 结构: {user_id: {"msgs": [msg_objects], "timer": asyncio.Task}}
pending_process_users = {}

# 并发控制信号量
ret_task_count = 0
stor_task_count = 0
stor_sem = asyncio.Semaphore(5)  # 存储任务并发锁
ret_sem = asyncio.Semaphore(2)   # 取回任务并发锁

# 支持的下载类型
dl_types = [MessageMediaType.PHOTO, MessageMediaType.VIDEO, MessageMediaType.AUDIO, MessageMediaType.DOCUMENT]

# ==============================================================================
#                               数据库操作层 (Database Layer)
# ==============================================================================

def get_connection():
    """获取数据库连接"""
    return connection_pool.get_connection()

def write_rec(mlk, mkey, skey, owner, desta, mgroup_id="", pack_id=None):
    """写入资源记录"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        val_mgroup = mgroup_id if mgroup_id else None
        sql = 'INSERT INTO records (mlk, mkey, skey, owner, mgroup_id, desta, pack_id ) VALUES (%s, %s, %s, %s, %s, %s, %s)'
        cursor.execute(sql, (mlk, mkey, skey, owner, val_mgroup, desta, pack_id))
        conn.commit()
    except Exception as e:
        print(f"写入数据库失败: {e}")
        print(traceback.format_exc())
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def read_rec(mlk):
    """读取资源记录并增加访问计数"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'SELECT * FROM records WHERE mlk = %s'
        cursor.execute(sql, (mlk,))
        result = cursor.fetchone()
        if result:
            cursor.execute('UPDATE records SET views = views + 1 WHERE mlk = %s', (mlk,))
            conn.commit()
        return result
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def get_pack_contents(pack_id):
    """获取文件夹内的所有资源"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'SELECT * FROM records WHERE pack_id = %s ORDER BY id ASC'
        cursor.execute(sql, (pack_id,))
        return cursor.fetchall()
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def rotate_mkey(mlk):
    """轮换主KEY (Lock功能)"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        mkey = str(uuid.uuid4()).split("-")[-1][0:8]
        cursor = conn.cursor(dictionary=True)
        sql = 'UPDATE records SET mkey = %s WHERE mlk = %s'
        cursor.execute(sql, (mkey, mlk))
        conn.commit()
        return mkey
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def rotate_skey(mlk):
    """轮换一次性KEY"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        skey = str(uuid.uuid4()).split("-")[-1][0:8]
        cursor = conn.cursor(dictionary=True)
        sql = 'UPDATE records SET skey = %s WHERE mlk = %s'
        cursor.execute(sql, (skey, mlk))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def set_name(mlk, name):
    """设置资源名称"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'UPDATE records SET name = %s WHERE mlk = %s'
        cursor.execute(sql, (name, mlk))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def search_names(owner, name):
    """搜索资源"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'SELECT * FROM records WHERE owner = %s AND name like %s ORDER BY ID DESC LIMIT 12'
        cursor.execute(sql, (owner, '%' + name + '%'))
        result = cursor.fetchall()
        return result if result and len(result) > 0 else False
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def top_views(owner):
    """获取访问量排行"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'SELECT * FROM records WHERE owner = %s ORDER BY views DESC LIMIT 5'
        cursor.execute(sql, (owner,))
        result = cursor.fetchall()
        return result if result and len(result) > 0 else False
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def set_expire(mlk, exp_time):
    """设置过期时间"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'UPDATE records SET exp = %s WHERE mlk = %s'
        cursor.execute(sql, (exp_time, mlk))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# ==============================================================================
#                               工具函数 (Utils)
# ==============================================================================

def cleanup_processed_media_groups():
    current_time = time.time()
    expired_keys = [key for key, timestamp in processed_media_groups.items() if current_time - timestamp > EXPIRATION_TIME]
    for key in expired_keys:
        del processed_media_groups[key]

def decode_rate_con(uid, p=0):
    """解析频率限制控制器"""
    if not uid in decode_users:
        decode_users[uid] = time.time()
    if p > 0:
        decode_users[uid] = decode_users[uid] + p
        return
    expired_keys = [key for key, timestamp in decode_users.items() if time.time() - timestamp > 180]
    for key in expired_keys:
        del decode_users[key]
    if (uid in decode_users):
        if(time.time() - decode_users[uid] < 0):
            return (decode_users[uid] - time.time())
    cooldown_time = max(8, 8 + 1.33 * min(4, ret_task_count))
    decode_users[uid] = time.time() + cooldown_time
    return 0

def mediatotype(obj):
    """媒体类型转换字符串"""
    if obj == MessageMediaType.PHOTO:
        return "photo"
    if obj == MessageMediaType.VIDEO:
        return "video"
    if obj == MessageMediaType.AUDIO:
        return "audio"
    if obj == MessageMediaType.DOCUMENT:
        return "document"
    return "unknown"

async def batch_timeout_monitor(user_id, chat_id):
    """批量模式超时监控"""
    await asyncio.sleep(BATCH_TIMEOUT)
    if user_id in batch_active_users:
        await app.send_message(chat_id, "⚠️ 批量模式已达到5分钟，正在自动结算...")
        await end_batch_logic(user_id, chat_id)

# ==============================================================================
#                               核心业务逻辑 (Core Logic)
# ==============================================================================

async def media_to_link(mlk, mkey, skey, chat_id, msg_id, owner, mgroup_id, stor_sem):
    """将接收到的媒体转存并生成链接"""
    global stor_task_count
    try:
        async with stor_sem:
            retry = 0
            dup_message = None
            while retry <= 3:
                try:
                    await asyncio.sleep(random.randint(3, 15) / 10)
                    if not mgroup_id:
                        dup_message = await app.copy_message(
                            chat_id=GROUPS[0], 
                            from_chat_id=chat_id, 
                            message_id=msg_id
                        )
                    else:
                        messages = await app.get_media_group(chat_id, msg_id)
                        ids = [m.id for m in messages]
                        res = await app.forward_messages(
                            chat_id=GROUPS[0],
                            from_chat_id=chat_id,
                            message_ids=ids
                        )
                        dup_message = res[0]
                    
                    if dup_message and (getattr(dup_message, "id", None) or getattr(dup_message, "message_id", None)):
                        break 
                        
                except Exception as e:
                    print(f"复制尝试 {retry} 失败: {e}\n{traceback.format_exc()}")
                    await asyncio.sleep(2)
                
                retry += 1

            if not dup_message:
                return
            write_rec(mlk, mkey, skey, owner, dup_message.id, mgroup_id)

            keyout = (
                '<点击链接直接复制，无需手选>\n\n'
                f'<b>主分享KEY</b>: `{BOT_LINK_PREFIX}{mlk}-{mkey}`\n'
                f'<b>一次性KEY</b>: `{BOT_LINK_PREFIX}{mlk}-{skey}`\n\n'
                '主分享KEY可重复使用，一次性KEY在获取一次后会失效，如果你是资源上传者，'
                '可以向机器人发送主分享KEY来获取最新可用的一次性KEY\n\n'
                '🔽链接默认不过期，如需限时有效下方可设置'
            )
            
            acts = InlineKeyboardMarkup([[
                InlineKeyboardButton("1H过期", callback_data=mlk + "?exp=1H"),
                InlineKeyboardButton("3H过期", callback_data=mlk + "?exp=3H"),
                InlineKeyboardButton("24H过期", callback_data=mlk + "?exp=24H"),
                InlineKeyboardButton("不过期", callback_data=mlk + "?exp=NULL"),
            ]])

            try:
                await app.send_message(chat_id, text=keyout, reply_to_message_id=msg_id, reply_markup=acts)
            except Exception as e:
                print(f"发送链接消息失败: {e}")

    except Exception as e:
        print(f"media_to_link 发生严重错误: {e}")
    finally:
        await asyncio.sleep(random.randint(10, 35) / 10)
        stor_task_count = max(0, stor_task_count - 1)

async def process_pending_media(user_id, chat_id):
    """处理缓冲区的媒体消息"""
    if user_id not in pending_process_users: return
    
    data = pending_process_users.pop(user_id)
    msgs = data["msgs"]
    
    # 策略：如果瞬间发的数量超过 5 条，强制提示用户使用批量模式，防止刷屏
    # 如果少于等于 5 条，则正常逐个处理
    if len(msgs) > 5:
        await app.send_message(
            chat_id, 
            f"⚠️ 检测到您瞬间发送了 {len(msgs)} 个文件。\n\n"
            "❌ **为了防止刷屏，本次请求已拦截。**\n"
            "✅ 请先发送 /start_batch 进入批量模式，然后再转发这些文件，最后发送 /end_batch 一次性打包。"
        )
        return

    # 正常数量，逐个处理
    for msg in msgs:
        # 为了避免瞬间并发爆炸，每处理一个稍微停顿一下
        await asyncio.sleep(0.5) 
        owner = user_id if msg.from_user else 0
        # 调用原有的 media_prep
        asyncio.create_task(media_prep(chat_id, msg.id, owner, msg.date))

async def media_prep(chat_id, msg_id, owner, msg_dt, mgroup_id=""):
    """媒体处理前置准备"""
    global stor_task_count
    if stor_task_count >= 5:
        try:
            await app.send_message(chat_id, text="[系统] 当前任务较多，已进入后台排队，请稍等片刻...")
        except Exception:
            pass

    stor_task_count += 1
    mlk_hash = hashlib.sha3_256()
    prep_key = f"{chat_id}{msg_id}{owner}{msg_dt}{uuid.uuid4()}"
    mlk_hash.update(prep_key.encode())
    mlk = mlk_hash.hexdigest()[0:48]
    mkey = str(uuid.uuid4()).split("-")[-1][0:8]
    skey = str(uuid.uuid4()).split("-")[-1][0:8]
    
    asyncio.create_task(
        media_to_link(mlk, mkey, skey, chat_id, msg_id, owner, mgroup_id, stor_sem)
    )

async def link_to_media(chat_id, msg_id, data_set, ret_sem):
    """
    [核心逻辑] 将链接转换为媒体发送给用户
    包含故障转移(Failover)逻辑：当主群组失效时，自动尝试从备份群组获取。
    """
    async with ret_sem:
        # 1. 严格构建来源列表，过滤无效ID
        raw_sources = []
        if data_set.get('desta'): raw_sources.append((GROUPS[0], data_set['desta']))
        if data_set.get('destb'): raw_sources.append((GROUPS[1], data_set['destb']))
        if data_set.get('destc'): raw_sources.append((GROUPS[2], data_set['destc']))
        
        sources = []
        for gid, mid in raw_sources:
            if mid and str(mid).isdigit():
                sources.append((int(gid), int(mid)))

        if not sources:
            print(f"[Critical] 资源 {data_set.get('mlk')} 数据库内无有效 ID")
            return

        mgroup_id = data_set.get('mgroup_id')
        success = False
        
        # 2. 迭代尝试：Failover 逻辑核心
        for from_chat_id, target_mid in sources:
            try:
                print(f"[Debug] 正在尝试从群组 {from_chat_id} 取回消息 {target_mid}...")
                
                if mgroup_id:
                    msgs = await app.copy_media_group(
                        chat_id=chat_id, 
                        from_chat_id=from_chat_id, 
                        message_id=target_mid, 
                        reply_to_message_id=msg_id
                    )
                    # 检查媒体组是否为空
                    if not msgs:
                        raise ValueError("Media group is empty")
                else:
                    msg = await app.copy_message(
                        chat_id=chat_id, 
                        from_chat_id=from_chat_id, 
                        message_id=target_mid,
                        reply_to_message_id=msg_id
                    )
                    # 检查返回的消息是否有效 (防止Ghost Message)
                    if not msg or getattr(msg, "empty", False):
                        raise ValueError("Copied message is empty (Deleted or Service Msg)")
                
                success = True
                print(f"[Success] 取回成功！源群组: {from_chat_id}, 消息ID: {target_mid}")
                break  # 成功获取，跳出循环
                
            except Exception as e:
                # 捕获异常，打印日志并进入下一次循环尝试下一个源
                print(f"[Warn] 从群组 {from_chat_id} 获取 ID:{target_mid} 失败: {e} -> 切换下一节点")
                continue 
        
        if not success:
            try:
                await app.send_message(chat_id, "❌ 该资源的所有存储节点（主库及备份）均已失效。")
            except: pass

        await asyncio.sleep(1 + random.randint(28, 35) / 10)
        global ret_task_count
        ret_task_count = max(0, ret_task_count - 1)

async def link_prep(chat_id, msg_id, from_id, result, join_op=0):
    """解析 KEY 并分配任务"""
    join_list = []
    global ret_task_count
    for m in result:
        mkey = m[0:48]
        rkey = m[49:65]
        data_set = read_rec(mkey) # 获取完整数据库行
        ret_task = []
        if data_set:
            # 过期检查
            if data_set['exp'] and time.time() > data_set['exp'].timestamp():
                try: await app.send_message(chat_id, text="资源已过期")
                except: pass
                return

            # 校验 KEY 类型 (Main or One-time)
            if rkey == data_set["mkey"] or rkey == data_set["skey"]:
                if rkey == data_set["skey"]:
                    rotate_skey(mkey)
                
                if join_op:
                    join_list.append(data_set['desta'])
                    continue
                
                # 创建取回任务，传入完整的 data_set 以便容灾
                task = asyncio.create_task(link_to_media(chat_id, msg_id, data_set, ret_sem))
                ret_task.append(task)
                
                if ret_task_count >= 5:
                    try: await app.send_message(chat_id, text="正在排队处理中...")
                    except: return
                
                ret_task_count += 1
                await asyncio.gather(*ret_task)
                
                # 如果是资源拥有者，显示一次性 KEY
                if from_id == data_set['owner']:
                    skey_disp = f'本资源当前一次性KEY: `{BOT_LINK_PREFIX}{data_set["mlk"]}-{data_set["skey"]}`'
                    try: await app.send_message(chat_id, text=skey_disp, reply_to_message_id=msg_id)
                    except: pass
                continue

        else:
            try:
                await app.send_message(chat_id, text="密钥不正确，一分钟后可以再试", reply_to_message_id=msg_id)
            except Exception: pass
            decode_rate_con(from_id, p=48)
            
    return join_list

async def send_pack_page(chat_id, pack_id, page=1):
    """发送文件夹内容（带翻页）- 包含完整容灾逻辑"""
    contents = get_pack_contents(pack_id)
    if not contents: 
        await app.send_message(chat_id, "❌ 文件夹不存在或已被清空")
        return

    total_items = len(contents)
    items_per_page = 1 
    total_pages = math.ceil(total_items / items_per_page)
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_page_items = contents[start_idx:end_idx]

    # 统计信息 (统计依然优先主群，但这不影响发送)
    video_count = 0
    photo_count = 0
    file_count = 0

    for item in contents:
        try:
            msg = await app.get_messages(GROUPS[0], item['desta'])
            if item['mgroup_id']:
                mg_msgs = await app.get_media_group(GROUPS[0], item['desta'])
                for m in mg_msgs:
                    if m.video: video_count += 1
                    elif m.photo: photo_count += 1
                    else: file_count += 1
            else:
                if msg.video: video_count += 1
                elif msg.photo: photo_count += 1
                else: file_count += 1
        except Exception:
            continue

    # 发送媒体 (这里修改为包含 Failover 逻辑)
    for item in current_page_items:
        # 1. 构建来源列表
        raw_sources = []
        if item.get('desta'): raw_sources.append((GROUPS[0], item['desta']))
        if item.get('destb'): raw_sources.append((GROUPS[1], item['destb']))
        if item.get('destc'): raw_sources.append((GROUPS[2], item['destc']))
        
        sources = []
        for gid, mid in raw_sources:
            if mid and str(mid).isdigit():
                sources.append((int(gid), int(mid)))
        
        item_success = False
        
        # 2. 尝试发送
        for from_chat_id, target_mid in sources:
            try:
                if item['mgroup_id']:
                    msgs = await app.copy_media_group(chat_id, from_chat_id, target_mid)
                    if not msgs: raise ValueError("Empty media group returned")
                else:
                    msg = await app.copy_message(chat_id, from_chat_id, target_mid)
                    if not msg or getattr(msg, "empty", False): raise ValueError("Empty message returned")
                item_success = True
                break # 成功发送，处理下一个 item
            except Exception as e:
                print(f"[Warn] Batch send failed from {from_chat_id} (ID: {target_mid}): {e}")
                continue # 尝试下一个 source
        
        if not item_success:
             print(f"[Error] Item {item.get('mlk')} failed to send from all sources.")

    # 构建按钮
    buttons = []
    if total_pages > 1:
        for i in range(1, total_pages + 1):
            label = f"⚪{i}" if i == page else str(i)
            buttons.append(InlineKeyboardButton(label, callback_data=f"page|{pack_id}|{i}"))
    
    kb_rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    kb = InlineKeyboardMarkup(kb_rows) if buttons else None
    
    status_text = (
        f"📂 **文件夹详情**\n"
        f"📊 统计: 共 {total_items} 组内容\n"
        f"📹 视频: {video_count} | 🖼 图片: {photo_count} | 📄 文件: {file_count}\n"
        f"📑 当前第 {page}/{total_pages} 页\n"
        f"⏳ 翻页冷却: 10秒"
    )
    await app.send_message(chat_id, status_text, reply_markup=kb)

async def end_batch_logic(user_id, chat_id):
    """批量模式结算逻辑"""
    if user_id not in batch_active_users: return
    data = batch_active_users.pop(user_id)
    data["timer"].cancel()
    
    if not data["msgs"]:
        await app.send_message(chat_id, "批量模式结束，未收到媒体。")
        return

    await app.send_message(chat_id, f"正在打包 {len(data['msgs'])} 个资源，并上传至存储库...")
    
    pack_id = hashlib.shake_128(str(uuid.uuid4()).encode()).hexdigest(4)
    first_mlk_link = ""
    processed_mgids = set()
    success_count = 0 

    for mid in data["msgs"]:
        try:
            msg = await app.get_messages(chat_id, mid)
            if not msg or not msg.media: continue

            mgroup_id, desta_id = "", 0
            if msg.media_group_id:
                if msg.media_group_id in processed_mgids: continue
                processed_mgids.add(msg.media_group_id)
                mg_msgs = await app.get_media_group(chat_id, mid)
                res = await app.forward_messages(GROUPS[0], chat_id, [m.id for m in mg_msgs])
                desta_id, mgroup_id = res[0].id, str(msg.media_group_id)
            else:
                res = await app.copy_message(GROUPS[0], chat_id, mid)
                desta_id = res.id

            mlk = hashlib.sha3_256(f"{desta_id}{uuid.uuid4()}".encode()).hexdigest()[0:48]
            mkey = str(uuid.uuid4()).split("-")[-1][0:8]
            skey = str(uuid.uuid4()).split("-")[-1][0:8]

            conn = connection_pool.get_connection()
            cursor = conn.cursor()
            sql = "INSERT INTO records (mlk, mkey, skey, owner, mgroup_id, desta, pack_id) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            cursor.execute(sql, (mlk, mkey, skey, user_id, mgroup_id if mgroup_id else None, desta_id, pack_id))
            conn.commit()
            cursor.close()
            conn.close()
            
            success_count += 1
            if not first_mlk_link:
                first_mlk_link = f"{BOT_LINK_PREFIX}pack_{pack_id}"
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Batch Error: {e}")
            continue

    if success_count > 0:
        await app.send_message(chat_id, f"✅ 批量打包成功！\n共计处理 {success_count} 组资源。\n文件夹提取链接：`{first_mlk_link}`")
    else:
        await app.send_message(chat_id, "❌ 批量处理失败。")

async def read_media(ids):
    """读取媒体信息用于组包"""
    media_cl = []
    if not ids: return
    for i in ids:
        try:
            msg = await app.get_messages(GROUPS[0], i)
            await asyncio.sleep(1.25)
        except FloodWait as e:
            await asyncio.sleep(e.value + 3)
        except Exception:
            await asyncio.sleep(1)
            msg = await app.get_messages(GROUPS[0], i)
        
        if msg.media_group_id:
            msgs = await app.get_media_group(GROUPS[0], i)
            for ix in msgs:
                type_str = mediatotype(ix.media)
                media_cl.append({"type": type_str, "file_id": getattr(ix, type_str).file_id, "thumb": ix.video.thumbs[0].file_id if type_str == "video" else ""})
        else:
            type_str = mediatotype(msg.media)
            media_cl.append({"type": type_str, "file_id": getattr(msg, type_str).file_id, "thumb": msg.video.thumbs[0].file_id if type_str == "video" else ""})
    return media_cl

async def join_process(file_list, chat_id, hint=False):
    """处理组包发送"""
    if len(file_list) <= 10:
        if len(file_list) == 1:
            if type(file_list[0]) == InputMediaPhoto:
                msg = await app.send_photo(chat_id, file_list[0].media)
            elif type(file_list[0]) == InputMediaVideo:
                msg = await app.send_video(chat_id, file_list[0].media, thumb=file_list[0].thumb)
            elif type(file_list[0]) == InputMediaAudio:
                msg = await app.send_audio(chat_id, file_list[0].media)
            elif type(file_list[0]) == InputMediaDocument:
                msg = await app.send_document(chat_id, file_list[0].media)
            await media_prep(chat_id, msg.id, 0, msg.date)
            return
        else:
            try:
                msg = await app.send_media_group(chat_id, file_list)
                await media_prep(chat_id, msg[0].id, 0, msg[0].date, str(msg[0].media_group_id))
            except Exception:
                await app.send_message(chat_id, text="暂不支持文档和图片进行组包")
            finally:
                return
    else:
        if not hint:
            try:
                await app.send_message(chat_id, text="媒体总数超过10个，将以10个一组返回，请耐心等待")
            except Exception:
                return
        msg = await app.send_media_group(chat_id, file_list[0:10])
        await asyncio.sleep(1.2)
        await media_prep(chat_id, msg[0].id, 0, msg[0].date, str(msg[0].media_group_id))
        await asyncio.sleep(2 + random.randint(15, 45) / 10)
        return await join_process(file_list[10:], chat_id, hint=True)

async def pre_command(message):
    """解析指令前的处理"""
    in_text = message.text
    result = re.findall(r'\w{48}-\w{8}', in_text)
    msg_id = message.id
    chat_id = message.chat.id
    from_id = message.from_user.id if message.from_user else 0
    
    if result and len(result) > 0:
        if decode_rate_con(from_id):
            cdt = math.ceil(decode_rate_con(from_id))
            try:
                if cdt < 20 and ret_task_count <= 4:
                    await app.send_message(chat_id=message.chat.id, text=f"资源将在{cdt}秒后返回，请勿重复点击")
                    decode_rate_con(from_id, 8)
                    await asyncio.sleep(cdt + ret_task_count * 0.33)
                else:
                    subbot_btn = InlineKeyboardMarkup([[
                        InlineKeyboardButton("发给副BOT处理", url=f"{SUB_BOT_LINK}{result[0]}")
                    ]])
                    await app.send_message(chat_id=message.chat.id, text=f"每{cdt}秒最多提交一次解析请求，请稍后再试", reply_markup=subbot_btn)
                    return
            except Exception as e:
                print(e)
        if len(result) > 3:
            try:
                await app.send_message(chat_id=message.chat.id, text="一次最多解析三个KEY，超出部分会被忽略")
            except Exception:
                return
            result = result[0:3]
        await link_prep(chat_id, msg_id, from_id, result)

# ==============================================================================
#                               BOT 事件处理器 (Event Handlers)
# ==============================================================================

@app.on_message(filters.command("start") & filters.private)
async def cmd_start(client, message):
    if len(message.command) == 2:
        param = message.command[1]
        # 处理文件夹链接
        if param.startswith("pack_"):
            pack_id = param.replace("pack_", "")
            await send_pack_page(message.chat.id, pack_id, 1)
            return
        # 单资源解析
        await pre_command(message)
        return
    welcome_text = '我是一个资源存储机器人，能够帮你把媒体资源转换为代码链接，便于分享和转发\n直接向我发送媒体开始使用，或者发送 /help 查看帮助'
    try:
        await app.send_message(message.from_user.id, welcome_text)
    except Exception:
        return

@app.on_message(filters.command("help") & filters.private)
async def cmd_help(client, message):
    help_message = f'''
向我发送媒体或媒体组，你将得到两个代码链接：<u>主分享KEY</u>和<u>一次性KEY</u>
链接格式均为：<pre>[48位资源索引]-[8位密钥]</pre> 主分享KEY和一次性KEY的资源索引相同，但密钥不同

🔖 一次性KEY在被获取后，其密钥会自动销毁，即仅能获取一次，主分享KEY可以重复被获取
如果你是资源上传者，可以向机器人发送主分享KEY来获取最新的一次性KEY
为避免爆破攻击，当资源索引正确但密钥错误时系统会给出提示，并进入一分钟的冷却时间

📒 资源上传者可以向任意一条带资源链接的消息回复 <pre>/name 资源名称</pre> 来对资源命名，该名称只有上传者可见，用于资源搜索。资源名称中切勿包含空格

🔎 资源上传者可以使用 <pre>/s 关键词</pre> 来搜索自己上传的、有主动命名过的资源，[举例] 关键词'数字'可以匹配'阿拉伯数字'，'大写数字捌'等，搜索结果最多返回最近12条，搜索冷却时间为12秒

🔑 对于同一用户，链接转媒体的冷却时间为12秒，每条消息最多提交三个链接进行解析，超出部分会被忽略

📦如需将多个媒体组包成一个，一次性发送过来，可以使用 <pre>/join 链接1 链接2 链接3</pre> 命令来操作，支持最多10个链接。举例：你分三次向机器人发送了2+1+3个媒体，使用组包功能可以将6个媒体集合成一条消息。TG允许一条消息包含最多10个媒体，如果组包后超过10个，会以每10个一组返回。

⛓️‍💥已经发出去的主KEY如需停止分享，上传者可以用 <pre> /lock </pre> 来回复带KEY的消息，或者向机器人发送 <pre> /lock 主分享链接 </pre> 更换主KEY。更换后会收到新的分享主KEY，曾经发出的主KEY无法再获取，但已获取过的资源不会被撤回。
'''
    try:
        await app.send_message(message.from_user.id, help_message)
    except Exception:
        return

@app.on_message(filters.command("join") & filters.private)
async def cmd_join(client, message):
    if decode_rate_con(message.from_user.id):
        try:
            await app.send_message(chat_id=message.chat.id, text="每30秒最多提交一次媒体组包请求，请稍后再试")
        except Exception:
            return
        return
    chat_id = message.chat.id
    result = re.findall(r'\w{48}-\w{8}', message.text)
    if not result:
        return
    if len(result) < 2 or len(result) > 10:
        try:
            await app.send_message(chat_id=message.chat.id, text="媒体组包功能需要2-10个分享链接")
        except Exception:
            return
    ids = await link_prep(chat_id, 0, 0, result, join_op=1)
    files = await read_media(ids)
    file_list = []
    for file in files:
        if file["type"] == "video":
            file_list.append(InputMediaVideo(file["file_id"], file["thumb"]))
        if file["type"] == "photo":
            file_list.append(InputMediaPhoto(file["file_id"]))
        if file["type"] == "audio":
            file_list.append(InputMediaAudio(file["file_id"]))
        if file["type"] == "document":
            file_list.append(InputMediaDocument(file["file_id"]))
    decode_rate_con(message.from_user.id, p=18)
    await join_process(file_list, chat_id)

@app.on_message(filters.command("s") & filters.private)
async def cmd_search(client, message):
    if (message.text.find(" ") > 0):
        search_word = message.text.split(" ")[-1]
        if decode_rate_con(message.from_user.id):
            try:
                await app.send_message(chat_id=message.chat.id, text="每12秒最多提交一次搜索请求，请稍后再试")
            except Exception:
                return
        data = search_names(message.from_user.id, search_word[0:32])
        if data:
            search_rr = '<b>搜索结果</b>：\n'
            n = 1
            for w in data:
                search_rr += f"{n}.{w['name']}: `{BOT_LINK_PREFIX}{w['mlk']}-{w['mkey']}`\n"
                n += 1
            await app.send_message(chat_id=message.chat.id, text=search_rr)
        else:
            await app.send_message(chat_id=message.chat.id, text="搜索无结果")

@app.on_message(filters.command("start_batch") & filters.private)
async def cmd_start_batch(client, message):
    uid = message.from_user.id
    if uid in batch_active_users:
        await message.reply("您已经在批量模式中了。")
        return
    
    batch_active_users[uid] = {
        "msgs": [],
        "timer": asyncio.create_task(batch_timeout_monitor(uid, message.chat.id))
    }
    await message.reply("🚀 **批量读取模式已开启**\n现在请发送或转发媒体给我，完成后发送 /end_batch 即可生成提取链接。")

@app.on_message(filters.command("end_batch") & filters.private)
async def cmd_end_batch(client, message):
    await end_batch_logic(message.from_user.id, message.chat.id)

@app.on_message(filters.reply & filters.private & filters.command("name"))
async def cmd_name(client, message):
    content = message.reply_to_message.text
    result = re.search(r'\w{48}-\w{8}', content)
    if not result: return
    result = result.group(0)
    
    if decode_rate_con(message.from_user.id):
        await app.send_message(chat_id=message.chat.id, text="每12秒最多提交一次命名请求，请稍后再试")
        return
        
    if (message.text.find(" ") > 0):
        new_name = message.text.split(" ")[-1]
        data_set = read_rec(result[0:48])
        if (data_set and data_set['owner'] == message.from_user.id):
            try:
                set_name(result[0:48], new_name[0:32])
                await app.send_message(message.chat.id, text="命名成功", reply_to_message_id=message.id)
            except Exception:
                await app.send_message(message.chat.id, text="命名失败")

@app.on_message(filters.private & filters.command("top"))
async def cmd_top(client, message):
    owner = message.from_user.id if message.from_user else 0
    if decode_rate_con(owner):
        await app.send_message(chat_id=message.chat.id, text="请稍后再试")
        return
    view_data = top_views(owner)
    if not view_data: return
    result = "以下是取回最多的资源：\n\n"
    for rec in view_data:
        result += f"[{rec['id']}]({BOT_LINK_PREFIX}{rec['mlk']}-{rec['mkey']}) > 取回:{rec['views']}\n"
    await app.send_message(message.chat.id, result)

@app.on_message(filters.private & filters.command("lock"))
async def cmd_lock(client, message):
    owner = message.from_user.id if message.from_user else 0
    if decode_rate_con(owner): return
    
    result = ""
    if message.reply_to_message:
        res = re.search(r'\w{48}-\w{8}', message.reply_to_message.text)
        result = res.group(0) if res else ""
    elif message.text.find(" ") > 0:
        res = re.search(r'\w{48}-\w{8}', message.text.split(" ")[-1])
        result = res.group(0) if res else ""
        
    if not result: return
    data_set = read_rec(result[0:48])
    if data_set and data_set['owner'] == owner:
        new_key = rotate_mkey(result[0:48])
        await app.send_message(message.chat.id, text=f"主KEY更换成功: `{BOT_LINK_PREFIX}{result[0:48]}-{new_key}`")

@app.on_message((filters.media | filters.media_group) & filters.private)
async def media_handler(client, message):
    uid = message.from_user.id
    
    # 1. 如果是批量模式，走原有逻辑
    if uid in batch_active_users:
        if message.media_group_id:
            if message.id not in batch_active_users[uid]["msgs"]:
                batch_active_users[uid]["msgs"].append(message.id)
        else:
            batch_active_users[uid]["msgs"].append(message.id)
        return 

    # 2. 非批量模式 -> 进入“防刷缓冲区”
    # 如果该用户还没有缓冲区，创建一个
    if uid not in pending_process_users:
        pending_process_users[uid] = {
            "msgs": [],
            "timer": None
        }

    # 取消旧的计时器（如果在跑的话）
    if pending_process_users[uid]["timer"]:
        pending_process_users[uid]["timer"].cancel()

    # 添加当前消息到缓冲列表
    pending_process_users[uid]["msgs"].append(message)

    # 重置计时器：如果 1 秒内没有新消息，就执行 process_pending_media
    # 这样用户连续转发 50 条时，只有最后一条发完 1 秒后才会触发处理
    pending_process_users[uid]["timer"] = asyncio.create_task(
        wait_and_process(uid, message.chat.id)
    )

async def wait_and_process(user_id, chat_id):
    """辅助延迟函数"""
    await asyncio.sleep(1.0) # 等待 1 秒
    await process_pending_media(user_id, chat_id)

@app.on_callback_query()
async def global_callback_handler(client, query):
    uid = query.from_user.id
    data = query.data

    # 1. 翻页逻辑
    if data.startswith("page|"):
        now = time.time()
        if now - page_cooldown.get(uid, 0) < 10:
            await query.answer("⏳ 翻页冷却中，请等待10秒。", show_alert=True)
            return
        page_cooldown[uid] = now
        _, pack_id, target_page = data.split("|")
        await query.answer("正在加载页面...")
        try: await query.message.delete()
        except: pass
        await send_pack_page(query.message.chat.id, pack_id, int(target_page))
        return

    # 2. 过期时间设置逻辑
    try:
        if "?" in data and "exp=" in data:
            mlk = data.split("?")[0]
            op = data.split("=")[-1]
            data_set = read_rec(mlk)
            if data_set and data_set['owner'] == uid:
                if op == "1H": exp = datetime.now() + timedelta(hours=1)
                elif op == "3H": exp = datetime.now() + timedelta(hours=3)
                elif op == "24H": exp = datetime.now() + timedelta(days=1)
                else: exp = datetime.now() + timedelta(weeks=300)
                set_expire(mlk, exp.strftime("%Y-%m-%d %H:%M:%S"))
                await app.send_message(query.message.chat.id, text=f"✅ 过期时间设定为：{exp}")
    except Exception as e:
        print(f"Callback error: {e}")

# ==============================================================================
#                               程序入口 (Main)
# ==============================================================================

async def main():
    async with app:
        await app.set_bot_commands([
            BotCommand("start", "开始使用"),
            BotCommand("start_batch", "开启批量生成模式"),
            BotCommand("end_batch", "结束批量并生成链接"),
            BotCommand("help", "详细功能说明"),
            BotCommand("s", "搜索资源"),
            BotCommand("join", "组包媒体"),
            BotCommand("top", "取回排行"),
            BotCommand("lock", "更换主KEY"),
            BotCommand("name", "资源命名"),
        ])
        print(f"[INFO] 机器人 @{BOT_USERNAME} 运行中...")
        await asyncio.Event().wait()

if __name__ == "__main__":
    app.run(main())