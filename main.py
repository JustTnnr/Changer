import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
from datetime import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

CPM1_API_KEY = "AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM"
CPM2_API_KEY = "AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ"
BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 8650959684

DATA_DIR = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, "users.txt")

if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r") as f:
        allowed_users = set(int(x.strip()) for x in f if x.strip())
else:
    allowed_users = set()

allowed_users.add(ADMIN_ID)


def save_users():
    with open(USERS_FILE, "w") as f:
        for uid in allowed_users:
            f.write(f"{uid}\n")


def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def box(title, lines):
    w = 40
    border = "+" + "-" * w + "+"
    title_line = "|" + f"  {title}".ljust(w) + "|"
    sep = "|" + "-" * w + "|"
    body = ""
    for line in lines:
        body += "|" + f"  {line}".ljust(w) + "|\n"
    return f"```\n{border}\n{title_line}\n{sep}\n{body}{border}\n```"


sessions = {}
user_states = {}


def build_menu(user_id):
    if user_id in sessions:
        keyboard = [
            [InlineKeyboardButton("Change Email", callback_data="changemail")],
            [InlineKeyboardButton("Change Password", callback_data="changepass")],
            [InlineKeyboardButton("Account Info", callback_data="accountinfo")],
            [InlineKeyboardButton("Logout", callback_data="logout")],
        ]
    else:
        keyboard = [[InlineKeyboardButton("Login", callback_data="login")]]
    return InlineKeyboardMarkup(keyboard)


def is_allowed(user_id):
    return user_id in allowed_users


async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        msg = box("COMMAND USAGE", [
            "/add <telegram_id>",
            "",
            "Tip: Get a user's ID by",
            "forwarding their message to",
            "@userinfobot",
        ])
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    try:
        user_id = int(context.args[0])

        if user_id in allowed_users:
            msg = box("USER ALREADY EXISTS", [
                f"ID: {user_id}",
                "",
                "This user is already in",
                "the whitelist.",
            ])
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        allowed_users.add(user_id)
        save_users()

        msg = box("USER SUCCESSFULLY ADDED", [
            f"ID: {user_id}",
            f"Date: {get_timestamp()}",
            f"Total Users: {len(allowed_users)}",
            "",
            "User can now use /start to",
            "access the bot.",
        ])
        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception:
        msg = box("ERROR", [
            "Invalid Telegram ID format.",
            "Please use numbers only.",
        ])
        await update.message.reply_text(msg, parse_mode="Markdown")


