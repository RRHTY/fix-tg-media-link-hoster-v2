import asyncio
import uvloop
import traceback
uvloop.install()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
import re,random,time,hashlib,uuid
from datetime import datetime, timedelta
from sys import stderr, stdout
from threading import Timer

from pyrogram import Client
from pyrogram.enums import MessageMediaType,ChatType,ParseMode
from pyrogram.errors import FileReferenceExpired,FloodWait,AuthBytesInvalid
from pyrogram.types import InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from pyrogram.client import Cache
from pyrogram import filters
import mysql.connector
from mysql.connector import pooling
import math

# --- 核心配置区 ---
api_id = 
api_hash = ""
bot_token = ""

# 在此处修改您的机器人用户名，链接会自动适配
BOT_USERNAME = "bot" 
BOT_LINK_PREFIX = f"https://t.me/{BOT_USERNAME}?start="
# 副BOT链接配置（暂时无用）
SUB_BOT_LINK = "https://t.me/mlk3autobot?start="

# --- 批量与翻页状态记录 ---
batch_active_users = {}  # {user_id: {"msgs": [], "timer": task}}
page_cooldown = {}       # {user_id: last_click_timestamp}
BATCH_TIMEOUT = 300      # 批量模式5分钟超时

# ----------------

app = Client("mlkauto", api_id=api_id, api_hash=api_hash,bot_token=bot_token, max_concurrent_transmissions = 1, sleep_threshold = 60)

app.message_cache = Cache(1000000)
dl_types = [MessageMediaType.PHOTO, MessageMediaType.VIDEO, MessageMediaType.AUDIO, MessageMediaType.DOCUMENT]
groups = [-100,-100,-100]
use_record = {}

dbconfig = {
    "host": "127.0.0.1",
    "user": "mlkauto",
    "password": "YiNyPKmyJdhTrWAc",
    "database": "mlkauto"
}

connection_pool = pooling.MySQLConnectionPool(pool_name="mypool",pool_size=5,**dbconfig)

processed_media_groups = {}
expiration_time = 1800
decode_users = {}

ret_task_count = 0
stor_task_count = 0
stor_sem = asyncio.Semaphore(5)
ret_sem = asyncio.Semaphore(2)

def cleanup_processed_media_groups():
    current_time = time.time()
    expired_keys = [key for key, timestamp in processed_media_groups.items() if current_time - timestamp > expiration_time]
    for key in expired_keys:
        del processed_media_groups[key]

def decode_rate_con(uid, p = 0):
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
    cooldown_time = max(8, 8 + 1.33 * min(4,ret_task_count) )
    decode_users[uid] = time.time() + cooldown_time
    return 0

def write_rec(mlk, mkey, skey, owner, desta, mgroup_id = "", pack_id = None):
    try:
        conn = connection_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        val_mgroup = mgroup_id if mgroup_id else None
        sql = 'INSERT INTO records (mlk, mkey, skey, owner, mgroup_id, desta, pack_id ) VALUES (%s, %s, %s, %s, %s, %s, %s)'
        cursor.execute(sql, (mlk, mkey, skey, owner, val_mgroup, desta, pack_id))
        conn.commit()
    except Exception as e:
        print(f"写入数据库失败: {e}")
        print(traceback.format_exc())
    finally:
        cursor.close()
        conn.close()
    
def read_rec(mlk):
    try:
        conn = connection_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        # 仅读取资源本身，不再在此处处理 pack_id 的自动联发
        sql = 'SELECT * FROM records WHERE mlk = %s'
        cursor.execute(sql, (mlk,))
        result = cursor.fetchone()
        if result:
            cursor.execute('UPDATE records SET views = views + 1 WHERE mlk = %s', (mlk,))
            conn.commit()
        return result
    finally:
        cursor.close()
        conn.close()

