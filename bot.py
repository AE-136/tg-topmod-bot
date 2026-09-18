"""
Telegram-бот: ограничение права писать в конкретных темах (topics) группы
конкретным пользователям.

Как это работает:
- Бот должен быть добавлен в группу как администратор с правом
  "Удаление сообщений" (Delete messages).
- Бот слушает все сообщения (админ-боты получают их независимо от privacy mode).
- Для каждой темы можно назначить режим "whitelist": писать разрешено
  только тем, кого явно добавили командой /allow. До первого /allow тема
  открыта - писать может любой участник группы.
- Если пользователь не в списке разрешённых для этой темы (и режим уже
  whitelist) - его сообщение удаляется сразу после отправки.

Кто может пользоваться командами настройки (/allow, /disallow, /open_topic):
- Команды принимают только от администраторов группы. Обычный пользователь
  получает явный отказ.
- Если тема уже в режиме белого списка - администратор должен ДОПОЛНИТЕЛЬНО
  быть явно добавлен в белый список именно этой темы, иначе команда просто
  игнорируется (без ответа) - даже если он админ группы. Пока тема открыта
  (whitelist ещё не включён), команда доступна любому админу - это точка
  входа: первый /allow в теме и включает режим белого списка.
"""

import logging
import os

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# BOT_TOKEN - имя переменной окружения, которое bothost.ru подставляет
# автоматически, если бот создан через мастер "Telegram" с указанием токена.
# API_TOKEN / TELEGRAM_BOT_TOKEN - синонимы на случай общего Python-шаблона.
BOT_TOKEN = (
    os.environ.get("BOT_TOKEN")
    or os.environ.get("API_TOKEN")
    or os.environ.get("TELEGRAM_BOT_TOKEN")
)


def get_topic_id(update: Update) -> int:
    """General (без темы) хранится как 0."""
    msg = update.effective_message
    return msg.message_thread_id if msg and msg.message_thread_id else 0


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Администратор или владелец группы в Telegram."""
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return False
    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


async def check_topic_command_permission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    Проверка для команд /allow, /disallow, /open_topic - привязанных к
    конкретной теме. Возвращает:
      "ok"     - можно выполнять команду;
      "denied" - вызвавший вообще не администратор группы -> нужно явно
                 ответить отказом;
      "ignore" - администратор, но тема уже в режиме белого списка, а он в
                 этот белый список не входит -> команду просто игнорируем,
                 без ответа (даже если это админ группы).
    """
    if not await is_admin(update, context):
        return "denied"

    user = update.effective_user
    chat = update.effective_chat
    topic_id = get_topic_id(update)
    mode = storage.get_topic_mode(chat.id, topic_id)

    if mode != "whitelist":
        # тема ещё открыта - это точка входа: любой админ может выполнить
        # первый /allow и включить режим белого списка
        return "ok"

    if storage.is_explicitly_listed(chat.id, topic_id, user.id):
        return "ok"

    return "ignore"


