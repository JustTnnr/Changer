import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
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

# ===== CONFIG =====
CPM1_API_KEY = "AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM"
CPM2_API_KEY = "AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ"
BOT_TOKEN = "8496323687:AAFyWCbdJqciZFFvLbj6GFEQVn4qVLR6x-c"

# ===== ADMIN CONFIG =====
ADMIN_ID = 8650959684

USERS_FILE = "users.txt"

# Load allowed users
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r") as f:
        allowed_users = set(int(x.strip()) for x in f if x.strip())
else:
    allowed_users = set()

# Always allow admin
allowed_users.add(ADMIN_ID)

def save_users():
    with open(USERS_FILE, "w") as f:
        for uid in allowed_users:
            f.write(f"{uid}\n")

# ===== ADMIN COMMANDS =====

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Usage: /add telegramid")
        return

    try:
        user_id = int(context.args[0])

        if user_id in allowed_users:
            await update.message.reply_text("User already exists.")
            return

        allowed_users.add(user_id)
        save_users()

        await update.message.reply_text(f"Added user: {user_id}")

    except Exception:
        await update.message.reply_text("Invalid Telegram ID")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Usage: /remove telegramid")
        return

    try:
        user_id = int(context.args[0])

        if user_id == ADMIN_ID:
            await update.message.reply_text("Cannot remove admin.")
            return

        if user_id not in allowed_users:
            await update.message.reply_text("User not found.")
            return

        allowed_users.remove(user_id)
        save_users()

        if user_id in sessions:
            del sessions[user_id]

        await update.message.reply_text(f"Removed user: {user_id}")

    except Exception:
        await update.message.reply_text("Invalid Telegram ID")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not allowed_users:
        await update.message.reply_text("No users.")
        return

    text = "Active Users:\n\n"

    for uid in sorted(allowed_users):
        status = "Online" if uid in sessions else "Offline"
        text += f"{uid} - {status}\n"

    await update.message.reply_text(text)

# ===== CPM FUNCTIONS =====
def login_request(email, password, api_key):
    url = f"https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    response = requests.post(url, json=payload)
    return response.json()

def update_request(id_token, api_key, new_email=None, new_password=None):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={api_key}"
    payload = {"idToken": id_token, "returnSecureToken": True}
    if new_email:
        payload["email"] = new_email
    if new_password:
        payload["password"] = new_password
    response = requests.post(url, json=payload)
    return response.json()

# ===== SESSIONS =====
sessions = {}      # user_id -> {id_token, email, game_name, api_key}
user_states = {}   # per-user step tracking

# ===== MENU HELPERS =====
def build_menu(user_id):
    if user_id in sessions:
        keyboard = [
            [InlineKeyboardButton("Change Email", callback_data="changemail")],
            [InlineKeyboardButton("Change Password", callback_data="changepass")],
            [InlineKeyboardButton("Logout", callback_data="logout")],
        ]
    else:
        keyboard = [[InlineKeyboardButton("Login", callback_data="login")]]
    return InlineKeyboardMarkup(keyboard)

# ===== ACCESS CHECK =====
def is_allowed(user_id):
    return user_id in allowed_users

# ===== START COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("You are not authorized to use this bot.")
        return

    await update.message.reply_text(
        "Welcome to Ash Change Tool Bot",
        reply_markup=build_menu(user_id),
    )

# ===== BUTTON HANDLER =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_allowed(user_id):
        await query.edit_message_text("Unauthorized.")
        return

    # ----- LOGIN FLOW -----
    if data == "login":
        keyboard = [
            [InlineKeyboardButton("CPM1", callback_data="login_CPM1")],
            [InlineKeyboardButton("CPM2", callback_data="login_CPM2")],
        ]
        await query.edit_message_text("Select game:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("login_"):
        game = data.split("_")[1]
        context.user_data["login_game"] = game
        context.user_data["api_key"] = CPM1_API_KEY if game == "CPM1" else CPM2_API_KEY
        context.user_data["step"] = "email"
        await query.edit_message_text(f"Enter your email for {game}:")

    # ----- CHANGE EMAIL -----
    elif data == "changemail":
        if user_id not in sessions:
            await query.edit_message_text("You must login first.")
            return
        context.user_data["step"] = "changemail"
        await query.edit_message_text("Enter new email:")

    # ----- CHANGE PASSWORD -----
    elif data == "changepass":
        if user_id not in sessions:
            await query.edit_message_text("You must login first.")
            return
        context.user_data["step"] = "changepass"
        await query.edit_message_text("Enter new password:")

    # ----- LOGOUT -----
    elif data == "logout":
        if user_id in sessions:
            del sessions[user_id]
            await query.edit_message_text("Logged out successfully.", reply_markup=build_menu(user_id))
        else:
            await query.edit_message_text("You are not logged in.", reply_markup=build_menu(user_id))

# ===== MESSAGE HANDLER =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    step = context.user_data.get("step")

    if not is_allowed(user_id):
        return

    # ----- EMAIL -----
    if step == "email":
        context.user_data["email"] = text
        context.user_data["step"] = "password"
        await update.message.reply_text("Now enter your password:")

    # ----- PASSWORD -----
    elif step == "password":
        email = context.user_data["email"]
        password = text
        api_key = context.user_data["api_key"]
        game_name = context.user_data["login_game"]

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(2)

        resp = login_request(email, password, api_key)
        if "idToken" not in resp:
            error_msg = resp.get("error", {}).get("message", "Unknown error")
            await update.message.reply_text(f"Login failed: {error_msg}", reply_markup=build_menu(user_id))
            context.user_data.clear()
            return

        sessions[user_id] = {
            "id_token": resp["idToken"],
            "email": resp.get("email", email),
            "game_name": game_name,
            "api_key": api_key,
        }
        await update.message.reply_text(
            f"Logged in as {sessions[user_id]['email']} ({game_name})",
            reply_markup=build_menu(user_id),
        )
        context.user_data.clear()

    # ----- CHANGE EMAIL -----
    elif step == "changemail":
        if user_id not in sessions:
            await update.message.reply_text("You must login first.", reply_markup=build_menu(user_id))
            return
        new_email = text
        s = sessions[user_id]

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(1.5)

        change_resp = update_request(s["id_token"], s["api_key"], new_email=new_email)
        if "email" in change_resp:
            s["email"] = change_resp["email"]
            s["id_token"] = change_resp.get("idToken", s["id_token"])
            await update.message.reply_text(f"Email updated to {s['email']}", reply_markup=build_menu(user_id))
        else:
            error_msg = change_resp.get("error", {}).get("message", "Unknown error")
            await update.message.reply_text(f"Failed: {error_msg}", reply_markup=build_menu(user_id))
        context.user_data.clear()

    # ----- CHANGE PASSWORD -----
    elif step == "changepass":
        if user_id not in sessions:
            await update.message.reply_text("You must login first.", reply_markup=build_menu(user_id))
            return
        new_pass = text
        s = sessions[user_id]

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(1.5)

        change_resp = update_request(s["id_token"], s["api_key"], new_password=new_pass)
        if "idToken" in change_resp:
            s["id_token"] = change_resp["idToken"]
            await update.message.reply_text("Password changed successfully", reply_markup=build_menu(user_id))
        else:
            error_msg = change_resp.get("error", {}).get("message", "Unknown error")
            await update.message.reply_text(f"Failed: {error_msg}", reply_markup=build_menu(user_id))
        context.user_data.clear()

# ===== BOT STARTUP =====
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add", add_user))
app.add_handler(CommandHandler("remove", remove_user))
app.add_handler(CommandHandler("users", list_users))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

print("Bot is running...")
app.run_polling()