def get_pack_contents(pack_id):
    """根据文件夹ID获取所有资源列表"""
    try:
        conn = connection_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'SELECT * FROM records WHERE pack_id = %s ORDER BY id ASC'
        cursor.execute(sql, (pack_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def rotate_mkey(mlk):
    try:
        conn = connection_pool.get_connection()
        mkey = str(uuid.uuid4()).split("-")[-1][0:8]
        cursor = conn.cursor(dictionary=True)
        sql = 'UPDATE records SET mkey = %s WHERE mlk = %s'
        cursor.execute(sql, (mkey, mlk))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()
        return mkey

def rotate_skey(mlk):
    try:
        conn = connection_pool.get_connection()
        skey = str(uuid.uuid4()).split("-")[-1][0:8]
        cursor = conn.cursor(dictionary=True)
        sql = 'UPDATE records SET skey = %s WHERE mlk = %s'
        cursor.execute(sql, (skey, mlk))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()

def set_name(mlk, name):
    try:
        conn = connection_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'UPDATE records SET name = %s WHERE mlk = %s'
        cursor.execute(sql, (name, mlk))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()

def search_names(owner, name):
    try:
        conn = connection_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'SELECT * FROM records WHERE owner = %s AND name like %s ORDER BY ID DESC LIMIT 12'
        cursor.execute(sql, (owner, '%' + name + '%'))
        result = cursor.fetchall()
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()
    if result and len(result) > 0:
        return result
    else:
        return False

def set_packid(mlkset, packid):
    try:
        conn = connection_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'UPDATE records SET pack_id = %s WHERE mlk = %s'
        for mlk in mlkset:
            cursor.execute(sql, (packid, mlk))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()

def read_pack(packid):
    try:
        conn = connection_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'SELECT * FROM records WHERE pack_id = %s'
        cursor.execute(sql, (packid,))
        result = cursor.fetchall()
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()
    if result and len(result) > 0:
        return result
    else:
        return False

def top_views(owner):
    try:
        conn = connection_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'SELECT * FROM records WHERE owner = %s ORDER BY views DESC LIMIT 5'
        cursor.execute(sql, (owner,))
        result = cursor.fetchall()
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()
    if result and len(result) > 0:
        return result
    else:
        return False

def set_expire(mlk, exp_time):
    try:
        conn = connection_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        sql = 'UPDATE records SET exp = %s WHERE mlk = %s'
        cursor.execute(sql, (exp_time, mlk))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()

def mediatotype(obj):
    if obj == MessageMediaType.PHOTO:
        return "photo"
    if obj == MessageMediaType.VIDEO:
        return "video"
    if obj == MessageMediaType.AUDIO:
        return "audio"
    if obj == MessageMediaType.DOCUMENT:
        return "document"

async def media_to_link(mlk, mkey, skey, chat_id, msg_id, owner, mgroup_id, stor_sem):
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
                            chat_id=groups[0], 
                            from_chat_id=chat_id, 
                            message_id=msg_id
                        )
                    else:
                        messages = await app.get_media_group(chat_id, msg_id)
                        ids = [m.id for m in messages]
                        res = await app.forward_messages(
                            chat_id=groups[0],
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

async def media_prep(chat_id, msg_id, owner, msg_dt, mgroup_id = ""):
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

async def link_to_media(chat_id, msg_id, desta, mgroup_id, ret_sem):
    async with ret_sem:
        if (mgroup_id):
            try:
                await app.copy_media_group(chat_id, from_chat_id = groups[0], message_id = desta, reply_to_message_id = msg_id)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await app.copy_media_group(chat_id, from_chat_id = groups[0], message_id = desta, reply_to_message_id = msg_id)
            except Exception as e:
                print(e)
        else:
            try:
                await app.copy_message(chat_id, from_chat_id = groups[0], message_id = desta)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await app.copy_message(chat_id, from_chat_id = groups[0], message_id = desta)
            except Exception as e:
                print(e)
        await asyncio.sleep(1 + random.randint(28,35) / 10)
        global ret_task_count
        ret_task_count -= 1 if ret_task_count > 0 else 0

async def link_prep(chat_id, msg_id, from_id, result, join_op = 0):
    join_list = []
    global ret_task_count
    for m in result:
        mkey = m[0:48]
        rkey = m[49:65]
        data_set = read_rec(mkey)
        ret_task = []
        if data_set:
            if data_set['exp'] and time.time() > data_set['exp'].timestamp():
                try:
                    await app.send_message(chat_id, text = "资源已过期")
                except Exception:
                    pass
                return
            desta = data_set['desta']
            mgroup_id = data_set['mgroup_id']
            if rkey == data_set["mkey"]:
                if join_op:
                    join_list.append(desta)
                    continue
                task = asyncio.create_task(link_to_media(chat_id, msg_id, desta, mgroup_id, ret_sem))
                ret_task.append(task)
                if ret_task_count >= 5:
                    try:
                        await app.send_message(chat_id, text =  "正在排队处理中，请稍等几秒，不要重复点击")
                    except Exception:
                        return
                ret_task_count += 1
                await asyncio.gather(*ret_task)
                if from_id == data_set['owner']:
                    skey_disp = f'本资源当前一次性KEY: `{BOT_LINK_PREFIX}{data_set["mlk"]}-{data_set["skey"]}`'
                    try:
                        await app.send_message(chat_id, text = skey_disp, reply_to_message_id = msg_id)
                    except Exception:
                        return
                continue
            if rkey == data_set["skey"]:
                rotate_skey(mkey)
                task = asyncio.create_task(link_to_media(chat_id, msg_id, desta, mgroup_id, ret_sem))
                ret_task.append(task)
                if ret_task_count >= 5:
                    try:
                        await app.send_message(chat_id, text =  "正在排队处理中，请稍等几秒，不要重复点击")
                    except Exception:
                        return
                ret_task_count += 1
                await asyncio.gather(*ret_task)
                try:
                    await app.send_message(chat_id, text = "当前使用的是一次性KEY，该KEY已自动销毁，无法再用")
                except Exception:
                    return
                continue
            if rkey != data_set["mkey"] and rkey != data_set["skey"]:
                try:
                    await app.send_message(chat_id, text = "资源索引有效，但密钥不正确，一分钟后可以再试", reply_to_message_id = msg_id)
                except Exception:
                    return
            decode_rate_con(from_id, p = 48)
    return join_list

async def send_pack_page(chat_id, pack_id, page=1):
    contents = get_pack_contents(pack_id)
    if not contents: 
        await app.send_message(chat_id, "❌ 文件夹不存在或已被清空")
        return

    total_items = len(contents)
    items_per_page = 1  # 每一页只展示数据库中的一组记录
    total_pages = math.ceil(total_items / items_per_page)
    
    # 严格切片获取当前组
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_page_items = contents[start_idx:end_idx]

    # --- 精准统计逻辑 ---
    video_count = 0
    photo_count = 0
    file_count = 0

    for item in contents:
        try:
            # 从存储群组获取原始消息进行类型判断
            msg = await app.get_messages(groups[0], item['desta'])
            if item['mgroup_id']:
                # 如果是媒体组，统计该组内所有成员
                mg_msgs = await app.get_media_group(groups[0], item['desta'])
                for m in mg_msgs:
                    if m.video: video_count += 1
                    elif m.photo: photo_count += 1
                    else: file_count += 1
            else:
                # 单个消息判断
                if msg.video: video_count += 1
                elif msg.photo: photo_count += 1
                else: file_count += 1
        except Exception:
            continue
    # ------------------

    # 发送当前页媒体
    for item in current_page_items:
        try:
            if item['mgroup_id']:
                await app.copy_media_group(chat_id, groups[0], item['desta'])
            else:
                await app.copy_message(chat_id, groups[0], item['desta'])
        except Exception as e:
            print(f"发送失败: {e}")

    # 构建页码按钮
    buttons = []
    if total_pages > 1:
        # 限制按钮数量，避免过多资源时溢出屏幕
        for i in range(1, total_pages + 1):
            label = f"⚪{i}" if i == page else str(i)
            buttons.append(InlineKeyboardButton(label, callback_data=f"page|{pack_id}|{i}"))
    
    # 将按钮按每排5个进行切分
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
    success_count = 0  # 增加计数器替代 undefined 的 new_mlks

    for mid in data["msgs"]:
        try:
            msg = await app.get_messages(chat_id, mid)
            if not msg or not msg.media: continue

            mgroup_id, desta_id = "", 0
            if msg.media_group_id:
                if msg.media_group_id in processed_mgids: continue
                processed_mgids.add(msg.media_group_id)
                mg_msgs = await app.get_media_group(chat_id, mid)
                res = await app.forward_messages(groups[0], chat_id, [m.id for m in mg_msgs])
                desta_id, mgroup_id = res[0].id, str(msg.media_group_id)
            else:
                res = await app.copy_message(groups[0], chat_id, mid)
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
    media_cl = []
    if not ids:
        return
    for i in ids:
        try:
            msg = await app.get_messages(groups[0], i)
            await asyncio.sleep(1.25)
        except FloodWait as e:
            await asyncio.sleep(e.value + 3)
        except Exception:
            await asyncio.sleep(1)
            msg = await app.get_messages(groups[0], i)
        if msg.media_group_id:
            msgs = await app.get_media_group(groups[0], i)
            for ix in msgs:
                type = mediatotype(ix.media)
                media_cl.append({"type": type, "file_id": getattr(ix, type).file_id, "thumb": ix.video.thumbs[0].file_id if type == "video" else ""})
        else:
                type = mediatotype(msg.media)
                media_cl.append({"type": type, "file_id": getattr(msg, type).file_id, "thumb": msg.video.thumbs[0].file_id if type == "video" else ""})
    return media_cl

async def join_process(file_list, chat_id, hint = False):
    if len(file_list) <= 10:
        if len(file_list) == 1:
            if type(file_list[0]) == InputMediaPhoto:
                msg = await app.send_photo(chat_id, file_list[0].media)
            if type(file_list[0]) == InputMediaVideo:
                msg = await app.send_video(chat_id, file_list[0].media, thumb = file_list[0].thumb)
            if type(file_list[0]) == InputMediaAudio:
                msg = await app.send_audio(chat_id, file_list[0].media)
            if type(file_list[0]) == InputMediaDocument:
                msg = await app.send_document(chat_id, file_list[0].media)
            await media_prep(chat_id, msg.id, 0, msg.date)
            return
        else:
            try:
                msg = await app.send_media_group(chat_id, file_list)
                await media_prep(chat_id, msg[0].id, 0, msg[0].date, str(msg[0].media_group_id))
            except Exception:
                await app.send_message(chat_id, text = "暂不支持文档和图片进行组包")
            finally:
                return
    else:
        if not hint:
            try:
                await app.send_message(chat_id, text = "媒体总数超过10个，将以10个一组返回，请耐心等待")
            except Exception:
                return
        msg = await app.send_media_group(chat_id, file_list[0:10])
        await asyncio.sleep(1.2)
        await media_prep(chat_id, msg[0].id, 0, msg[0].date, str(msg[0].media_group_id))
        await asyncio.sleep(2 + random.randint(15,45) / 10)
        return await join_process(file_list[10:], chat_id, hint = True)

async def pre_command(message):
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
                    await app.send_message(chat_id = message.chat.id, text = f"资源将在{cdt}秒后返回，请勿重复点击")
                    decode_rate_con(from_id, 8)
                    await asyncio.sleep(cdt + ret_task_count * 0.33)
                else:
                    subbot_btn = InlineKeyboardMarkup([[
                        InlineKeyboardButton("发给副BOT处理",url = f"{SUB_BOT_LINK}{result[0]}")
                    ]])
                    await app.send_message(chat_id = message.chat.id, text = f"每{cdt}秒最多提交一次解析请求，请稍后再试", reply_markup = subbot_btn)
                    return
            except Exception as e:
                print(e)
        if len(result) > 3:
            try:
                await app.send_message(chat_id = message.chat.id, text = "一次最多解析三个KEY，超出部分会被忽略")
            except Exception:
                return
            result = result[0:3]
        await link_prep(chat_id, msg_id, from_id, result)

@app.on_message(filters.command("start") & filters.private)
async def cmd_main(client, message):
    if len(message.command) == 2:
        param = message.command[1]
        # 如果是点击了文件夹链接: /start pack_xxxx
        if param.startswith("pack_"):
            pack_id = param.replace("pack_", "")
            await send_pack_page(message.chat.id, pack_id, 1)
            return
        # 正常单资源解析
        await pre_command(message)
        return
    welcome_text = '我是一个资源存储机器人，能够帮你把媒体资源转换为代码链接，便于分享和转发\n直接向我发送媒体开始使用，或者发送 /help 查看帮助'
    try:
        await app.send_message(message.from_user.id, welcome_text)
    except Exception:
        return

@app.on_message(filters.command("help") & filters.private)
async def cmd_main(client, message):
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
async def join_media(client, message):
    if decode_rate_con(message.from_user.id):
        try:
            await app.send_message(chat_id = message.chat.id, text = "每30秒最多提交一次媒体组包请求，请稍后再试")
        except Exception:
            return
        return
    chat_id = message.chat.id
    result = re.findall(r'\w{48}-\w{8}', message.text)
    if not result:
        return
    if len(result) < 2 or len(result) > 10:
        try:
            await app.send_message(chat_id = message.chat.id, text = "媒体组包功能需要2-10个分享链接")
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
    decode_rate_con(message.from_user.id, p = 18)
    await join_process(file_list, chat_id)

@app.on_message(filters.command("s") & filters.private)
async def cmd_main(client, message):
    if (message.text.find(" ") > 0):
        search_word = message.text.split(" ")[-1]
        if decode_rate_con(message.from_user.id):
            try:
                await app.send_message(chat_id = message.chat.id, text = "每12秒最多提交一次搜索请求，请稍后再试")
            except Exception:
                return
        data = search_names(message.from_user.id, search_word[0:32])
        if data:
            search_rr = '<b>搜索结果</b>：\n'
            n = 1
            for w in data:
                search_rr += f"{n}.{w['name']}: `{BOT_LINK_PREFIX}{w['mlk']}-{w['mkey']}`\n"
                n += 1
            await app.send_message(chat_id = message.chat.id, text = search_rr)
        else:
            await app.send_message(chat_id = message.chat.id, text = "搜索无结果")

# --- 修改媒体处理逻辑 ---
@app.on_message((filters.media | filters.media_group) & filters.private)
async def media_handler(client, message):
    uid = message.from_user.id
    # 如果用户在批量模式中，只记录 ID，不回复任何链接
    if uid in batch_active_users:
        if message.media_group_id:
            # 简单去重逻辑，防止媒体组触发多次
            if message.id not in batch_active_users[uid]["msgs"]:
                batch_active_users[uid]["msgs"].append(message.id)
        else:
            batch_active_users[uid]["msgs"].append(message.id)
        return 

    # 原有 media_prep 逻辑 (非批量模式)
    owner = uid if message.from_user else 0
    await media_prep(message.chat.id, message.id, owner, message.date)

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

    # 2. 原有的过期设置逻辑 (由 queue_ans 合并而来)
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

@app.on_message(filters.command("start_batch") & filters.private)
async def cmd_start_batch(client, message):
    uid = message.from_user.id
    if uid in batch_active_users:
        await message.reply("您已经在批量模式中了。")
        return
    
    # 开启缓冲区并设置超时监控
    batch_active_users[uid] = {
        "msgs": [],
        "timer": asyncio.create_task(batch_timeout_monitor(uid, message.chat.id))
    }
    await message.reply("🚀 **批量读取模式已开启**\n现在请发送或转发媒体给我，完成后发送 /end_batch 即可生成提取链接。")

@app.on_message(filters.command("end_batch") & filters.private)
async def cmd_end_batch(client, message):
    await end_batch_logic(message.from_user.id, message.chat.id)

async def batch_timeout_monitor(user_id, chat_id):
    """超时自动结算"""
    await asyncio.sleep(BATCH_TIMEOUT)
    if user_id in batch_active_users:
        await app.send_message(chat_id, "⚠️ 批量模式已达到5分钟，正在自动结算...")
        await end_batch_logic(user_id, chat_id)

@app.on_message(filters.reply & filters.private & filters.command("name"))
async def reply_main(client, message):
    content = message.reply_to_message.text
    result = re.search(r'\w{48}-\w{8}', content)
    if not result: return
    result = result.group(0)
    
    if decode_rate_con(message.from_user.id):
        await app.send_message(chat_id = message.chat.id, text = "每12秒最多提交一次命名请求，请稍后再试")
        return
        
    if (message.text.find(" ") > 0):
        new_name = message.text.split(" ")[-1]
        data_set = read_rec(result[0:48])
        if (data_set and data_set['owner'] == message.from_user.id):
            try:
                set_name(result[0:48], new_name[0:32])
                await app.send_message(message.chat.id, text = "命名成功", reply_to_message_id = message.id)
            except Exception:
                await app.send_message(message.chat.id, text = "命名失败")

@app.on_message(filters.private & filters.command("top"))
async def top_rank(client, message):
    owner = message.from_user.id if message.from_user else 0
    if decode_rate_con(owner):
        await app.send_message(chat_id = message.chat.id, text = "请稍后再试")
        return
    view_data = top_views(owner)
    if not view_data: return
    result = "以下是取回最多的资源：\n\n"
    for rec in view_data:
        result += f"[{rec['id']}]({BOT_LINK_PREFIX}{rec['mlk']}-{rec['mkey']}) > 取回:{rec['views']}\n"
    await app.send_message(message.chat.id, result)

@app.on_message(filters.private & filters.command("lock"))
async def lock_key(client, message):
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
        await app.send_message(message.chat.id, text = f"主KEY更换成功: `{BOT_LINK_PREFIX}{result[0:48]}-{new_key}`")

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