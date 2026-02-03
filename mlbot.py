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
BOT_USERNAME = "mlkautobot" 
BOT_LINK_PREFIX = f"https://t.me/{BOT_USERNAME}?start="
# 副BOT链接配置
SUB_BOT_LINK = "https://t.me/mlk3autobot?start="
# ----------------

app = Client("mlkauto", api_id=api_id, api_hash=api_hash,bot_token=bot_token, max_concurrent_transmissions = 1, sleep_threshold = 60)

app.message_cache = Cache(1000000)
dl_types = [MessageMediaType.PHOTO, MessageMediaType.VIDEO, MessageMediaType.AUDIO, MessageMediaType.DOCUMENT]
groups = [-100,-100,-100]
use_record = {}

dbconfig = {
    "host": "127.0.0.1",
    "user": "mlkauto",
    "password": "",
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

def write_rec(mlk, mkey, skey, owner, desta, mgroup_id = ""):
    try:
        conn = connection_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        val_mgroup = mgroup_id if mgroup_id else None
        sql = 'INSERT INTO records (mlk, mkey, skey, owner, mgroup_id, desta ) VALUES (%s, %s, %s, %s, %s, %s)'
        cursor.execute(sql, (mlk, mkey, skey, owner, val_mgroup, desta))
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
        sql = 'SELECT * FROM records WHERE mlk = %s'
        cursor.execute(sql, (mlk,))
        result = cursor.fetchone()
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    if result and len(result) > 0:
        sql = 'UPDATE records SET views = views + 1 WHERE mlk = %s'
        cursor.execute(sql, (mlk,))
        conn.commit()
        cursor.close()
        conn.close()
        return result
    else:
        cursor.close()
        conn.close()
        return False

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
                if data_set['pack_id']:
                    full_set = read_pack(data_set['pack_id'])
                    try:
                        await app.send_message(chat_id, text =  f"该媒体属于文件夹 `{data_set['pack_id']}` ，正在返回全部{len(full_set)}组媒体\n\n文件夹取回操作优先级较低，请耐心等待")
                    except Exception:
                        return
                    for set in full_set:
                        task = asyncio.create_task(link_to_media(chat_id, msg_id, set['desta'], set['mgroup_id'], ret_sem))
                        await asyncio.sleep(0.5 + 1.33 * ret_task_count + 1.5 * len(full_set))
                        ret_task_count += 1
                        ret_task.append(task)
                    await asyncio.gather(*ret_task)
                    return
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
    if (message.command and len(message.command) == 2):
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
链接格式均为：<pre>[48位资源索引]-[8位密钥]</pre> 

🔖 一次性KEY在被获取后密钥会自动销毁。
如果你是资源上传者，可以向机器人发送主分享KEY来获取最新的一次性KEY。

🔎 资源上传者可以使用 <pre>/s 关键词</pre> 来搜索自己上传的资源。
📦 如需组包，可以使用 <pre>/join 链接1 链接2</pre> (最多10个)。
🧰 文件夹管理请使用 <pre>/pack</pre>。
⛓️‍💥 停止分享请回复KEY消息并发送 <pre>/lock</pre>。
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

@app.on_message(filters.media_group & filters.private)
async def media_group_handler(client, message):
    mgroup_id = str(message.media_group_id)
    if mgroup_id in processed_media_groups:
        return
    processed_media_groups[mgroup_id] = time.time()
    await asyncio.sleep(1.2)
    owner = message.from_user.id if message.from_user else 0
    await media_prep(message.chat.id, message.id, owner, message.date, mgroup_id)

@app.on_message(filters.media & ~filters.media_group & filters.private)
async def media_main(client, message):
    owner = message.from_user.id if message.from_user else 0
    await media_prep(message.chat.id, message.id, owner, message.date)

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

@app.on_message(filters.reply & filters.private & filters.command("pack"))
async def add_to_pack(client, message):
    content = message.reply_to_message.text
    mlk = []
    try:
        mlk.append(re.search(r'\w{48}-\w{8}', content).group(0)[0:48])
    except Exception:
        await app.send_message(chat_id = message.chat.id, text = "操作错误，请用 /pack 回复媒体消息")
        return
    
    owner = message.from_user.id if message.from_user else 0
    if decode_rate_con(owner):
        await app.send_message(chat_id = message.chat.id, text = "请稍后再试")
        return
        
    data_set = read_rec(mlk[0])
    if (not data_set or not data_set['owner'] == owner):
        await app.send_message(message.chat.id, text = "无权设定文件夹")
        return
        
    if (message.text == "/pack"):
        packid = hashlib.shake_128(str(uuid.uuid4()).encode()).hexdigest(6)
        set_packid(mlk,packid)
        await app.send_message(message.chat.id, text = f"资源成功添加到文件夹: `{packid}`", reply_to_message_id = message.id)
    elif (message.text.find(" ") > 0):
        request_packid = message.text.split(" ")[-1]
        pack_test = read_pack(request_packid)
        if pack_test and len(pack_test) <= 5:
            set_packid(mlk,request_packid)
            await app.send_message(message.chat.id, text = f"资源成功添加到文件夹: `{request_packid}`", reply_to_message_id = message.id)

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

@app.on_callback_query()
async def queue_ans(client, callback_query):
    try:
        mlk = callback_query.data.split("?")[0]
        cmd = callback_query.data.split("?")[-1].split("=")[0]
        op = callback_query.data.split("?")[-1].split("=")[-1]
        data_set = read_rec(mlk)
        if data_set['owner'] != callback_query.from_user.id: return
        
        if cmd == "exp":
            if op == "1H": exp = datetime.now() + timedelta(hours=1)
            elif op == "3H": exp = datetime.now() + timedelta(hours=3)
            elif op == "24H": exp = datetime.now() + timedelta(days=1)
            else: exp = datetime.now() + timedelta(weeks=300)
            
            exp_str = exp.strftime("%Y-%m-%d %H:%M:%S")
            set_expire(mlk, exp_str)
            await app.send_message(callback_query.message.chat.id, text = f"过期时间设定为：{exp_str}")
    except Exception:
        pass

async def main():
    async with app:
        await app.set_bot_commands([
            BotCommand("start", "开始使用"),
            BotCommand("help", "详细功能说明"),
            BotCommand("s", "搜索资源"),
            BotCommand("join", "组包媒体"),
            BotCommand("top", "取回排行"),
            BotCommand("lock", "更换主KEY"),
            BotCommand("name", "资源命名"),
            BotCommand("pack", "文件夹管理")
        ])
        print(f"[INFO] 机器人 @{BOT_USERNAME} 运行中...")
        await asyncio.Event().wait()

if __name__ == "__main__":
    app.run(main())