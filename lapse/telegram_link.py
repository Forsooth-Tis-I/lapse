import secrets

from redis.exceptions import WatchError

from lapse import jobs


def new_link_code(uid: str) -> str:
    while True:
        code = secrets.token_urlsafe(18)
        if jobs.client().set(f"lapse:tglink:{code}", uid, ex=3600, nx=True):
            return code


def bind(code: str, chat_id: int) -> str:
    code_key = f"lapse:tglink:{code}"
    chat_key = f"lapse:tgchat:{chat_id}"
    with jobs.client().pipeline() as pipe:
        while True:
            try:
                pipe.watch(code_key, chat_key)
                uid = pipe.get(code_key)
                if uid is None:
                    raise ValueError("Telegram link expired or already used")
                uid_key = f"lapse:tguser:{uid}"
                pipe.watch(uid_key)
                old_chat = pipe.get(uid_key)
                old_uid = pipe.get(chat_key)
                pipe.multi()
                if old_chat and old_chat != str(chat_id):
                    pipe.delete(f"lapse:tgchat:{old_chat}")
                if old_uid and old_uid != uid:
                    pipe.delete(f"lapse:tguser:{old_uid}")
                pipe.set(uid_key, chat_id)
                pipe.set(chat_key, uid)
                pipe.delete(code_key)
                pipe.execute()
                return uid
            except WatchError:
                continue


def chat_for(uid: str) -> int | None:
    value = jobs.client().get(f"lapse:tguser:{uid}")
    return int(value) if value is not None else None


def uid_for(chat_id: int) -> str | None:
    return jobs.client().get(f"lapse:tgchat:{chat_id}")
