import asyncio
import logging
import os
import random

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from content import BLOCKS, DAILY_TIPS, INTRO_TEXT
from database import (
    get_diary,
    get_progress,
    init_db,
    mark_block_completed,
    mark_self_check_done,
    save_diary_entry,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

(
    STATE_MAIN_MENU,
    STATE_BLOCK_MENU,
    STATE_THEORY,
    STATE_EXERCISE,
    STATE_TIMER,
    STATE_SELF_CHECK,
    STATE_DIARY_NOTE,
) = range(7)

TOTAL_BLOCKS = 5


def main_menu_keyboard(progress: dict) -> InlineKeyboardMarkup:
    buttons = []
    for i in range(1, TOTAL_BLOCKS + 1):
        done = progress.get(i, {}).get("completed", 0)
        check = progress.get(i, {}).get("self_check_done", 0)
        label = BLOCKS[i]["title"]
        icon = "✅" if (done and check) else ("🔄" if done else "📌")
        buttons.append([InlineKeyboardButton(f"{icon} {label}", callback_data=f"block_{i}")])
    buttons.append([InlineKeyboardButton("📓 Мой дневник", callback_data="diary")])
    buttons.append([InlineKeyboardButton("💡 Совет дня", callback_data="tip")])
    return InlineKeyboardMarkup(buttons)


def block_menu_keyboard(block_num: int, progress: dict) -> InlineKeyboardMarkup:
    block = BLOCKS[block_num]
    completed = progress.get(block_num, {}).get("completed", 0)
    self_check_done = progress.get(block_num, {}).get("self_check_done", 0)
    buttons = [
        [InlineKeyboardButton("📖 Теория", callback_data=f"theory_{block_num}")],
    ]
    for i, ex in enumerate(block["exercises"]):
        buttons.append([
            InlineKeyboardButton(f"💪 {ex['name']}", callback_data=f"ex_{block_num}_{i}")
        ])
    if completed and not self_check_done:
        buttons.append([InlineKeyboardButton("✍️ Самооценка", callback_data=f"check_{block_num}_0")])
    elif self_check_done:
        buttons.append([InlineKeyboardButton("✅ Самооценка пройдена", callback_data="check_done")])
    else:
        buttons.append([InlineKeyboardButton("✍️ Самооценка (после упражнений)", callback_data=f"check_{block_num}_0")])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    progress = await get_progress(user_id)
    await update.message.reply_text(INTRO_TEXT, reply_markup=main_menu_keyboard(progress))
    return STATE_MAIN_MENU


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    progress = await get_progress(user_id)
    await query.edit_message_text(INTRO_TEXT, reply_markup=main_menu_keyboard(progress))
    return STATE_MAIN_MENU


async def block_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    block_num = int(query.data.split("_")[1])
    user_id = query.from_user.id
    progress = await get_progress(user_id)
    block = BLOCKS[block_num]
    text = f"*{block['title']}*\n_{block['subtitle']}_\n\nВыберите раздел:"
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=block_menu_keyboard(block_num, progress))
    return STATE_BLOCK_MENU


async def theory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    block_num = int(query.data.split("_")[1])
    block = BLOCKS[block_num]
    text = f"*{block['title']}*\n\n{block['theory']}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("← Назад к блоку", callback_data=f"block_{block_num}")]])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    return STATE_THEORY


async def exercise_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, block_num_str, ex_idx_str = query.data.split("_")
    block_num = int(block_num_str)
    ex_idx = int(ex_idx_str)
    block = BLOCKS[block_num]
    ex = block["exercises"][ex_idx]
    total = len(block["exercises"])
    context.user_data["current_block"] = block_num
    context.user_data["current_ex"] = ex_idx
    text = f"*{ex['name']}*\n\n{ex['description']}"
    buttons = []
    timer_min = ex.get("duration", 3)
    buttons.append([InlineKeyboardButton(f"⏱ Запустить таймер ({timer_min} мин)",
                                          callback_data=f"timer_{block_num}_{ex_idx}_{timer_min}")])
    nav = []
    if ex_idx > 0:
        nav.append(InlineKeyboardButton("◀️ Предыдущее", callback_data=f"ex_{block_num}_{ex_idx - 1}"))
    if ex_idx < total - 1:
        nav.append(InlineKeyboardButton("Следующее ▶️", callback_data=f"ex_{block_num}_{ex_idx + 1}"))
    if nav:
        buttons.append(nav)
    if ex_idx == total - 1:
        buttons.append([InlineKeyboardButton("✅ Блок выполнен!", callback_data=f"done_{block_num}")])
    buttons.append([InlineKeyboardButton("← Назад к блоку", callback_data=f"block_{block_num}")])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    return STATE_EXERCISE


