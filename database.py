import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "voice_bot.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                user_id INTEGER NOT NULL,
                block_num INTEGER NOT NULL,
                exercise_idx INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                self_check_done INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, block_num)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_diary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                block_num INTEGER NOT NULL,
                rating TEXT NOT NULL,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def get_progress(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT block_num, completed, self_check_done FROM user_progress WHERE user_id = ?",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return {row["block_num"]: dict(row) for row in rows}


async def mark_block_completed(user_id: int, block_num: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO user_progress (user_id, block_num, completed)
               VALUES (?, ?, 1)
               ON CONFLICT(user_id, block_num) DO UPDATE SET completed = 1""",
            (user_id, block_num),
        )
        await db.commit()


async def mark_self_check_done(user_id: int, block_num: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO user_progress (user_id, block_num, self_check_done)
               VALUES (?, ?, 1)
               ON CONFLICT(user_id, block_num) DO UPDATE SET self_check_done = 1""",
            (user_id, block_num),
        )
        await db.commit()


async def save_diary_entry(user_id: int, block_num: int, rating: str, note: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO user_diary (user_id, block_num, rating, note) VALUES (?, ?, ?, ?)",
            (user_id, block_num, rating, note),
        )
        await db.commit()


async def get_diary(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT block_num, rating, note, created_at
               FROM user_diary WHERE user_id = ?
               ORDER BY created_at DESC LIMIT 20""",
            (user_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]