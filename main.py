import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
import json
from datetime import datetime, timedelta
import requests
from supabase import create_client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- Configuration ---
CPM1_API_KEY = "AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM"
CPM2_API_KEY = "AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ"
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 6915342860

SUPABASE_URL = os.getenv("SUPABASE_URL", os.getenv("VITE_SUPABASE_URL", ""))
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", os.getenv("VITE_SUPABASE_ANON_KEY", ""))

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY)

# --- Plan Definitions ---
PLANS = {
    "14_days": {"name": "14 Days", "price": "$0.50", "days": 14, "cents": 50},
    "30_days": {"name": "30 Days", "price": "$1.00", "days": 30, "cents": 100},
    "90_days": {"name": "90 Days", "price": "$3.00", "days": 90, "cents": 300},
    "unlimited": {"name": "Unlimited", "price": "$8.00", "days": None, "cents": 800},
}

# --- In-memory session state ---
sessions = {}
user_states = {}


# --- Utility Functions ---
def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def login_request(email, password, api_key):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    resp = requests.post(url, json=payload)
    return resp.json()


def update_request(id_token, api_key, new_email=None, new_password=None):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={api_key}"
    payload = {"idToken": id_token, "returnSecureToken": True}
    if new_email:
        payload["email"] = new_email
    if new_password:
        payload["password"] = new_password
    resp = requests.post(url, json=payload)
    return resp.json()


def box(title, lines):
    border = "\u2500" * 28
    body = ""
    for line in lines:
        body += f"  {line}\n"
    return f"{border}\n  {title}\n{border}\n{body}{border}"


# --- Authorization Check ---
def is_authorized(telegram_id):
    try:
        result = supabase.table("bot_authorized_users").select("*").eq(
            "telegram_id", telegram_id
        ).eq("is_active", True).maybe_single().execute()

        if not result.data:
            return False

        user = result.data
        if user.get("expiration_date"):
            exp = datetime.fromisoformat(user["expiration_date"].replace("Z", "+00:00"))
            if exp < datetime.now(exp.tzinfo):
                supabase.table("bot_authorized_users").update(
                    {"is_active": False, "updated_at": datetime.now().isoformat()}
                ).eq("telegram_id", telegram_id).execute()
                return False
        return True
    except Exception as e:
        print(f"Auth check error: {e}")
        return False


def is_admin(user_id):
    return user_id == ADMIN_ID


# --- Pricing Message ---
def build_pricing_message():
    text = (
        "\u2b50 *TNNR Premium Access*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Unlock full access to the account changer bot\\.\n\n"
        "\ud83d\udcce *Available Plans:*\n\n"
        "\ud83d\uddd3 *14 Days* \\- $0\\.50\n"
        "\ud83d\udcc5 *30 Days* \\- $1\\.00\n"
        "\ud83d\udcab *90 Days* \\- $3\\.00\n"
        "\ud83d\udc8e *Unlimited* \\- $8\\.00\n\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\ud83d\udc47 Select a plan below to purchase:"
    )
    keyboard = [
        [InlineKeyboardButton("\ud83d\uddd3 14 Days \u2014 $0.50", callback_data="buy_14_days")],
        [InlineKeyboardButton("\ud83d\udcc5 30 Days \u2014 $1.00", callback_data="buy_30_days")],
        [InlineKeyboardButton("\ud83d\udcab 90 Days \u2014 $3.00", callback_data="buy_90_days")],
        [InlineKeyboardButton("\ud83d\udc8e Unlimited \u2014 $8.00", callback_data="buy_unlimited")],
    ]
    return text, InlineKeyboardMarkup(keyboard)


# --- Main Menu ---
def build_menu(user_id):
    if user_id in sessions:
        keyboard = [
            [InlineKeyboardButton("\ud83d\udce7 Change Email", callback_data="changemail")],
            [InlineKeyboardButton("\ud83d\udd12 Change Password", callback_data="changepass")],
            [InlineKeyboardButton("\u2139\ufe0f Account Info", callback_data="accountinfo")],
            [InlineKeyboardButton("\ud83d\udc4b Logout", callback_data="logout")],
        ]
    else:
        keyboard = [[InlineKeyboardButton("\ud83d\udd11 Login", callback_data="login")]]
    return InlineKeyboardMarkup(keyboard)


