"""Кто может пользоваться ботом: владелица, приглашённые друзья и лимит запросов к ИИ.

Владельцы — id из ALLOWED_USER_IDS (переменная на хостинге). Они могут звать друзей
командой /invite: бот даёт одноразовую ссылку, по ней человек получает свою отдельную книгу.
Если ALLOWED_USER_IDS пустая — ботом может пользоваться кто угодно.
"""
import secrets
import time

from . import config, db

INVITE_TTL = 7 * 24 * 3600  # ссылка-приглашение живёт неделю


class LimitError(Exception):
    pass


def is_owner(user_id: int) -> bool:
    return user_id in config.ALLOWED_USER_IDS


def allowed(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS or is_owner(user_id):
        return True
    with db.conn() as c:
        return c.execute("SELECT 1 FROM members WHERE user_id=?", (user_id,)).fetchone() is not None


def new_invite(owner_id: int) -> str:
    code = secrets.token_urlsafe(9)
    with db.conn() as c:
        c.execute("INSERT INTO invites(code, created_by, created) VALUES (?,?,?)",
                  (code, owner_id, time.time()))
    return code


def redeem(code: str, user_id: int, name: str) -> str:
    """Пробует принять приглашение. Возвращает ok | already | bad."""
    if allowed(user_id):
        return "already"
    with db.conn() as c:
        r = c.execute("SELECT * FROM invites WHERE code=?", (code,)).fetchone()
        if not r or r["used_by"] or time.time() - r["created"] > INVITE_TTL:
            return "bad"
        c.execute("UPDATE invites SET used_by=? WHERE code=?", (user_id, code))
        c.execute("INSERT OR REPLACE INTO members(user_id, name, invited_by, joined) VALUES (?,?,?,?)",
                  (user_id, name[:100], r["created_by"], time.time()))
    return "ok"


def members() -> list[dict]:
    with db.conn() as c:
        rows = c.execute("""SELECT m.user_id, m.name, m.joined,
                                   (SELECT COUNT(*) FROM recipes r WHERE r.user_id=m.user_id) AS recipes
                            FROM members m ORDER BY m.joined""").fetchall()
    return [dict(r) for r in rows]


def remove(user_id: int) -> bool:
    """Закрывает доступ. Рецепты человека остаются в базе — если позвать снова, они вернутся."""
    with db.conn() as c:
        return c.execute("DELETE FROM members WHERE user_id=?", (user_id,)).rowcount > 0


def spend_ai(user_id: int) -> None:
    """Считает запросы к ИИ за сутки. У владельцев лимита нет, у остальных — AI_DAILY_LIMIT."""
    if is_owner(user_id) or not config.AI_DAILY_LIMIT:
        return
    day = time.strftime("%Y-%m-%d")
    with db.conn() as c:
        r = c.execute("SELECT count FROM ai_usage WHERE user_id=? AND day=?", (user_id, day)).fetchone()
        used = r["count"] if r else 0
        if used >= config.AI_DAILY_LIMIT:
            raise LimitError(f"На сегодня лимит разборов рецептов закончился ({config.AI_DAILY_LIMIT} в день). "
                             "Завтра снова можно.")
        c.execute("INSERT OR REPLACE INTO ai_usage(user_id, day, count) VALUES (?,?,?)",
                  (user_id, day, used + 1))
