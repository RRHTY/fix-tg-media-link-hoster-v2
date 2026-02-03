#  Pyrogram - Telegram MTProto API Client Library for Python
#  Copyright (C) 2017-present Dan <https://github.com/delivrance>
#
#  This file is part of Pyrogram.
#
#  Pyrogram is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published
#  by the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Pyrogram is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with Pyrogram.  If not, see <http://www.gnu.org/licenses/>.

import logging
from typing import Union, List

import pyrogram
from pyrogram import types

log = logging.getLogger(__name__)


class GetMediaGroup:
    async def get_media_group(
        self: "pyrogram.Client",
        chat_id: Union[int, str],
        message_id: int
    ) -> List["types.Message"]:
        if message_id <= 0:
            raise ValueError("Passed message_id is negative or equal to zero.")

        # 1. 扩大扫描范围：前后各取 10 条（媒体组上限是 10 张图）
        messages = await self.get_messages(
            chat_id=chat_id,
            message_ids=[msg_id for msg_id in range(message_id - 10, message_id + 11)],
            replies=0
        )

        # 2. 健壮地寻找目标消息的 media_group_id
        # 不再使用固定索引，而是直接过滤出 ID 匹配的那条消息
        target_msg = next((m for m in messages if m and m.id == message_id), None)
        
        if not target_msg or target_msg.media_group_id is None:
            raise ValueError("The message doesn't belong to a media group")

        media_group_id = target_msg.media_group_id

        # 3. 返回该组内所有消息
        return types.List(msg for msg in messages if msg and msg.media_group_id == media_group_id)