# --- /start Command ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "User"

    if not is_admin(user_id) and not is_authorized(user_id):
        text, markup = build_pricing_message()
        await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=markup)
        return

    msg = box("\ud83c\udfae TNNR LOGIN CHANGER", [
        f"\ud83d\udc4b Welcome back, {user_name}!",
        "",
        "What this bot can do:",
        "",
        "\ud83d\udd11 Login to CPM1 / CPM2",
        "\ud83d\udce7 Change account email",
        "\ud83d\udd12 Change account password",
        "\u2139\ufe0f View account info",
        "",
        f"\ud83c\udd94 Your ID: {user_id}",
        f"\ud83d\udd50 Time: {get_timestamp()}",
        "",
        "\ud83d\udc47 Select an option below:",
    ])
    await update.message.reply_text(msg, reply_markup=build_menu(user_id))


# --- Admin: /add Command ---
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        msg = box("\ud83d\udccb COMMAND USAGE", ["/add <telegram_id>"])
        await update.message.reply_text(msg)
        return

    try:
        user_id = int(context.args[0])
        plan = context.args[1] if len(context.args) > 1 else "unlimited"

        plan_info = PLANS.get(plan, PLANS["unlimited"])
        exp_date = None
        if plan_info["days"]:
            exp_date = (datetime.now() + timedelta(days=plan_info["days"])).isoformat()

        supabase.table("bot_authorized_users").upsert({
            "telegram_id": user_id,
            "purchased_plan": plan,
            "purchase_date": datetime.now().isoformat(),
            "expiration_date": exp_date,
            "payment_id": "manual_admin",
            "is_active": True,
            "updated_at": datetime.now().isoformat(),
        }, on_conflict="telegram_id").execute()

        msg = box("\u2705 USER ADDED", [
            f"\ud83c\udd94 ID: {user_id}",
            f"\ud83d\udce6 Plan: {plan_info['name']}",
            f"\ud83d\udcc5 Expires: {exp_date or 'Never'}",
            f"\ud83d\udd50 Date: {get_timestamp()}",
        ])
        await update.message.reply_text(msg)

    except Exception as e:
        msg = box("\u274c ERROR", [f"Failed: {str(e)}"])
        await update.message.reply_text(msg)


# --- Admin: /remove Command ---
async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        msg = box("\ud83d\udccb COMMAND USAGE", ["/remove <telegram_id>"])
        await update.message.reply_text(msg)
        return

    try:
        user_id = int(context.args[0])

        if user_id == ADMIN_ID:
            msg = box("\ud83d\udee1\ufe0f PROTECTED", ["Cannot remove admin."])
            await update.message.reply_text(msg)
            return

        result = supabase.table("bot_authorized_users").select("id").eq(
            "telegram_id", user_id
        ).maybe_single().execute()

        if not result.data:
            msg = box("\ud83d\udd0d NOT FOUND", [f"ID {user_id} not in database."])
            await update.message.reply_text(msg)
            return

        supabase.table("bot_authorized_users").delete().eq("telegram_id", user_id).execute()

        if user_id in sessions:
            del sessions[user_id]

        msg = box("\ud83d\uddd1\ufe0f USER REMOVED", [
            f"\ud83c\udd94 ID: {user_id}",
            f"\ud83d\udd50 Time: {get_timestamp()}",
            "Access revoked.",
        ])
        await update.message.reply_text(msg)

    except Exception as e:
        msg = box("\u274c ERROR", [str(e)])
        await update.message.reply_text(msg)


