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

Команда /all:
- Бот отвечает сообщением с упоминаниями:
    - в теме с включённым белым списком - только тех, кто в нём состоит;
    - в открытой теме - всех пользователей, которых бот когда-либо видел
      пишущими в этой группе (в любой теме).
  Автора команды бот не отмечает. Пользоваться /all может только тот, кому
  разрешено писать в этой теме (от остальных команда молча игнорируется, а
  их сообщение удаляется как обычно). Если отмечать некого - бот отвечает
  коротким пояснением, чтобы было видно, что он работает.
  Важно: Telegram Bot API не даёт боту получить полный список участников
  группы - это ограничение платформы, не кода. Поэтому "все пользователи
  беседы" технически означает "все, кто хоть раз написал хоть что-то, пока
  бот состоял в группе", а не список участников из настроек чата.
"""

import html
import logging
import os

from telegram import Update
from telegram.constants import ChatMemberStatus, ParseMode
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

    if msg.from_user.id == context.bot.id:
        # Telegram и так не присылает боту его собственные сообщения; эта
        # проверка - просто страховка, чтобы бот никогда не удалил и не записал
        # в "виденные" самого себя.
        return

    chat_id = update.effective_chat.id
    topic_id = get_topic_id(update)
    user_id = msg.from_user.id
    display_name = msg.from_user.username or msg.from_user.first_name

    # Запоминаем автора как "видели в этой группе" ДО проверки прав - это
    # нужно для /all в открытых темах, и человек остаётся участником беседы
    # независимо от того, разрешено ли ему писать именно здесь.
    storage.record_seen_user(chat_id, user_id, display_name)

    if not storage.is_user_allowed(chat_id, topic_id, user_id):
        try:
            await context.bot.delete_message(chat_id, msg.message_id)
            logger.info(
                "Удалено сообщение user_id=%s chat_id=%s topic_id=%s",
                user_id, chat_id, topic_id,
            )
        except Exception as e:
            logger.warning("Не удалось удалить сообщение: %s", e)
        return


async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/all - отметить всех, кого имеет смысл позвать в ЭТОЙ теме:
    - в whitelist-теме - только тех, кто в её белом списке;
    - в открытой теме - всех пользователей, которых бот видел пишущими в
      этой группе (см. storage.list_seen_users и ограничение Bot API выше).
    Автор команды в упоминания не попадает.
    """
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    chat_id = update.effective_chat.id
    topic_id = get_topic_id(update)

    # Как и писать в теме, пользоваться /all может только тот, кому там
    # разрешено писать. От остальных команду молча игнорируем: их сообщение
    # всё равно удалит enforce_rules.
    if not storage.is_user_allowed(chat_id, topic_id, user.id):
        return

    if storage.get_topic_mode(chat_id, topic_id) == "whitelist":
        rows = storage.list_allowed(chat_id, topic_id)
        nobody_msg = "В белом списке этой темы больше никого нет."
    else:
        rows = storage.list_seen_users(chat_id)
        nobody_msg = (
            "Отмечать некого: бот пока не видел в этой группе других участников. "
            "Он отмечает только тех, кто уже писал сообщения."
        )

    # не упоминаем самого автора команды
    rows = [(uid, uname) for uid, uname in rows if uid != user.id]

    if not rows:
        await msg.reply_text(nobody_msg)
        return

    # tg://user?id=<id> создаёт настоящее упоминание (с уведомлением) даже у
    # пользователей без @username - в отличие от текстового "@имя".
    mentions = [
        f'<a href="tg://user?id={uid}">{html.escape(uname or str(uid))}</a>'
        for uid, uname in rows
    ]

    thread_id = topic_id or None  # 0 (General) - это отсутствие темы для Bot API

    # Делим на части, чтобы не упереться в лимит длины сообщения Telegram
    # (4096 символов) при большом списке.
    chunk: list[str] = []
    chunk_len = 0
    for mention in mentions:
        if chunk and chunk_len + len(mention) + 1 > 3500:
            await context.bot.send_message(
                chat_id, " ".join(chunk), message_thread_id=thread_id, parse_mode=ParseMode.HTML
            )
            chunk, chunk_len = [], 0
        chunk.append(mention)
        chunk_len += len(mention) + 1

    if chunk:
        await context.bot.send_message(
            chat_id, " ".join(chunk), message_thread_id=thread_id, parse_mode=ParseMode.HTML
        )


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
    application.add_handler(CommandHandler("all", cmd_all), group=0)

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