def _extract_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь-цель команды: из ответа на сообщение, либо из аргумента user_id [имя]."""
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        u = update.message.reply_to_message.from_user
        return u.id, (u.username or u.first_name)
    if context.args and context.args[0].lstrip("-").isdigit():
        target_id = int(context.args[0])
        target_name = context.args[1] if len(context.args) > 1 else str(target_id)
        return target_id, target_name
    return None, None


ACCESS_DENIED_MSG = "Эта команда доступна только администраторам группы."


async def cmd_allow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = await check_topic_command_permission(update, context)
    if result == "denied":
        await update.message.reply_text(ACCESS_DENIED_MSG)
        return
    if result == "ignore":
        return  # админ, но не в белом списке этой (уже закрытой) темы - молчим

    chat_id = update.effective_chat.id
    topic_id = get_topic_id(update)
    target_id, target_name = _extract_target(update, context)

    if target_id is None:
        await update.message.reply_text(
            "Ответьте командой /allow на сообщение пользователя, которому нужно "
            "разрешить писать в ЭТОЙ теме, либо укажите его user_id: /allow 123456789 [имя]"
        )
        return

    storage.allow_user(chat_id, topic_id, target_id, target_name)
    await update.message.reply_text(
        f"Пользователь {target_name or target_id} теперь может писать в этой теме."
    )


async def cmd_disallow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = await check_topic_command_permission(update, context)
    if result == "denied":
        await update.message.reply_text(ACCESS_DENIED_MSG)
        return
    if result == "ignore":
        return

    chat_id = update.effective_chat.id
    topic_id = get_topic_id(update)
    target_id, _ = _extract_target(update, context)

    if target_id is None:
        await update.message.reply_text(
            "Ответьте командой /disallow на сообщение пользователя, "
            "либо укажите его user_id: /disallow 123456789"
        )
        return

    storage.disallow_user(chat_id, topic_id, target_id)
    await update.message.reply_text("Доступ пользователя к этой теме отменён.")


async def cmd_open_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = await check_topic_command_permission(update, context)
    if result == "denied":
        await update.message.reply_text(ACCESS_DENIED_MSG)
        return
    if result == "ignore":
        return

    chat_id = update.effective_chat.id
    topic_id = get_topic_id(update)
    storage.reset_topic(chat_id, topic_id)
    await update.message.reply_text("Тема снова открыта для всех участников группы.")


async def cmd_topic_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    topic_id = get_topic_id(update)
    mode = storage.get_topic_mode(chat_id, topic_id)

    if mode != "whitelist":
        await update.message.reply_text("Эта тема открыта — писать может любой участник группы.")
        return

    users = storage.list_allowed(chat_id, topic_id)
    if not users:
        await update.message.reply_text(
            "Тема в режиме белого списка, но список пуст — писать пока не может никто."
        )
        return

    lines = [f"- {uname or uid} (id: {uid})" for uid, uname in users]
    await update.message.reply_text("Писать в этой теме разрешено:\n" + "\n".join(lines))


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_admin(update, context):
        await update.message.reply_text(ACCESS_DENIED_MSG)
        return

    chat_id = update.effective_chat.id
    rules = storage.list_all_rules(chat_id)
    if not rules:
        await update.message.reply_text("Для этой группы пока нет ограничений по темам.")
        return

    lines = []
    for topic_id, mode in rules:
        label = "General (без темы)" if topic_id == 0 else f"topic_id={topic_id}"
        lines.append(f"{label}: {mode}")
    await update.message.reply_text("\n".join(lines))


async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список пользователей в белом списке ТЕКУЩЕЙ темы (той, в которой вызвана команда)."""
    if not await is_admin(update, context):
        await update.message.reply_text(ACCESS_DENIED_MSG)
        return

    chat_id = update.effective_chat.id
    topic_id = get_topic_id(update)
    users = storage.list_allowed(chat_id, topic_id)

    if not users:
        await update.message.reply_text("В белом списке этой темы пока никого нет.")
        return

    lines = [f"- {uname or uid} (id: {uid})" for uid, uname in users]
    await update.message.reply_text("Белый список этой темы:\n" + "\n".join(lines))


async def enforce_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.from_user is None:
        # анонимный админ или служебное сообщение - не трогаем
        return

    chat_id = update.effective_chat.id
    topic_id = get_topic_id(update)
    user_id = msg.from_user.id

    if storage.is_user_allowed(chat_id, topic_id, user_id):
        return

    try:
        await context.bot.delete_message(chat_id, msg.message_id)
        logger.info(
            "Удалено сообщение user_id=%s chat_id=%s topic_id=%s",
            user_id, chat_id, topic_id,
        )
    except Exception as e:
        logger.warning("Не удалось удалить сообщение: %s", e)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Укажите токен бота в переменной окружения BOT_TOKEN")

    storage.init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики команд регистрируем в группе 0 (по умолчанию) - они должны
    # успеть отработать первыми и ответить пользователю.
    application.add_handler(CommandHandler("allow", cmd_allow), group=0)
    application.add_handler(CommandHandler("disallow", cmd_disallow), group=0)
    application.add_handler(CommandHandler("open_topic", cmd_open_topic), group=0)
    application.add_handler(CommandHandler("topic_status", cmd_topic_status), group=0)
    application.add_handler(CommandHandler("rules", cmd_rules), group=0)
    application.add_handler(CommandHandler("whitelist", cmd_whitelist), group=0)

    # enforce_rules регистрируем в ОТДЕЛЬНОЙ группе (1) и без исключения команд:
    # в python-telegram-bot обработчики из разных групп выполняются независимо,
    # поэтому это правило проверяет КАЖДОЕ сообщение в группе - включая команды -
    # даже если его уже обработал один из хендлеров выше. Иначе сообщение с
    # любой командой (в том числе несуществующей, типа /spam) не проверялось бы
    # на удаление и было бы дырой для обхода ограничений темы.
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, enforce_rules), group=1)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