# --- Admin: /users Command ---
async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    result = supabase.table("bot_authorized_users").select("*").execute()
    users = result.data or []

    if not users:
        msg = box("\ud83d\udced NO USERS", ["Database is empty."])
        await update.message.reply_text(msg)
        return

    now = datetime.now()
    lines = [f"\ud83d\udc65 Total: {len(users)}", ""]

    keyboard = []
    for u in users:
        tid = u["telegram_id"]
        plan = u.get("purchased_plan", "unknown")
        exp = u.get("expiration_date")

        if exp:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00")).replace(tzinfo=None)
            days_left = (exp_dt - now).days
            status = "\ud83d\udfe2 ACTIVE" if days_left > 0 else "\ud83d\udd34 EXPIRED"
            days_str = f"{days_left}d" if days_left > 0 else "EXPIRED"
        else:
            status = "\ud83d\udfe2 ACTIVE"
            days_str = "\u221e"
            exp = "Never"

        lines.append(f"{status} {tid}")
        lines.append(f"   Plan: {plan} | Left: {days_str}")
        lines.append("")

        keyboard.append([
            InlineKeyboardButton(f"\ud83d\uddd1 Remove {tid}", callback_data=f"admin_remove_{tid}")
        ])

    msg = box("\ud83d\udc65 AUTHORIZED USERS", lines)
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))