async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        msg = box("COMMAND USAGE", [
            "/remove <telegram_id>",
            "",
            "This will revoke access",
            "and end active sessions.",
        ])
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    try:
        user_id = int(context.args[0])

        if user_id == ADMIN_ID:
            msg = box("PROTECTION ACTIVE", [
                "Cannot remove admin account.",
                "This action is prohibited.",
            ])
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        if user_id not in allowed_users:
            msg = box("USER NOT FOUND", [
                f"ID: {user_id}",
                "",
                "This user is not in the",
                "whitelist.",
                "",
                "Use /users to see all",
                "registered users.",
            ])
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        allowed_users.remove(user_id)
        save_users()

        was_online = user_id in sessions
        if user_id in sessions:
            del sessions[user_id]

        msg = box("USER SUCCESSFULLY REMOVED", [
            f"ID: {user_id}",
            f"Date: {get_timestamp()}",
            f"Remaining Users: {len(allowed_users)}",
            f"Was Online: {'Yes' if was_online else 'No'}",
            "",
            "User's session has been",
            "terminated if active.",
        ])
        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception:
        msg = box("ERROR", [
            "Invalid Telegram ID format.",
            "Please use numbers only.",
        ])
        await update.message.reply_text(msg, parse_mode="Markdown")


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not allowed_users:
        msg = box("NO USERS REGISTERED", [
            "Use /add <id> to register",
            "new users.",
        ])
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    online_count = sum(1 for uid in allowed_users if uid in sessions)
    offline_count = len(allowed_users) - online_count

    lines = [
        f"Total: {len(allowed_users)}",
        f"Online: {online_count}",
        f"Offline: {offline_count}",
        "",
    ]
    for uid in sorted(allowed_users):
        if uid in sessions:
            game = sessions[uid].get("game_name", "N/A")
            lines.append(f"[ON]  {uid} | {game}")
        else:
            lines.append(f"[OFF] {uid} | Inactive")
    lines.append("")
    lines.append(f"Updated: {get_timestamp()}")

    msg = box("REGISTERED USERS", lines)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "User"

    if not is_allowed(user_id):
        msg = box("ACCESS DENIED", [
            "You are not authorized to",
            "use this bot.",
            "",
            f"Your ID: {user_id}",
            "",
            "Send this ID to the admin",
            "to request access.",
        ])
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    msg = box("TNNR LOGIN CHANGER", [
        f"Welcome back, {user_name}!",
        "",
        "What this bot can do:",
        "",
        "- Login to CPM1 / CPM2",
        "- Change account email",
        "- Change account password",
        "- View account info",
        "",
        f"Your ID: {user_id}",
        f"Time: {get_timestamp()}",
        "",
        "Select an option below:",
    ])
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=build_menu(user_id),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_allowed(user_id):
        msg = box("UNAUTHORIZED", [
            "Your access has been revoked",
            "or you were never authorized.",
            "",
            f"Your ID: {user_id}",
            "Contact admin for access.",
        ])
        await query.edit_message_text(msg, parse_mode="Markdown")
        return

    if data == "login":
        keyboard = [
            [InlineKeyboardButton("CPM1 (Car Parking)", callback_data="login_CPM1")],
            [InlineKeyboardButton("CPM2 (New Version)", callback_data="login_CPM2")],
        ]
        msg = box("GAME SELECTION", [
            "Choose which game account",
            "you want to login to:",
            "",
            "CPM1 - Car Parking Multiplayer",
            "CPM2 - New Version",
            "",
            "Make sure you have your",
            "login credentials ready.",
        ])
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("login_"):
        game = data.split("_")[1]
        context.user_data["login_game"] = game
        context.user_data["api_key"] = CPM1_API_KEY if game == "CPM1" else CPM2_API_KEY
        context.user_data["step"] = "email"
        game_full = "Car Parking Multiplayer" if game == "CPM1" else "CPM2 New Version"
        msg = box(f"LOGGING INTO: {game}", [
            f"Game: {game_full}",
            "",
            "Please enter your email",
            "address below:",
        ])
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif data == "accountinfo":
        if user_id not in sessions:
            msg = box("NOT LOGGED IN", [
                "Please login first.",
            ])
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=build_menu(user_id))
            return
        s = sessions[user_id]
        msg = box("ACCOUNT INFORMATION", [
            f"Email: {s['email']}",
            f"Game: {s['game_name']}",
            f"Your ID: {user_id}",
            f"Session Time: {get_timestamp()}",
            "Status: Active",
            "",
            "You can change your email or",
            "password using the buttons.",
        ])
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=build_menu(user_id))

    elif data == "changemail":
        if user_id not in sessions:
            msg = box("NOT LOGGED IN", [
                "You must login first before",
                "changing your email.",
            ])
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=build_menu(user_id))
            return
        context.user_data["step"] = "changemail"
        s = sessions[user_id]
        msg = box("CHANGE EMAIL", [
            f"Current: {s['email']}",
            f"Game: {s['game_name']}",
            "",
            "Type your NEW email below:",
            "",
            "Make sure it's a valid email",
            "that you have access to.",
        ])
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif data == "changepass":
        if user_id not in sessions:
            msg = box("NOT LOGGED IN", [
                "You must login first before",
                "changing your password.",
            ])
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=build_menu(user_id))
            return
        context.user_data["step"] = "changepass"
        s = sessions[user_id]
        msg = box("CHANGE PASSWORD", [
            f"Account: {s['email']}",
            f"Game: {s['game_name']}",
            "",
            "Type your NEW password below:",
            "",
            "Tips:",
            "- Use 6+ characters",
            "- Mix letters and numbers",
            "- Avoid common passwords",
        ])
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif data == "logout":
        if user_id in sessions:
            email = sessions[user_id]["email"]
            game = sessions[user_id]["game_name"]
            del sessions[user_id]
            msg = box("LOGGED OUT", [
                f"Email: {email}",
                f"Game: {game}",
                f"Time: {get_timestamp()}",
                "",
                "Session ended successfully.",
                "",
                "Use /start to login again.",
            ])
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=build_menu(user_id))
        else:
            msg = box("NOT LOGGED IN", [
                "You are not currently logged",
                "into any account.",
            ])
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=build_menu(user_id))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    step = context.user_data.get("step")

    if not is_allowed(user_id):
        return

    if step == "email":
        context.user_data["email"] = text
        context.user_data["step"] = "password"
        msg = box("PASSWORD REQUIRED", [
            f"Email: {text}",
            "Email received!",
            "",
            "Now enter your password:",
        ])
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif step == "password":
        email = context.user_data["email"]
        password = text
        api_key = context.user_data["api_key"]
        game_name = context.user_data["login_game"]

        loading_msg = box("AUTHENTICATING...", [
            f"Email: {email}",
            f"Game: {game_name}",
            "",
            "Please wait...",
        ])
        loading = await update.message.reply_text(loading_msg, parse_mode="Markdown")

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(2)

        resp = login_request(email, password, api_key)
        if "idToken" not in resp:
            error_msg = resp.get("error", {}).get("message", "Unknown error")
            fail_text = box("LOGIN FAILED", [
                f"Email: {email}",
                f"Game: {game_name}",
                "",
                f"Error: {error_msg}",
                "",
                "Tips:",
                "- Check your email spelling",
                "- Verify your password",
                "- Make sure account exists",
            ])
            await loading.edit_text(fail_text, parse_mode="Markdown", reply_markup=build_menu(user_id))
            context.user_data.clear()
            return

        sessions[user_id] = {
            "id_token": resp["idToken"],
            "email": resp.get("email", email),
            "game_name": game_name,
            "api_key": api_key,
        }
        success_text = box("LOGIN SUCCESSFUL", [
            f"Email: {sessions[user_id]['email']}",
            f"Game: {game_name}",
            f"Time: {get_timestamp()}",
            "Status: Active",
            "",
            "Available Actions:",
            "- Change Email",
            "- Change Password",
            "- View Account Info",
            "- Logout",
        ])
        await loading.edit_text(
            success_text,
            parse_mode="Markdown",
            reply_markup=build_menu(user_id),
        )
        context.user_data.clear()

    elif step == "changemail":
        if user_id not in sessions:
            msg = box("NOT LOGGED IN", ["Please login first."])
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=build_menu(user_id))
            return
        new_email = text
        s = sessions[user_id]

        processing_msg = box("UPDATING EMAIL...", [
            f"New: {new_email}",
            "Please wait...",
        ])
        proc = await update.message.reply_text(processing_msg, parse_mode="Markdown")

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(1.5)

        change_resp = update_request(s["id_token"], s["api_key"], new_email=new_email)
        if "email" in change_resp:
            old_email = s["email"]
            s["email"] = change_resp["email"]
            s["id_token"] = change_resp.get("idToken", s["id_token"])
            success_text = box("EMAIL UPDATED", [
                f"Old: {old_email}",
                f"New: {s['email']}",
                f"Game: {s['game_name']}",
                f"Time: {get_timestamp()}",
                "",
                "Your email has been changed",
                "successfully. Use the new",
                "email to login next time.",
            ])
            await proc.edit_text(success_text, parse_mode="Markdown", reply_markup=build_menu(user_id))
        else:
            error_msg = change_resp.get("error", {}).get("message", "Unknown error")
            fail_text = box("EMAIL CHANGE FAILED", [
                f"Attempted: {new_email}",
                f"Error: {error_msg}",
                "",
                "Make sure the email is valid",
                "and not already in use.",
            ])
            await proc.edit_text(fail_text, parse_mode="Markdown", reply_markup=build_menu(user_id))
        context.user_data.clear()

    elif step == "changepass":
        if user_id not in sessions:
            msg = box("NOT LOGGED IN", ["Please login first."])
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=build_menu(user_id))
            return
        new_pass = text
        s = sessions[user_id]

        processing_msg = box("UPDATING PASSWORD...", [
            f"Account: {s['email']}",
            "Please wait...",
        ])
        proc = await update.message.reply_text(processing_msg, parse_mode="Markdown")

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(1.5)

        change_resp = update_request(s["id_token"], s["api_key"], new_password=new_pass)
        if "idToken" in change_resp:
            s["id_token"] = change_resp["idToken"]
            success_text = box("PASSWORD CHANGED", [
                f"Account: {s['email']}",
                f"Game: {s['game_name']}",
                f"Time: {get_timestamp()}",
                "",
                "Your password has been",
                "updated successfully!",
                "",
                "Remember your new password",
                "for your next login.",
            ])
            await proc.edit_text(success_text, parse_mode="Markdown", reply_markup=build_menu(user_id))
        else:
            error_msg = change_resp.get("error", {}).get("message", "Unknown error")
            fail_text = box("PASSWORD CHANGE FAILED", [
                f"Account: {s['email']}",
                f"Error: {error_msg}",
                "",
                "Password must be at least",
                "6 characters long.",
            ])
            await proc.edit_text(fail_text, parse_mode="Markdown", reply_markup=build_menu(user_id))
        context.user_data.clear()


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add", add_user))
app.add_handler(CommandHandler("remove", remove_user))
app.add_handler(CommandHandler("users", list_users))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

print("Bot is running...")
app.run_polling()