async def timer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏱ Таймер запущен!")
    parts = query.data.split("_")
    block_num = int(parts[1])
    ex_idx = int(parts[2])
    minutes = int(parts[3])
    seconds = minutes * 60
    await query.edit_message_text(
        f"⏱ *Таймер запущен: {minutes} мин*\n\nВыполняйте упражнение...\nБот уведомит вас, когда время выйдет.",
        parse_mode=ParseMode.MARKDOWN)
    await asyncio.sleep(seconds)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("← Вернуться к упражнению",
                                                            callback_data=f"ex_{block_num}_{ex_idx}")]])
    try:
        await query.message.reply_text(
            "✅ *Время вышло!* Упражнение завершено.\n\nОтличная работа!",
            parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    except Exception:
        pass
    return STATE_TIMER


async def done_block_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    block_num = int(query.data.split("_")[1])
    user_id = query.from_user.id
    await mark_block_completed(user_id, block_num)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Пройти самооценку", callback_data=f"check_{block_num}_0")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
    ])
    await query.edit_message_text(
        f"🎉 *Блок {block_num} выполнен!*\n\nОтличная работа! Теперь пройдите самооценку.",
        parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    return STATE_MAIN_MENU


async def self_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "check_done":
        await query.answer("Самооценка уже пройдена ✅", show_alert=True)
        return STATE_BLOCK_MENU
    parts = query.data.split("_")
    block_num = int(parts[1])
    q_idx = int(parts[2])
    block = BLOCKS[block_num]
    questions = block["self_check"]
    if q_idx >= len(questions):
        user_id = query.from_user.id
        await mark_self_check_done(user_id, block_num)
        context.user_data["diary_block"] = block_num
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ Отлично", callback_data="diary_great")],
            [InlineKeyboardButton("👍 Хорошо", callback_data="diary_good")],
            [InlineKeyboardButton("😐 Трудно", callback_data="diary_hard")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ])
        await query.edit_message_text(
            "✅ *Самооценка завершена!*\n\nКак вы оцениваете сегодняшнюю тренировку?",
            parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return STATE_SELF_CHECK
    q = questions[q_idx]
    buttons = []
    for opt in q["options"]:
        buttons.append([InlineKeyboardButton(opt, callback_data=f"check_{block_num}_{q_idx + 1}")])
    buttons.append([InlineKeyboardButton("← Пропустить", callback_data=f"check_{block_num}_{q_idx + 1}")])
    await query.edit_message_text(
        f"*Самооценка — Блок {block_num}*\nВопрос {q_idx + 1} из {len(questions)}:\n\n_{q['question']}_",
        parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    return STATE_SELF_CHECK


async def diary_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rating_map = {"diary_great": "⭐ Отлично", "diary_good": "👍 Хорошо", "diary_hard": "😐 Трудно"}
    rating = rating_map.get(query.data, "—")
    block_num = context.user_data.get("diary_block", 0)
    user_id = query.from_user.id
    await save_diary_entry(user_id, block_num, rating)
    progress = await get_progress(user_id)
    completed_count = sum(1 for v in progress.values() if v.get("completed"))
    await query.edit_message_text(
        f"📓 *Записано в дневник!*\n\nБлок {block_num} — {rating}\n\nВсего блоков пройдено: {completed_count}/{TOTAL_BLOCKS}\n\nПродолжайте в том же духе! 💪",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]))
    return STATE_MAIN_MENU


async def diary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    entries = await get_diary(user_id)
    progress = await get_progress(user_id)
    completed_count = sum(1 for v in progress.values() if v.get("completed"))
    checks_count = sum(1 for v in progress.values() if v.get("self_check_done"))
    if not entries:
        text = "📓 *Ваш дневник пуст*\n\nВыполните упражнения и пройдите самооценку — здесь будет ваш прогресс."
    else:
        text = f"📓 *Ваш дневник прогресса*\n\n✅ Пройдено блоков: {completed_count}/{TOTAL_BLOCKS}\n✍️ Самооценок: {checks_count}/{TOTAL_BLOCKS}\n\nПоследние записи:\n"
        for e in entries[:7]:
            date = e["created_at"][:10] if e["created_at"] else "—"
            text += f"\n📌 Блок {e['block_num']} | {date} | {e['rating']}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    return STATE_MAIN_MENU


async def tip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tip = random.choice(DAILY_TIPS)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Ещё совет", callback_data="tip")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
    ])
    await query.edit_message_text(f"*Совет дня*\n\n{tip}", parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    return STATE_MAIN_MENU


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎙 *Тренажёр постановки голоса*\n\nКоманды:\n/start — главное меню\n/help — помощь\n\n"
        "Как пользоваться:\n1. Выберите блок из меню\n2. Прочитайте теорию\n"
        "3. Выполните упражнения (используйте таймер)\n4. Пройдите самооценку\n"
        "5. Отслеживайте прогресс в дневнике\n\nЗанимайтесь ежедневно по 15-20 минут 💪",
        parse_mode=ParseMode.MARKDOWN)


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN не задан в .env файле")
    app = Application.builder().token(token).build()

    async def post_init(application):
        await init_db()

    app.post_init = post_init
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(block_menu_callback, pattern=r"^block_\d+$"))
    app.add_handler(CallbackQueryHandler(theory_callback, pattern=r"^theory_\d+$"))
    app.add_handler(CallbackQueryHandler(exercise_callback, pattern=r"^ex_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(timer_callback, pattern=r"^timer_\d+_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(done_block_callback, pattern=r"^done_\d+$"))
    app.add_handler(CallbackQueryHandler(self_check_callback, pattern=r"^check_(\d+_\d+|done)$"))
    app.add_handler(CallbackQueryHandler(diary_rating_callback, pattern=r"^diary_(great|good|hard)$"))
    app.add_handler(CallbackQueryHandler(diary_callback, pattern="^diary$"))
    app.add_handler(CallbackQueryHandler(tip_callback, pattern="^tip$"))
    logger.info("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()