# --- Button Handler ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # --- Purchase buttons ---
    if data.startswith("buy_"):
        plan_key = data[4:]
        if plan_key not in PLANS:
            await query.edit_message_text("\u274c Invalid plan.")
            return

        plan_info = PLANS[plan_key]
        checkout_url = f"{SUPABASE_URL}/functions/v1/bot-checkout"

        try:
            resp = requests.post(checkout_url, json={
                "plan": plan_key,
                "telegram_id": user_id,
            }, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            })
            result = resp.json()

            if "url" in result:
                keyboard = [[InlineKeyboardButton(
                    f"\ud83d\udcb3 Pay {plan_info['price']}", url=result["url"]
                )]]
                msg = (
                    f"\ud83d\uded2 *Checkout: {plan_info['name']}*\n\n"
                    f"Amount: {plan_info['price']}\n"
                    f"Duration: {plan_info['days'] or 'Lifetime'} {'days' if plan_info['days'] else ''}\n\n"
                    "Click the button below to complete payment\\.\n"
                    "After payment, you'll receive a DM with your confirmation code\\."
                )
                await query.edit_message_text(
                    msg,
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            else:
                await query.edit_message_text(f"\u274c Error: {result.get('error', 'Unknown')}")
        except Exception as e:
            await query.edit_message_text(f"\u274c Payment error: {str(e)}")
        return

    # --- Admin remove button ---
    if data.startswith("admin_remove_"):
        if not is_admin(user_id):
            return
        target_id = int(data.replace("admin_remove_", ""))

        if target_id == ADMIN_ID:
            await query.edit_message_text("\ud83d\udee1\ufe0f Cannot remove admin.")
            return

        supabase.table("bot_authorized_users").delete().eq("telegram_id", target_id).execute()

        if target_id in sessions:
            del sessions[target_id]

        await query.edit_message_text(f"\u2705 User {target_id} removed successfully.")
        return

    # --- Setup flow buttons ---
    if data == "speak_admin":
        await query.edit_message_text(
            "\ud83d\udcac Contact @JustTnnr for manual setup assistance.\n\n"
            "Send them your Telegram ID and confirmation code."
        )
        return

    if data == "enter_telegram_id":
        user_states[user_id] = "awaiting_telegram_id"
        await query.edit_message_text(
            "\ud83c\udd94 *Get Your Telegram ID*\n\n"
            "1\\. Open @userinfotg2bot\n"
            "2\\. Start it to get your ID\n"
            "3\\. Paste your numeric ID below:",
            parse_mode="MarkdownV2",
        )
        return

    # --- Authorization check for protected actions ---
    if not is_admin(user_id) and not is_authorized(user_id):
        text, markup = build_pricing_message()
        await query.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=markup)
        return

    # --- Protected bot actions ---
    if data == "login":
        keyboard = [
            [InlineKeyboardButton("\ud83d\ude97 CPM1 (Car Parking)", callback_data="login_CPM1")],
            [InlineKeyboardButton("\ud83c\udfce\ufe0f CPM2 (New Version)", callback_data="login_CPM2")],
        ]
        msg = box("\ud83c\udfae GAME SELECTION", [
            "Choose which game account",
            "you want to login to:",
            "",
            "\ud83d\ude97 CPM1 - Car Parking Multiplayer",
            "\ud83c\udfce\ufe0f CPM2 - New Version",
        ])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("login_"):
        game = data.split("_")[1]
        context.user_data["login_game"] = game
        context.user_data["api_key"] = CPM1_API_KEY if game == "CPM1" else CPM2_API_KEY
        context.user_data["step"] = "email"
        msg = box(f"\ud83d\udd11 LOGGING INTO: {game}", [
            f"\ud83c\udfae Game: {'Car Parking Multiplayer' if game == 'CPM1' else 'CPM2 New Version'}",
            "",
            "\ud83d\udce7 Please enter your email below:",
        ])
        await query.edit_message_text(msg)

    elif data == "accountinfo":
        if user_id not in sessions:
            msg = box("\u26a0\ufe0f NOT LOGGED IN", ["Please login first."])
            await query.edit_message_text(msg, reply_markup=build_menu(user_id))
            return
        s = sessions[user_id]
        msg = box("\u2139\ufe0f ACCOUNT INFO", [
            f"\ud83d\udce7 Email: {s['email']}",
            f"\ud83c\udfae Game: {s['game_name']}",
            f"\ud83c\udd94 Your ID: {user_id}",
            "\ud83d\udfe2 Status: Active",
        ])
        await query.edit_message_text(msg, reply_markup=build_menu(user_id))

    elif data == "changemail":
        if user_id not in sessions:
            msg = box("\u26a0\ufe0f NOT LOGGED IN", ["Login first."])
            await query.edit_message_text(msg, reply_markup=build_menu(user_id))
            return
        context.user_data["step"] = "changemail"
        s = sessions[user_id]
        msg = box("\ud83d\udce7 CHANGE EMAIL", [
            f"\ud83d\udccc Current: {s['email']}",
            "",
            "\u270f\ufe0f Type your NEW email below:",
        ])
        await query.edit_message_text(msg)

    elif data == "changepass":
        if user_id not in sessions:
            msg = box("\u26a0\ufe0f NOT LOGGED IN", ["Login first."])
            await query.edit_message_text(msg, reply_markup=build_menu(user_id))
            return
        context.user_data["step"] = "changepass"
        s = sessions[user_id]
        msg = box("\ud83d\udd12 CHANGE PASSWORD", [
            f"\ud83d\udce7 Account: {s['email']}",
            "",
            "\u270f\ufe0f Type your NEW password below:",
        ])
        await query.edit_message_text(msg)

    elif data == "logout":
        if user_id in sessions:
            email = sessions[user_id]["email"]
            del sessions[user_id]
            msg = box("\ud83d\udc4b LOGGED OUT", [
                f"\ud83d\udce7 {email}",
                "Session ended.",
                "Use /start to login again.",
            ])
            await query.edit_message_text(msg, reply_markup=build_menu(user_id))
        else:
            msg = box("\u26a0\ufe0f NOT LOGGED IN", ["No active session."])
            await query.edit_message_text(msg, reply_markup=build_menu(user_id))


# --- Message Handler ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    step = context.user_data.get("step")

    # --- Check for forwarded confirmation message ---
    if update.message.forward_date and "TNNR-" in (text or ""):
        await handle_forwarded_confirmation(update, context)
        return

    # --- Awaiting Telegram ID input for setup ---
    if user_states.get(user_id) == "awaiting_telegram_id":
        await handle_telegram_id_input(update, context)
        return

    # --- Authorization check ---
    if not is_admin(user_id) and not is_authorized(user_id):
        pricing_text, markup = build_pricing_message()
        await update.message.reply_text(pricing_text, parse_mode="MarkdownV2", reply_markup=markup)
        return

    # --- Protected command steps ---
    if step == "email":
        context.user_data["email"] = text
        context.user_data["step"] = "password"
        msg = box("\ud83d\udd12 PASSWORD REQUIRED", [
            f"\ud83d\udce7 Email: {text}",
            "\u2705 Email received!",
            "",
            "\ud83d\udd11 Now enter your password:",
        ])
        await update.message.reply_text(msg)

    elif step == "password":
        email = context.user_data["email"]
        password = text
        api_key = context.user_data["api_key"]
        game_name = context.user_data["login_game"]

        loading_msg = box("\u23f3 AUTHENTICATING...", [
            f"\ud83d\udce7 Email: {email}",
            f"\ud83c\udfae Game: {game_name}",
            "\u23f3 Please wait...",
        ])
        loading = await update.message.reply_text(loading_msg)
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(2)

        resp = login_request(email, password, api_key)
        if "idToken" not in resp:
            error_msg = resp.get("error", {}).get("message", "Unknown error")
            fail_text = box("\u274c LOGIN FAILED", [
                f"\ud83d\udce7 Email: {email}",
                f"\u26a0\ufe0f Error: {error_msg}",
            ])
            await loading.edit_text(fail_text, reply_markup=build_menu(user_id))
            context.user_data.clear()
            return

        sessions[user_id] = {
            "id_token": resp["idToken"],
            "email": resp.get("email", email),
            "game_name": game_name,
            "api_key": api_key,
        }
        success_text = box("\u2705 LOGIN SUCCESSFUL", [
            f"\ud83d\udce7 Email: {sessions[user_id]['email']}",
            f"\ud83c\udfae Game: {game_name}",
            f"\ud83d\udd50 Time: {get_timestamp()}",
            "\ud83d\udfe2 Status: Active",
        ])
        await loading.edit_text(success_text, reply_markup=build_menu(user_id))
        context.user_data.clear()

    elif step == "changemail":
        if user_id not in sessions:
            msg = box("\u26a0\ufe0f NOT LOGGED IN", ["Please login first."])
            await update.message.reply_text(msg, reply_markup=build_menu(user_id))
            return
        new_email = text
        s = sessions[user_id]

        proc = await update.message.reply_text(box("\u23f3 UPDATING EMAIL...", ["\u23f3 Please wait..."]))
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(1.5)

        change_resp = update_request(s["id_token"], s["api_key"], new_email=new_email)
        if "email" in change_resp:
            old_email = s["email"]
            s["email"] = change_resp["email"]
            s["id_token"] = change_resp.get("idToken", s["id_token"])
            success_text = box("\u2705 EMAIL UPDATED", [
                f"\ud83d\udce7 Old: {old_email}",
                f"\ud83d\udce7 New: {s['email']}",
                f"\ud83c\udfae Game: {s['game_name']}",
            ])
            await proc.edit_text(success_text, reply_markup=build_menu(user_id))
        else:
            error_msg = change_resp.get("error", {}).get("message", "Unknown error")
            fail_text = box("\u274c EMAIL CHANGE FAILED", [f"\u26a0\ufe0f Error: {error_msg}"])
            await proc.edit_text(fail_text, reply_markup=build_menu(user_id))
        context.user_data.clear()

    elif step == "changepass":
        if user_id not in sessions:
            msg = box("\u26a0\ufe0f NOT LOGGED IN", ["Please login first."])
            await update.message.reply_text(msg, reply_markup=build_menu(user_id))
            return
        new_pass = text
        s = sessions[user_id]

        proc = await update.message.reply_text(box("\u23f3 UPDATING PASSWORD...", ["\u23f3 Please wait..."]))
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(1.5)

        change_resp = update_request(s["id_token"], s["api_key"], new_password=new_pass)
        if "idToken" in change_resp:
            s["id_token"] = change_resp["idToken"]
            success_text = box("\u2705 PASSWORD CHANGED", [
                f"\ud83d\udce7 Account: {s['email']}",
                f"\ud83c\udfae Game: {s['game_name']}",
                "\ud83d\udd11 Remember your new password!",
            ])
            await proc.edit_text(success_text, reply_markup=build_menu(user_id))
        else:
            error_msg = change_resp.get("error", {}).get("message", "Unknown error")
            fail_text = box("\u274c PASSWORD CHANGE FAILED", [f"\u26a0\ufe0f Error: {error_msg}"])
            await proc.edit_text(fail_text, reply_markup=build_menu(user_id))
        context.user_data.clear()


# --- Forwarded Confirmation Handler ---
async def handle_forwarded_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""

    # Extract confirmation code from forwarded message
    code = None
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("TNNR-"):
            code = line
            break

    if not code:
        await update.message.reply_text("\u274c Could not find a valid confirmation code in that message.")
        return
            # Verify the code exists and hasn't been used
    result = supabase.table("bot_payments").select("*").eq(
        "confirmation_code", code
    ).eq("status", "completed").maybe_single().execute()

    if not result.data:
        await update.message.reply_text("\u274c Invalid or expired confirmation code.")
        return

    payment = result.data
    if payment.get("confirmation_used"):
        await update.message.reply_text("\u274c This confirmation code has already been used.")
        return

    # Mark as used
    supabase.table("bot_payments").update({
        "confirmation_used": True,
        "updated_at": datetime.now().isoformat(),
    }).eq("confirmation_code", code).execute()

    # Store payment info for setup
    context.user_data["pending_payment"] = payment

    keyboard = [
        [InlineKeyboardButton("\ud83d\udcac Speak With Admin", callback_data="speak_admin")],
        [InlineKeyboardButton("\ud83c\udd94 Enter Telegram ID", callback_data="enter_telegram_id")],
    ]
    msg = (
        "\u2705 *Confirmation Verified\\!*\n\n"
        "DM @JustTnnr for manual setup assistance OR continue automatic setup below\\.\n\n"
        "\ud83d\udc47 Choose an option:"
    )
    await update.message.reply_text(
        msg, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# --- Telegram ID Input Handler ---
async def handle_telegram_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    del user_states[user_id]

    if not text.isdigit():
        await update.message.reply_text(
            "\u274c Invalid Telegram ID. Must be numeric.\n\n"
            "Get your ID from @userinfotg2bot and try again."
        )
        return

    target_telegram_id = int(text)
    payment = context.user_data.get("pending_payment")

    if not payment:
        # If no pending payment, just use the provided ID with current user's last payment
        result = supabase.table("bot_payments").select("*").eq(
            "telegram_id", user_id
        ).eq("status", "completed").eq("confirmation_used", True).order(
            "created_at", desc=True
        ).limit(1).maybe_single().execute()

        if not result.data:
            await update.message.reply_text("\u274c No verified payment found. Please complete payment first.")
            return
        payment = result.data

    plan_key = payment["plan"]
    plan_info = PLANS.get(plan_key, PLANS["unlimited"])
    exp_date = None
    if plan_info["days"]:
        exp_date = (datetime.now() + timedelta(days=plan_info["days"])).isoformat()

    # Add user to authorized users
    supabase.table("bot_authorized_users").upsert({
        "telegram_id": target_telegram_id,
        "purchased_plan": plan_key,
        "purchase_date": datetime.now().isoformat(),
        "expiration_date": exp_date,
        "payment_id": payment.get("stripe_session_id", "unknown"),
        "confirmation_code": payment.get("confirmation_code"),
        "is_active": True,
        "updated_at": datetime.now().isoformat(),
    }, on_conflict="telegram_id").execute()

    context.user_data.pop("pending_payment", None)

    exp_display = exp_date[:10] if exp_date else "Never"
    msg = box("\u2705 ACCOUNT ACTIVATED", [
        f"\ud83c\udd94 Telegram ID: {target_telegram_id}",
        f"\ud83d\udce6 Plan: {plan_info['name']}",
        f"\ud83d\udcc5 Expires: {exp_display}",
        "",
        "You now have full access!",
        "Use /start to begin.",
    ])
    await update.message.reply_text(msg)


# --- App Setup ---
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
