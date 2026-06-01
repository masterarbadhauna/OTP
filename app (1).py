import asyncio
import re
import requests
import csv
import os
import json
import random
import logging
import time
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.error import TimedOut, NetworkError, RetryAfter
from datetime import datetime
import phonenumbers
from phonenumbers import geocoder

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING
)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("telegram").setLevel(logging.ERROR)


# ==================  CONFIG ==================

BOT_TOKEN = "fill your bot token"
API_URL = "http://147.135.212.197/crapi/st/viewstats?token=R1dURklBUzR3kpNfiIuJaIdmlHNeZWFEc5N0U0VsjGtKiXBIZ5h5hA=="
DEV_USERNAME = "@saturogojo072"
BOT_NAME = "HEART HUB"
BOT_USERNAME = "@heart2otp2bot"

ADMIN_IDS = [8443825601, 8696522674, 8574635657]
CHAT_IDS = [-1003321483444, -1003784469446, -1003321483444, -1003676039095, -1002677861985, -1003799538629, -1003642471260, -1003586051721, -1003522290714, -1003520302736, -1003371226768, -1003265732950, -1003083894704, -1002711672082, -1003844386133, -1003392531680]
AUTO_DELETE_CHATS = [-1003784469446, -1002502260850]

REQUIRED_CHANNELS = [
    ("📢 Main Channel", "https://t.me/synervsms", -1003310107186),
]

AUTO_POST_CHANNEL  = "@synervsms"
NUMBER_CHANNEL_ID  = -1003844386133

OTP_EARN_PER_OTP      = 0.01
REFERRAL_EARN_PER_OTP = 0.001
MIN_WITHDRAW          = 10.00

DATA_DIR           = 'bot_data'
COUNTRIES_FILE     = os.path.join(DATA_DIR, 'countries.json')
USER_NUMBERS_FILE  = os.path.join(DATA_DIR, 'user_numbers.json')
ASSIGNED_FILE      = os.path.join(DATA_DIR, 'assigned_numbers.json')
OTP_HISTORY_FILE   = os.path.join(DATA_DIR, 'otp_history.json')
USER_STATS_FILE    = os.path.join(DATA_DIR, 'user_stats.json')
REFERRAL_FILE      = os.path.join(DATA_DIR, 'referrals.json')
BALANCE_FILE       = os.path.join(DATA_DIR, 'balances.json')
OTP_USED_FILE      = os.path.join(DATA_DIR, 'otp_used_numbers.json')

# ---- runtime state ----
PENDING_COUNTRY  = {}   # {user_id: "awaiting_name" | str}
PENDING_UPLOAD   = {}   # {user_id: {country, file_id, services_selected: set()}}
live_traffic     = {}
_full_sms_cache  = {}
last_number      = None
_api2_last_dt    = None
_api3_last_dt    = None
_api4_last_dt    = None
_api5_last_dt    = None
_api6_last_dt    = None

# All services supported
ALL_SERVICES = ["WhatsApp", "Rednote", "Telegram", "Facebook", "TikTok", "IMO"]
SERVICE_EMOJI_BTN = {
    "WhatsApp": "📱", "Rednote": "📕", "Telegram": "✈️",
    "Facebook": "📘", "TikTok": "🎵",  "IMO": "💬",
}

bot = Bot(token=BOT_TOKEN)

# ============================================================
# Colored Button Helper — Bot API 9.4 (via api_kwargs workaround)
# style: "primary" (blue), "success" (green), "danger" (red)
# ============================================================
def btn(text, callback_data=None, url=None, style=None):
    """Create InlineKeyboardButton with optional color style"""
    kwargs = {}
    if style:
        kwargs['api_kwargs'] = {"style": style}
    if url:
        return InlineKeyboardButton(text, url=url, **kwargs)
    return InlineKeyboardButton(text, callback_data=callback_data, **kwargs)

# =============================================

def init_data_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    for fp, default in [
        (COUNTRIES_FILE, {}), (USER_NUMBERS_FILE, {}), (ASSIGNED_FILE, {}),
        (OTP_HISTORY_FILE, {}), (USER_STATS_FILE, {}),
        (REFERRAL_FILE, {}), (BALANCE_FILE, {}), (OTP_USED_FILE, []),
    ]:
        if not os.path.exists(fp):
            with open(fp, 'w') as f:
                json.dump(default, f, indent=2)

def load_json(fp):
    try:
        with open(fp, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_json(fp, data):
    with open(fp, 'w') as f:
        json.dump(data, f, indent=2)

# ============================================================
# Countries — NEW structure: {country: {service: [numbers]}}
# ============================================================
def get_countries_data():
    """Returns {country: {service: [nums]}}"""
    return load_json(COUNTRIES_FILE)

def get_services_for_country(country):
    """Return list of services that have numbers for a country"""
    data = get_countries_data()
    if country not in data:
        return []
    cd = data[country]
    # Support both old format (list) and new format (dict)
    if isinstance(cd, list):
        return ["WhatsApp"]  # legacy
    return [svc for svc, nums in cd.items() if nums]

def get_countries_with_services():
    """Returns {country: [services_with_numbers]}"""
    data = get_countries_data()
    result = {}
    for country, cd in data.items():
        if isinstance(cd, list):
            if cd:
                result[country] = ["WhatsApp"]
        elif isinstance(cd, dict):
            svcs = [s for s, nums in cd.items() if nums]
            if svcs:
                result[country] = svcs
    return result

def add_numbers_to_country_service(country, service, numbers):
    """Add numbers to country→service bucket"""
    data = get_countries_data()
    if country not in data:
        data[country] = {}
    # Migrate old list format
    if isinstance(data[country], list):
        old = data[country]
        data[country] = {"WhatsApp": old}
    if service not in data[country]:
        data[country][service] = []
    existing = set(data[country][service])
    new = [n for n in numbers if n not in existing]
    data[country][service].extend(new)
    save_json(COUNTRIES_FILE, data)
    return len(new), len(data[country][service])

def get_numbers_for_country_service(country, service):
    data = get_countries_data()
    if country not in data:
        return []
    cd = data[country]
    if isinstance(cd, list):
        return cd if service == "WhatsApp" else []
    return cd.get(service, [])

def get_all_numbers_for_country(country):
    """All numbers across all services for a country"""
    data = get_countries_data()
    if country not in data:
        return []
    cd = data[country]
    if isinstance(cd, list):
        return cd
    all_nums = []
    for nums in cd.values():
        all_nums.extend(nums)
    return all_nums

# ============================================================
# Number Assignment — 1 per user, skip OTP-used numbers
# ============================================================
def get_otp_used_numbers():
    try:
        data = load_json(OTP_USED_FILE)
        return set(data) if isinstance(data, list) else set()
    except:
        return set()

def mark_number_otp_used(number):
    used = get_otp_used_numbers()
    used.add(number)
    save_json(OTP_USED_FILE, list(used))

def get_unique_numbers_for_user(country, service, count=1):
    all_nums = get_numbers_for_country_service(country, service)
    if not all_nums:
        return []
    assigned = load_json(ASSIGNED_FILE)
    key = f"{country}_{service}"
    assigned_set = set(assigned.get(key, []))
    otp_used = get_otp_used_numbers()

    # Skip already assigned AND otp-received numbers
    available = [n for n in all_nums if n not in assigned_set and n not in otp_used]

    if not available:
        # Reset assigned (not otp_used) and try again
        assigned[key] = []
        save_json(ASSIGNED_FILE, assigned)
        available = [n for n in all_nums if n not in otp_used]

    if not available:
        return []

    selected = random.sample(available, min(count, len(available)))
    assigned.setdefault(key, []).extend(selected)
    save_json(ASSIGNED_FILE, assigned)
    return selected

# ============================================================
# Balance
# ============================================================
def get_balance(user_id):
    b = load_json(BALANCE_FILE)
    return b.get(str(user_id), 0.0)

def add_balance(user_id, amount):
    b = load_json(BALANCE_FILE)
    uid = str(user_id)
    b[uid] = round(b.get(uid, 0.0) + amount, 4)
    save_json(BALANCE_FILE, b)
    return b[uid]

def get_referrer(user_id):
    refs = load_json(REFERRAL_FILE)
    return refs.get(str(user_id), {}).get("referred_by")

# ============================================================
# Admin IDs / Chat IDs helpers
# ============================================================
def load_admin_ids():
    return ADMIN_IDS.copy()

def save_admin_ids(ids):
    global ADMIN_IDS
    ADMIN_IDS = ids
    _update_var_in_file('ADMIN_IDS', ids)

def load_chat_ids():
    return CHAT_IDS.copy()

def save_chat_ids(ids):
    global CHAT_IDS
    CHAT_IDS = ids
    _update_var_in_file('CHAT_IDS', ids)

def load_auto_delete_chats():
    return AUTO_DELETE_CHATS.copy()

def save_auto_delete_chats(ids):
    global AUTO_DELETE_CHATS
    AUTO_DELETE_CHATS = ids
    _update_var_in_file('AUTO_DELETE_CHATS', ids)

def _update_var_in_file(var_name, ids_list):
    try:
        with open('app.py', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.strip().startswith(f'{var_name} = ['):
                lines[i] = f'{var_name} = [{", ".join(map(str, ids_list))}]\n'
                break
        with open('app.py', 'w', encoding='utf-8') as f:
            f.writelines(lines)
    except Exception as e:
        print(f"File update error: {e}")

# ============================================================
# Retry helper
# ============================================================
async def safe_send(coro_func, retries=3, delay=2):
    for attempt in range(retries):
        try:
            return await coro_func()
        except TimedOut:
            if attempt < retries - 1:
                await asyncio.sleep(delay)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except NetworkError:
            if attempt < retries - 1:
                await asyncio.sleep(delay)
        except Exception as e:
            err = str(e).lower()
            # Blocked / deleted / deactivated users — silently skip
            if any(x in err for x in ["forbidden", "blocked", "deactivated", "not found", "chat not found", "user not found"]):
                return None  # silent skip
            print(f"[safe_send] {e}")
            break
    return None

# ============================================================
# Subscription check
# ============================================================
async def check_subscription(user_id):
    for name, link, chat_id in REQUIRED_CHANNELS:
        if chat_id is None:
            continue
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            print(f"[SUB CHECK] {name} | user={user_id} | status={member.status}")
            if member.status in ['left', 'kicked', 'banned']:
                return False
        except Exception as e:
            print(f"[SUB CHECK ERROR] {name} | chat_id={chat_id} | user={user_id} | error={e}")
            return False
    return True

# ============================================================
# OTP / Message utilities
# ============================================================
def fetch_latest_otp():
    try:
        res = requests.get(API_URL, timeout=10)
        res.raise_for_status()
        data = res.json()
        if not isinstance(data, list) or not data:
            return None
        latest = data[0]
        if len(latest) < 4:
            return None
        return {"source": "api1", "service": latest[0] or "Unknown",
                "number": latest[1] or "N/A", "message": latest[2] or "",
                "time": latest[3] or "N/A"}
    except:
        return None

def fetch_api2():
    try:
        url = "http://137.74.1.203/zonecr/reseller/mdr.php?token=Qk9UQkZRfkJGTlI="
        res = requests.get(url, timeout=15)
        if not res.text.strip():
            return []
        data = res.json()
        if not isinstance(data, dict):
            return []
        if data.get("status", "").lower() != "success":
            return []
        import html
        result = []
        for r in data.get("data", []):
            msg = html.unescape(r.get("message", ""))
            result.append({
                "source": "api2",
                "service": r.get("cli", "Unknown"),
                "number":  r.get("number", "N/A"),
                "message": msg,
                "time":    r.get("datetime", "N/A")
            })
        return result
    except Exception as e:
        print(f"[API2] {e}")
        return []

def fetch_api4():
    """New MDR API — http://137.74.1.203/crapi/reseller/mdr.php"""
    try:
        import html
        url = "http://137.74.1.203/crapi/reseller/mdr.php?token=QlJRSkZWfkJET1VF="
        res = requests.get(url, timeout=15)
        if not res.text.strip():
            return []
        data = res.json()
        if not isinstance(data, dict):
            return []
        if data.get("status", "").lower() != "success":
            return []
        result = []
        for r in data.get("data", []):
            msg = html.unescape(r.get("message", ""))
            result.append({
                "source": "api4",
                "service": r.get("cli", "Unknown"),
                "number":  r.get("number", "N/A"),
                "message": msg,
                "time":    r.get("datetime", "N/A")
            })
        return result
    except Exception as e:
        print(f"[API4] {e}")
        return []

def fetch_api5():
    """viewstats API 5 — response: [[service, number, message, datetime], ...]"""
    import html as html_mod
    try:
        url = "http://147.135.212.197/crapi/st/viewstats?token=SFFVRUFBUzSIUomGVE9rVItRY1iAjFB5dZJoa2lVjWRWandFd22EYA=="
        res = requests.get(url, timeout=15)
        text = res.text.strip()
        if not text or not text.startswith('['):
            return []
        data = res.json()
        if not isinstance(data, list):
            return []
        result = []
        for r in data:
            if not isinstance(r, list) or len(r) < 4:
                continue
            msg = html_mod.unescape(str(r[2]))
            result.append({
                "source":  "api5",
                "service": r[0] or "Unknown",
                "number":  r[1] or "N/A",
                "message": msg,
                "time":    r[3] or "N/A"
            })
        return result
    except Exception as e:
        pass  # API5 empty response — normal
        return []

def fetch_api6():
    """viewstats API 6 — response: [[service, number, message, datetime], ...]"""
    import html as html_mod
    try:
        url = "http://147.135.212.197/crapi/st/viewstats?token=SFJQQ0NBUzSHcXNXZFFYSIRpZlh3bHRFYndsWXRTkWZhhnFphmtkRA=="
        res = requests.get(url, timeout=15)
        text = res.text.strip()
        if not text or not text.startswith('['):
            return []
        data = res.json()
        if not isinstance(data, list):
            return []
        result = []
        for r in data:
            if not isinstance(r, list) or len(r) < 4:
                continue
            msg = html_mod.unescape(str(r[2]))
            result.append({
                "source":  "api6",
                "service": r[0] or "Unknown",
                "number":  r[1] or "N/A",
                "message": msg,
                "time":    r[3] or "N/A"
            })
        return result
    except Exception as e:
        pass  # API6 empty response — normal
        return []

def fetch_api3():
    try:
        url = "http://51.77.216.195/crapi/konek/viewstats?token=SE9YNEVBl1drVXCEaYhqdop2cUdkjGp4WXaUc4iCZmt4iIFaaHE"
        res = requests.get(url, timeout=15)
        if not res.text.strip():
            return []
        data = res.json()
        # Agar response list hai (viewstats format)
        if isinstance(data, list):
            import html as html_mod
            result = []
            for r in data:
                if not isinstance(r, list) or len(r) < 4:
                    continue
                msg = html_mod.unescape(str(r[2]))
                result.append({"source": "api3", "service": r[0] or "Unknown",
                                "number": r[1] or "N/A", "message": msg,
                                "time": r[3] or "N/A"})
            return result
        # Agar dict hai (mdr format)
        if not isinstance(data, dict):
            return []
        if data.get("status", "").lower() != "success":
            return []
        return [{"source": "api3", "service": r.get("cli", "Unknown"),
                 "number": r.get("num", "N/A"), "message": r.get("message", ""),
                 "time": r.get("dt", "N/A")} for r in data.get("data", [])]
    except Exception as e:
        print(f"[API3] {e}")
        return []

def extract_otp(msg):
    for p in [r"\d{3}-\d{3}", r"\d{6}", r"\d{5}", r"\d{4}"]:
        m = re.search(p, msg)
        if m:
            return m.group(0)
    return "N/A"

def get_country_info(num):
    try:
        n = "+" + num if not num.startswith("+") else num
        parsed = phonenumbers.parse(n)
        country = geocoder.description_for_number(parsed, "en")
        region  = phonenumbers.region_code_for_number(parsed)
        flag = (chr(127462 + ord(region[0]) - 65) + chr(127462 + ord(region[1]) - 65)) if region else "🌍"
        return country or "Unknown", flag, region or "??"
    except:
        return "Unknown", "🌍", "??"

def detect_language(text):
    if not text: return "English"
    if re.search(r'[\u0600-\u06FF]', text): return "Arabic"
    if re.search(r'[\u0400-\u04FF]', text): return "Russian"
    if re.search(r'[\u4E00-\u9FFF]', text): return "Chinese"
    if re.search(r'[\u0900-\u097F]', text): return "Hindi"
    if re.search(r'\b(código|clave|su|tu|para|este|es)\b', text, re.I): return "Spanish"
    if re.search(r'\b(votre|code|est|pour|merci)\b', text, re.I): return "French"
    return "English"

def to_bold_font(text):
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    bold   = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
    return "".join(bold[normal.find(c)] if normal.find(c) != -1 else c for c in text)

def mask_ghost(num):
    num = num.lstrip("+")
    if len(num) <= 6:
        return num + "Ghost"
    return f"{num[:4]}Ghost{num[-4:]}"

SERVICE_EMOJI_TG = {
    "whatsapp": "5334998226636390258", "telegram": "5330237710655306682",
    "instagram": "5319160079465857105", "facebook": "5323261730283863478",
    "google": "5359758030198031389",   "microsoft": "5370857634440170316",
    "twitter": "5330337435500951363",  "tiktok": "5327982530702359565",
    "snapchat": "5330248916224983855", "binance": "5359437015752401733",
    "discord": "5226520997850550976",  "imo": "5226479577185949100",
    "amazon": "5226745212323272446",   "netflix": "5229102973275113650",
    "rednote": "5226837060198896309",
}
SERVICE_EMOJI_DEFAULT = "5226837060198896309"

COUNTRY_EMOJI = {
    "UA":"5222250679371839695","US":"5224321781321442532","PL":"5224670399521892983",
    "KZ":"5222276376161171525","AZ":"5224426544163728284","AM":"5224369957969603463",
    "RU":"5280582975270963511","CN":"5224435456220868088","UZ":"5222404546575219535",
    "DE":"5222165617544542414","JP":"5222390089715299207","TR":"5224601903383457698",
    "BY":"5280820319458707404","GB":"5224518800061245598","IN":"5222300011366200403",
    "BR":"5224688610183228070","YE":"5222300655611294950","VN":"5222359651282071925",
    "AE":"5224565851427976312","UG":"5222464040462200940","TH":"5224638530864556281",
    "TZ":"5224397364155923150","TJ":"5222217865821696536","CH":"5224707263226194753",
    "SE":"5222201098269373561","ES":"5222024776976970940","KR":"5222345550904439270",
    "ZA":"5224696216570309138","SG":"5224194023224257181","RS":"5222145396838512729",
    "SA":"5224698145010624573","CI":"5293991322003200135","RO":"5222273794885826118",
    "QA":"5222225596762830469","PT":"5224404094369672274","PH":"5222065042295376892",
    "PK":"5224637061985742245","NG":"5224723614166691638","NL":"5224516489368841614",
    "MY":"5224312886444174057","KE":"5222089648163009103","FR":"5222029789203804982",
    "IT":"5222460101977190141","IL":"5224720599099648709","IQ":"5221980268230882832",
    "IR":"5224374154152653367","ID":"5224405893960969756","HU":"5224691998912427164",
    "GH":"5224511339703056124","GE":"5222152195771742239","EG":"5222161185138292290",
    "DK":"5222297215342490217","CO":"5224455152940886669","CA":"5222001124592071204",
    "CM":"5222270788408717651","BD":"5224407289825340729","AU":"5224659803837574114",
    "AR":"5221980461504411710","VE":"5294476442854247878","MA":"5224530035695693965",
    "MX":"5221971386238514431","SN":"5224321781321442532",
}
COUNTRY_EMOJI_DEFAULT = "6161462810422290161"

def get_service_emoji_id(service_str):
    s = service_str.lower()
    for k, v in SERVICE_EMOJI_TG.items():
        if k in s:
            return v
    return SERVICE_EMOJI_DEFAULT

def format_otp_msg(data):
    import html as html_mod
    otp    = extract_otp(data["message"])
    country, flag, region = get_country_info(data["number"])
    masked  = mask_ghost(data["number"])
    svc_eid = get_service_emoji_id(data["service"])
    c_eid   = COUNTRY_EMOJI.get(region, COUNTRY_EMOJI_DEFAULT)
    lang    = detect_language(data["message"])
    flag_tag = f'<tg-emoji emoji-id="{c_eid}">{flag}</tg-emoji>'
    svc_tag  = f'<tg-emoji emoji-id="{svc_eid}">{html_mod.escape(data["service"][:3])}</tg-emoji>'
    masked_s = masked.replace("Ghost", "<b>𝗚𝗛𝗢𝗦𝗧</b>")
    msg = (f"{flag_tag} <b>{html_mod.escape(region)}</b>  |  {masked_s}  |  {svc_tag}\n"
           f"🔈 <b>{html_mod.escape(lang)}</b>\n")
    return msg, otp

def update_live_traffic(service, country):
    import datetime as dt
    now = dt.datetime.now()
    key = f"{service}_{country}"
    live_traffic.setdefault(key, {"service": service, "country": country, "count": 0, "last_time": None})
    live_traffic[key]["count"] += 1
    live_traffic[key]["last_time"] = now
    cutoff = dt.datetime.now() - dt.timedelta(minutes=30)
    for k in list(live_traffic):
        if live_traffic[k]["last_time"] and live_traffic[k]["last_time"] < cutoff:
            del live_traffic[k]

# ============================================================
# OTP Send — user FIRST, then groups
# ============================================================
async def send_otp(data):
    msg, otp   = format_otp_msg(data)
    country, flag, region = get_country_info(data["number"])
    update_live_traffic(data["service"], country)
    clean_otp  = otp.replace("-", "")
    otp_bold   = to_bold_font(clean_otp)
    _full_sms_cache[data["number"]] = data["message"]

    # Mark number as OTP-used — future allotment mein skip hoga
    mark_number_otp_used(data["number"])
    keyboard   = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔐  {otp_bold}", callback_data=f"copyotp_{clean_otp}")],
        [InlineKeyboardButton("📡 Panel", url=f"https://t.me/{BOT_USERNAME.replace('@','')}"),
         InlineKeyboardButton("🔔 Channel", url="https://t.me/+Cwr6hvLGd0RhNTRl")]
    ])

    # 1️⃣ User pehle
    await notify_user_privately(data["number"], otp, data["service"], data["message"])

    # 2️⃣ Groups baad mein
    for chat_id in load_chat_ids():
        try:
            sent = await safe_send(lambda cid=chat_id: bot.send_message(cid, msg, parse_mode="HTML", reply_markup=keyboard))
            if sent and chat_id in load_auto_delete_chats():
                asyncio.create_task(auto_delete_message(chat_id, sent.message_id, 120))
        except Exception as e:
            print(f"[GROUP] {chat_id}: {e}")

async def notify_user_privately(number, otp, service, full_message):
    history    = load_json(OTP_HISTORY_FILE)
    user_nums  = load_json(USER_NUMBERS_FILE)
    user_stats = load_json(USER_STATS_FILE)

    for uid, udata in user_nums.items():
        # Teeno numbers check karo — kisi pe bhi OTP aaye notify karo
        nums = list(udata.get('numbers', []))
        single = udata.get('number')
        if single and single not in nums:
            nums.append(single)
        if not nums or number not in nums:
            continue

        # History save
        history.setdefault(uid, []).append({
            'otp': otp, 'service': service, 'number': number,
            'message': full_message,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        if len(history[uid]) > 20:
            history[uid] = history[uid][-20:]

        # OTP count
        user_stats.setdefault(uid, {"otp_count": 0})
        user_stats[uid]["otp_count"] = user_stats[uid].get("otp_count", 0) + 1

        # Balance add
        new_bal = add_balance(int(uid), OTP_EARN_PER_OTP)

        # User notify — with earned + balance
        txt = (
            f"📩 <b>New OTP Received!</b>\n\n"
            f"🎯 <b>OTP:</b> <code>{otp}</code>\n\n"
            f"📱 <b>Service:</b> {service}\n"
            f"📞 <b>Number:</b> <code>{number}</code>\n\n"
            f"💵 <b>Earned:</b> +$0.01$\n"
            f"💰 <b>Balance:</b> ${new_bal:.2f}$\n\n"
            f"💬 <b>Full Message:</b>\n<code>{full_message}</code>"
        )
        await safe_send(lambda u=uid, t=txt: bot.send_message(int(u), t, parse_mode="HTML"))
        print(f"[OTP] Notified user {uid} — {number} — {otp}")

        # Referrer earn
        referrer = get_referrer(int(uid))
        if referrer:
            rb = add_balance(int(referrer), REFERRAL_EARN_PER_OTP)
            refs = load_json(REFERRAL_FILE)
            refs.setdefault(str(referrer), {})
            refs[str(referrer)]['total_bonus'] = round(
                refs[str(referrer)].get('total_bonus', 0.0) + REFERRAL_EARN_PER_OTP, 4
            )
            save_json(REFERRAL_FILE, refs)
            await safe_send(lambda r=referrer, b=rb: bot.send_message(
                int(r),
                f"💸 <b>Referral Earning!</b>\n\n"
                f"Your referral received an OTP\n"
                f"💵 <b>Earned:</b> +$0.001$\n"
                f"💰 <b>Balance:</b> ${b:.4f}$",
                parse_mode="HTML"
            ))

    save_json(OTP_HISTORY_FILE, history)
    save_json(USER_STATS_FILE, user_stats)

async def auto_delete_message(chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except:
        pass

# ============================================================
# Broadcast helpers
# ============================================================
async def _do_broadcast(text, admin_chat_id, status_msg_id):
    """Background broadcast — OTP loop ko affect nahi karega"""
    gs, gf = 0, 0
    for cid in load_chat_ids():
        result = await safe_send(lambda c=cid: bot.send_message(c, text, parse_mode="HTML"))
        if result: gs += 1
        else: gf += 1
        await asyncio.sleep(0.1)

    try:
        await bot.send_message(AUTO_POST_CHANNEL, text, parse_mode="HTML")
    except:
        pass

    udata = load_json(USER_NUMBERS_FILE)
    us, uf, skip = 0, 0, 0
    all_u = list(udata.keys())
    total = len(all_u)

    for i, uid in enumerate(all_u):
        try:
            result = await bot.send_message(int(uid), text, parse_mode="HTML")
            if result:
                us += 1
            else:
                skip += 1
        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["forbidden", "blocked", "deactivated", "not found", "chat not found"]):
                skip += 1  # silent skip — bot blocked ya account deleted
            else:
                uf += 1

        # Flood control — 0.3s per user (Telegram limit: ~30 msg/sec)
        await asyncio.sleep(0.3)

        # Update status every 100 users
        if (i + 1) % 100 == 0:
            try:
                await bot.edit_message_text(
                    chat_id=admin_chat_id, message_id=status_msg_id,
                    text=(
                        f"📢 <b>Broadcasting...</b>\n\n"
                        f"💬 Groups: ✅{gs} ❌{gf}\n"
                        f"👤 Users: {i+1}/{total}\n"
                        f"✅ Sent: {us} | ⏭ Skipped: {skip} | ❌ Failed: {uf}"
                    ),
                    parse_mode="HTML")
            except:
                pass

        # Yield control every 10 users so OTP loop can run
        if (i + 1) % 10 == 0:
            await asyncio.sleep(0)

    try:
        await bot.edit_message_text(
            chat_id=admin_chat_id, message_id=status_msg_id,
            text=(
                f"✅ <b>Broadcast Complete!</b>\n\n"
                f"💬 Groups: ✅{gs} ❌{gf}\n"
                f"👤 Users: ✅{us} | ⏭ Skipped: {skip} | ❌{uf}\n"
                f"📊 Total Sent: {gs+us}"
            ),
            parse_mode="HTML")
    except:
        pass

# main_menu_kb removed — no main menu, direct flow only

# ============================================================
# /start
# ============================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    uid_s   = str(user_id)

    # Referral register
    if context.args:
        try:
            ref = int(context.args[0])
            if ref != user_id:
                refs = load_json(REFERRAL_FILE)
                if uid_s not in refs or not refs[uid_s].get("referred_by"):
                    refs.setdefault(uid_s, {})["referred_by"] = str(ref)
                    refs.setdefault(str(ref), {})
                    refs[str(ref)]["count"] = refs[str(ref)].get("count", 0) + 1
                    refs[str(ref)].setdefault("referred_users", []).append(uid_s)
                    save_json(REFERRAL_FILE, refs)
        except:
            pass

    # Stats init
    stats = load_json(USER_STATS_FILE)
    if uid_s not in stats:
        stats[uid_s] = {"otp_count": 0, "name": user.first_name or "",
                        "username": user.username or "",
                        "join_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        save_json(USER_STATS_FILE, stats)

    if user_id in load_admin_ids():
        await update.message.reply_text(
            f"🔥 <b>Welcome Admin — {BOT_NAME}</b>\n\n"
            "📁 <b>Number Management:</b>\n"
            "/setcountry &lt;name&gt; — set country for next upload\n"
            "/listcountries — view all stock\n"
            "/deletecountry — delete country\n"
            "/cleannumbers &lt;country&gt; — clear numbers\n\n"
            "👤 <b>Admin:</b> /add_admin /remove_admin /list_admins\n"
            "💬 <b>Chat:</b> /add_chat /addchats /remove_chat /list_chats\n"
            "📢 <b>Broadcast:</b> /broadcast &lt;msg&gt;\n"
            "📊 <b>Other:</b> /status /id /help",
            parse_mode="HTML"
        )
        return

    # Hamesha channel verify screen dikhao
    kb = [[InlineKeyboardButton(f"➕ Join {n}", url=l)] for n, l, _ in REQUIRED_CHANNELS]
    kb.append([InlineKeyboardButton("✅ I Joined — Verify", callback_data="verify")])
    await update.message.reply_text(
        f"👋 <b>Welcome to {BOT_NAME}!</b>\n\n"
        f"📢 Pehle hamara channel join karo, phir Verify karo:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML"
    )
    return

# ============================================================
# Main callback router
# ============================================================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data

    # OTP copy
    if data == "noop":
        await q.answer("✅ Copy the OTP!")
        return
    if data.startswith("copyotp_"):
        await q.answer(f"✅ OTP: {data[8:]}", show_alert=True)
        return

    # Auth
    if data == "verify":
        await _verify(update, context); return

    # Back to service selection
    if data == "back_to_service":
        await _show_services(update, context); return

    # Country/Service selection
    if data.startswith("ci_"):
        await _country_selected(update, context); return
    if data.startswith("svc_user_"):
        await _service_selected_user(update, context); return
    if data.startswith("change_num_"):
        await _change_numbers(update, context); return

    # Admin: upload service multi-select
    if data == "usvc_done":
        await _admin_service_done(update, context); return
    if data.startswith("usvc_"):
        await _admin_service_toggle(update, context); return
    if data == "broadcast_now":
        await _broadcast_now(update, context); return
    if data == "silent_save":
        await _silent_save(update, context); return

    # Admin: delete country
    if data.startswith("delcountry_"):
        await _del_country_cb(update, context); return

    # setcountry for file prompt
    if data == "setcountry_for_file":
        await _setcountry_prompt(update, context); return

    await q.answer()

# ============================================================
# Verify
# ============================================================
async def _verify(update, context):
    q = update.callback_query
    user_id = update.effective_user.id
    if await check_subscription(user_id):
        await q.answer("✅ Verified!")
        await _send_country_list(q.message, context, edit=True)
    else:
        await q.answer("❌ Please join the channel first!", show_alert=True)

# ============================================================
# Country list — direct, no service select
# ============================================================
async def _send_country_list(msg_or_query, context, edit=False):
    """Show all countries with numbers. msg_or_query can be Message or CallbackQuery"""
    cws = get_countries_with_services()
    all_countries = list(cws.keys())

    if not all_countries:
        text = "⚠️ <b>No numbers available yet. Try again later.</b>"
        if edit:
            await msg_or_query.edit_text(text, parse_mode="HTML")
        else:
            await msg_or_query.reply_text(text, parse_mode="HTML")
        return

    # Store country map
    ci_map = {str(i): c for i, c in enumerate(all_countries)}
    context.bot_data['_ci'] = ci_map

    kb = []
    row = []
    for i, country in enumerate(all_countries):
        total = sum(len(get_numbers_for_country_service(country, s)) for s in cws[country])
        row.append(InlineKeyboardButton(f"🌍 {country} ({total})", callback_data=f"ci_{i}"))
        if len(row) == 2:
            kb.append(row); row = []
    if row: kb.append(row)

    text = f"👋 <b>WELCOME TO {BOT_NAME}!</b>\n\n🌍 <b>Select Country to get number:</b>"
    if edit:
        await msg_or_query.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        await msg_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def _show_services(update, context):
    q = update.callback_query
    await q.answer()
    await _send_country_list(q.message, context, edit=True)

async def _get_number(update, context):
    await _show_services(update, context)

# ============================================================
# Country selected → assign number (no service needed)
# ============================================================
async def _country_selected(update, context):
    q = update.callback_query
    await q.answer()
    idx = q.data.replace("ci_", "")
    ci_map = context.bot_data.get('_ci', {})
    country = ci_map.get(idx)
    if not country:
        await q.answer("❌ Try again.", show_alert=True); return

    # Pick first available service for this country
    cws = get_countries_with_services()
    svcs = cws.get(country, [])
    service = svcs[0] if svcs else "WhatsApp"

    await _assign_numbers(update, context, country, service)

async def _service_selected_user(update, context):
    # Not used anymore — keep for safety
    q = update.callback_query
    await q.answer()
    await _send_country_list(q.message, context, edit=True)

async def _assign_numbers(update, context, country, service):
    q = update.callback_query
    user_id = update.effective_user.id
    nums = get_unique_numbers_for_user(country, service, count=1)
    if not nums:
        await q.answer("⚠️ No numbers available!", show_alert=True); return

    un = load_json(USER_NUMBERS_FILE)
    un[str(user_id)] = {
        'country': country, 'service': service,
        'number': nums[0], 'numbers': nums,
        'assigned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    save_json(USER_NUMBERS_FILE, un)

    _, flag, _ = get_country_info(nums[0])
    text = f"{flag} <b>{country} — {service} Number:</b>\n\n"
    for i, n in enumerate(nums, 1):
        text += f"{i}. <code>{n}</code>\n\n"
    text += "⏳ Waiting for OTPs...\n🔔 You will be notified instantly!"

    kb = [
        [InlineKeyboardButton("🔄 Change Number", callback_data=f"change_num_{country}_{service}"),
         InlineKeyboardButton("🌍 Change Country", callback_data="back_to_service")],
        [InlineKeyboardButton("📢 OTP Group", url="https://t.me/+Cwr6hvLGd0RhNTRl")]
    ]
    await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def _change_numbers(update, context):
    q = update.callback_query
    await q.answer()
    parts = q.data.replace("change_num_", "").split("_", 1)
    country = parts[0]
    service = parts[1] if len(parts) > 1 else None

    if not service:
        # Legacy: get service from stored data
        un = load_json(USER_NUMBERS_FILE)
        udata = un.get(str(update.effective_user.id), {})
        service = udata.get("service", "WhatsApp")
    await _assign_numbers(update, context, country, service)

# ============================================================
# Past OTPs
# ============================================================
async def _past_otps(update, context):
    q = update.callback_query
    await q.answer()
    user_id = str(update.effective_user.id)
    history = load_json(OTP_HISTORY_FILE)
    entries = history.get(user_id, [])
    if not entries:
        await q.answer("📭 No past OTPs found!", show_alert=True); return
    text = "📜 <b>Your Past OTPs:</b>\n\n"
    for e in entries[-10:]:
        text += f"🎯 OTP: <code>{e['otp']}</code> | {e['service']} | {e['time']}\n"
    await q.message.reply_text(text, parse_mode="HTML")

# ============================================================
# My Account
# ============================================================
async def _my_account(update, context):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    uid_s   = str(user_id)
    stats   = load_json(USER_STATS_FILE)
    refs    = load_json(REFERRAL_FILE)
    history = load_json(OTP_HISTORY_FILE)

    otp_count   = stats.get(uid_s, {}).get("otp_count", 0)
    balance     = get_balance(user_id)
    ref_count   = refs.get(uid_s, {}).get("count", 0)
    ref_bonus   = round(ref_count * REFERRAL_EARN_PER_OTP * otp_count, 4)  # approximation

    # top country
    my_h    = history.get(uid_s, [])
    cc      = {}
    for h in my_h:
        c = get_country_info(h.get('number', ''))[0]
        cc[c] = cc.get(c, 0) + 1
    top_c   = max(cc, key=cc.get) if cc else "N/A"

    bot_i   = await bot.get_me()
    ref_link = f"https://t.me/{bot_i.username}?start={user_id}"

    text = (f"👤 <b>My Account</b>\n\n"
            f"🆔 User ID: <code>{user_id}</code>\n"
            f"💰 Balance: <b>${balance:.2f}</b>\n"
            f"📊 Min Withdraw: <b>${MIN_WITHDRAW:.2f}</b>\n\n"
            f"📨 Total OTPs Received: <b>{otp_count}</b>\n"
            f"🏆 Top Country: <b>{top_c}</b>\n\n"
            f"👥 Referrals (L1): <b>{ref_count}</b>\n"
            f"🎁 Total Referral Bonus: <b>${refs.get(uid_s, {}).get('total_bonus', 0.0):.4f}</b>\n\n"
            f"🔗 Referral Link:\n<code>{ref_link}</code>\n\n"
            f"🎁 <i>Earn commissions from your friends' OTPs!</i>")
    kb = [
        [InlineKeyboardButton("💸 Request Withdrawal", callback_data="menu_withdraw")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
    ]
    await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# ============================================================
# Balance
# ============================================================
async def _balance(update, context):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    text = (f"💰 <b>Your Balance</b>\n\n"
            f"💵 Current Balance: <b>${bal:.2f}</b>\n"
            f"📊 Minimum Withdraw: <b>${MIN_WITHDRAW:.2f}</b>\n\n"
            f"You earn <b>${OTP_EARN_PER_OTP}</b> for every OTP received on your numbers.")
    kb = [
        [InlineKeyboardButton("💸 Request Withdrawal", callback_data="menu_withdraw")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
    ]
    await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# ============================================================
# Withdraw
# ============================================================
async def _withdraw(update, context):
    q = update.callback_query
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    if bal < MIN_WITHDRAW:
        await q.answer(
            f"🚫 Minimum withdrawal is ${MIN_WITHDRAW:.2f}\nYour balance: ${bal:.2f}",
            show_alert=True
        )
        return
    await q.answer()
    text = (f"💸 <b>Withdrawal Request</b>\n\n"
            f"💰 Your Balance: <b>${bal:.2f}</b>\n"
            f"📊 Min Withdraw: <b>${MIN_WITHDRAW:.2f}</b>\n\n"
            f"✅ Balance sufficient! Contact developer:\n"
            f"👨‍💻 {DEV_USERNAME}")
    kb = [
        [InlineKeyboardButton("💬 Contact Developer", url=f"https://t.me/{DEV_USERNAME.replace('@','')}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
    ]
    await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# ============================================================
# Refer & Earn
# ============================================================
async def _refer_earn(update, context):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    uid_s   = str(user_id)
    refs    = load_json(REFERRAL_FILE)
    bot_i   = await bot.get_me()
    ref_link  = f"https://t.me/{bot_i.username}?start={user_id}"
    ref_count = refs.get(uid_s, {}).get("count", 0)
    ref_bonus = refs.get(uid_s, {}).get("total_bonus", 0.0)
    bal       = get_balance(user_id)

    text = (f"👥 <b>Refer &amp; Earn</b>\n\n"
            f"🆔 User ID: <code>{user_id}</code>\n"
            f"💰 Balance: <b>${bal:.2f}</b>\n"
            f"📊 Min Withdraw: <b>${MIN_WITHDRAW:.2f}</b>\n\n"
            f"👥 Referrals (L1): <b>{ref_count}</b>\n"
            f"🎁 Total Referral Bonus: <b>${ref_bonus:.4f}</b>\n\n"
            f"🔗 <b>Your Referral Link:</b>\n<code>{ref_link}</code>\n\n"
            f"💡 <b>How it works:</b>\n"
            f"If you refer a friend and they receive an OTP on their number, "
            f"you will earn <b>$0.001</b> for every OTP they receive. "
            f"The more friends you refer, the more you earn!\n\n"
            f"💵 Minimum withdrawal is <b>${MIN_WITHDRAW:.2f}</b>.")
    kb = [
        [InlineKeyboardButton("💸 Withdraw", callback_data="menu_withdraw"),
         InlineKeyboardButton("🔄 Refresh",  callback_data="menu_refer_earn")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
    ]
    await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# ============================================================
# Get Number File
# ============================================================
async def _get_number_file(update, context):
    q = update.callback_query
    await q.answer()
    cws = get_countries_with_services()
    if not cws:
        await q.message.edit_text(
            "📂 <b>No files available yet.</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]),
            parse_mode="HTML"
        )
        return
    text = "📂 <b>Select a country to download numbers:</b>"
    kb   = []
    for country, svcs in cws.items():
        count = sum(len(get_numbers_for_country_service(country, s)) for s in svcs)
        kb.append([InlineKeyboardButton(f"📂 {country} ({count})", callback_data=f"getfile_{country}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")])
    await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def _getfile(update, context):
    q = update.callback_query
    await q.answer("📤 Sending file...")
    country = q.data.replace("getfile_", "")
    all_nums = get_all_numbers_for_country(country)
    if not all_nums:
        await q.answer("⚠️ No numbers!", show_alert=True); return
    fname = f"{country.replace(' ','_')}_Numbers.txt"
    fpath = os.path.join(DATA_DIR, fname)
    with open(fpath, 'w') as f:
        f.write("\n".join(all_nums))
    cap = f"📂 <b>{country}</b>\nCount: {len(all_nums)}\n\n⚡ {BOT_NAME}"
    with open(fpath, 'rb') as f:
        await safe_send(lambda: bot.send_document(update.effective_user.id, document=f, filename=fname, caption=cap, parse_mode="HTML"))
    try: os.remove(fpath)
    except: pass

# ============================================================
# Development
# ============================================================
async def _dev(update, context):
    q = update.callback_query
    await q.answer()
    text = (f"🛠 <b>Development</b>\n\n"
            f"Need help or have a suggestion?\n\n"
            f"👨‍💻 Developer: {DEV_USERNAME}\n\n"
            f"📌 <b>Common Issues:</b>\n"
            f"• OTP not received? Wait up to 10 mins\n"
            f"• Number not working? Use Change Number\n"
            f"• Bot not responding? Try /start\n\n"
            f"⚡ Powered by {BOT_NAME}")
    kb = [
        [InlineKeyboardButton("💬 Contact Developer", url=f"https://t.me/{DEV_USERNAME.replace('@','')}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
    ]
    await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# ============================================================
# ADMIN: File Upload flow
# ============================================================
async def cmd_setcountry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    if not context.args:
        await update.message.reply_text("❌ Usage: /setcountry <country_name>"); return
    country = " ".join(context.args)
    context.user_data['set_country'] = country
    await update.message.reply_text(
        f"✅ Country set: <b>{country}</b>\n\nNow upload .txt file with numbers.",
        parse_mode="HTML"
    )

async def handle_txt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.effective_user.id not in load_admin_ids(): return
    doc = update.message.document
    if not doc or not doc.file_name.endswith('.txt'): return

    country = context.user_data.get('set_country') or PENDING_COUNTRY.get(update.effective_user.id)

    if not country or PENDING_COUNTRY.get(update.effective_user.id) == "awaiting_name":
        context.user_data['pending_file_id']   = doc.file_id
        context.user_data['pending_file_name'] = doc.file_name
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Set Country Name", callback_data="setcountry_for_file")]])
        await update.message.reply_text(
            "📂 <b>File received!</b>\n\nSet country/category name first:",
            reply_markup=kb, parse_mode="HTML"
        )
        return

    await _process_txt(update, context, doc.file_id, country)

async def _setcountry_prompt(update, context):
    q = update.callback_query
    if update.effective_user.id not in load_admin_ids():
        await q.answer("❌ Only admins!", show_alert=True); return
    PENDING_COUNTRY[update.effective_user.id] = "awaiting_name"
    await q.answer()
    await q.message.edit_text(
        "✍️ <b>Type country/category name and send:</b>\n\nExample: <code>Venezuela</code>",
        parse_mode="HTML"
    )

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.effective_user.id not in load_admin_ids(): return
    user_id = update.effective_user.id
    if PENDING_COUNTRY.get(user_id) != "awaiting_name": return

    country = update.message.text.strip()
    if not country:
        await update.message.reply_text("❌ Name cannot be empty!"); return

    file_id = context.user_data.get('pending_file_id')
    if not file_id:
        await update.message.reply_text("❌ File not found. Upload again.")
        PENDING_COUNTRY.pop(user_id, None); return

    PENDING_COUNTRY.pop(user_id, None)
    context.user_data['set_country'] = country
    await update.message.reply_text(f"✅ Country: <b>{country}</b>\n⏳ Processing...", parse_mode="HTML")
    await _process_txt(update, context, file_id, country)

async def _process_txt(update, context, file_id, country):
    user_id = update.effective_user.id
    try:
        f = await bot.get_file(file_id)
        tmp = f"tmp_{user_id}.txt"
        await f.download_to_drive(tmp)
        with open(tmp, 'r') as fx:
            numbers = [l.strip() for l in fx if l.strip()]
        try: os.remove(tmp)
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ File error: {e}"); return

    context.user_data.pop('set_country', None)
    context.user_data.pop('pending_file_id', None)
    PENDING_COUNTRY.pop(user_id, None)

    # Store in pending — admin will select services
    PENDING_UPLOAD[user_id] = {
        'country': country,
        'numbers': numbers,
        'services_selected': set(),
    }

    await _show_service_multiselect(update, context, user_id, first=True)

async def _show_service_multiselect(update, context, user_id, first=False):
    pending = PENDING_UPLOAD.get(user_id)
    if not pending:
        return
    selected = pending['services_selected']
    country  = pending['country']
    numbers  = pending['numbers']

    kb = []
    row = []
    for svc in ALL_SERVICES:
        emoji = SERVICE_EMOJI_BTN.get(svc, "📱")
        tick  = "✅ " if svc in selected else ""
        row.append(InlineKeyboardButton(f"{tick}{emoji} {svc}", callback_data=f"usvc_{svc}"))
        if len(row) == 2:
            kb.append(row); row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("✅ Done", callback_data="usvc_done")])

    sel_text = ", ".join(selected) if selected else "None selected"
    text = (f"📂 <b>{len(numbers)} numbers loaded</b>\n"
            f"🌍 Country: <b>{country}</b>\n\n"
            f"🛒 <b>Select services</b> (tap to toggle, tap multiple):\n"
            f"✅ Selected: <b>{sel_text}</b>\n\n"
            f"<i>Tap Done when finished.</i>")

    if first:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        try:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        except Exception as e:
            if "not modified" not in str(e).lower():
                print(f"[MULTISELECT] {e}")

async def _admin_service_toggle(update, context):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    if user_id not in load_admin_ids():
        await q.answer("❌ Only admins!", show_alert=True); return
    if user_id not in PENDING_UPLOAD:
        await q.answer("❌ No pending upload!", show_alert=True); return

    svc = q.data.replace("usvc_", "")
    selected = PENDING_UPLOAD[user_id]['services_selected']
    if svc in selected:
        selected.discard(svc)
    else:
        selected.add(svc)
    await _show_service_multiselect(update, context, user_id, first=False)

async def _admin_service_done(update, context):
    """Admin clicked Done — save numbers to selected services, show broadcast options"""
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    if user_id not in load_admin_ids():
        await q.answer("❌ Only admins!", show_alert=True); return

    pending = PENDING_UPLOAD.get(user_id)
    if not pending:
        await q.answer("❌ No pending upload!", show_alert=True); return

    country  = pending['country']
    numbers  = pending['numbers']
    selected = pending['services_selected']

    if not selected:
        await q.answer("⚠️ Select at least one service!", show_alert=True); return

    # Save numbers to each selected service
    results = {}
    for svc in selected:
        new_c, total = add_numbers_to_country_service(country, svc, numbers)
        results[svc] = (new_c, total)

    # Forward to number channel — file + caption with service + bot username
    try:
        svcs_str = ", ".join(selected)
        fname = f"{country.replace(' ','_')}_{svcs_str.replace(', ','_')}.txt"
        fpath = os.path.join(DATA_DIR, fname)
        with open(fpath, 'w') as fx:
            fx.write("\n".join(numbers))
        cap = (f"📂 <b>{country}</b>\n"
               f"🛒 Service: <b>{svcs_str}</b>\n"
               f"📈 Numbers: <b>{len(numbers)}</b>\n\n"
               f"⚡ {BOT_NAME}\n"
               f"🤖 {BOT_USERNAME}")
        with open(fpath, 'rb') as fx:
            await bot.send_document(NUMBER_CHANNEL_ID, document=fx, filename=fname, caption=cap, parse_mode="HTML")
        try: os.remove(fpath)
        except: pass
    except Exception as e:
        print(f"[CHANNEL POST] {e}")

    PENDING_UPLOAD.pop(user_id, None)

    # Build result summary
    summary = "\n".join(f"  • {s}: +{r[0]} new (total {r[1]})" for s, r in results.items())
    svcs_str = ", ".join(selected)

    # Build broadcast preview
    broadcast_text = (
        f"✅ <b>New Stock Added!</b>\n\n"
        f"🌍 Country: <b>🌍{country}</b>\n"
        f"🛒 Service: <b>{svcs_str}</b>\n"
        f"📈 New Stock: <b>{len(numbers)}</b>\n\n"
        f"⚡ 𝗚𝗛𝗢𝗦𝗧 𝗛𝗨𝗕\n"
        f"🤖 {BOT_USERNAME}"
    )

    # Store broadcast text for later
    context.bot_data[f'bcast_{user_id}'] = broadcast_text

    kb = [
        [InlineKeyboardButton("📢 Broadcast", callback_data="broadcast_now"),
         InlineKeyboardButton("🔇 Silent Save", callback_data="silent_save")]
    ]
    await q.message.edit_text(
        f"✅ <b>Numbers Saved!</b>\n\n{summary}\n\n"
        f"📋 <b>Broadcast Preview:</b>\n\n{broadcast_text}\n\n"
        f"<i>Choose an action:</i>",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML"
    )

async def _broadcast_now(update, context):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    btext = context.bot_data.pop(f'bcast_{user_id}', None)
    if not btext:
        await q.answer("❌ No broadcast data!", show_alert=True); return
    status = await q.message.edit_text("📢 <b>Broadcasting...</b>", parse_mode="HTML")
    asyncio.create_task(_do_broadcast(btext, q.message.chat_id, status.message_id))

async def _silent_save(update, context):
    q = update.callback_query
    await q.answer("✅ Saved silently!")
    context.bot_data.pop(f'bcast_{q.from_user.id}', None)
    try:
        await q.message.edit_text("✅ <b>Numbers saved silently. No broadcast sent.</b>", parse_mode="HTML")
    except:
        pass

# ============================================================
# Admin: Country management commands
# ============================================================
async def cmd_listcountries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    cws = get_countries_with_services()
    if not cws:
        await update.message.reply_text("⚠️ No countries."); return
    text = "🌍 <b>Countries &amp; Services:</b>\n\n"
    for c, svcs in cws.items():
        for s in svcs:
            nums = get_numbers_for_country_service(c, s)
            text += f"• <b>{c}</b> → {s}: {len(nums)}\n"
    await update.message.reply_text(text, parse_mode="HTML")

async def cmd_deletecountry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    data = get_countries_data()
    if not data:
        await update.message.reply_text("⚠️ No countries."); return
    kb = [[InlineKeyboardButton(f"🗑️ {c}", callback_data=f"delcountry_{c}")] for c in data]
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="menu_close")])
    await update.message.reply_text(
        "🗑️ <b>Select country to delete:</b>",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML"
    )

async def _del_country_cb(update, context):
    q = update.callback_query
    if q.from_user.id not in load_admin_ids():
        await q.answer("❌ Only admins!", show_alert=True); return
    country = q.data.replace("delcountry_", "")
    data    = get_countries_data()
    if country in data:
        del data[country]
        save_json(COUNTRIES_FILE, data)
        await q.answer(f"✅ Deleted: {country}")
        await q.message.edit_text(f"✅ <b>{country}</b> deleted.", parse_mode="HTML")
    else:
        await q.answer("❌ Not found!", show_alert=True)

async def cmd_cleannumbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    if not context.args:
        await update.message.reply_text("❌ Usage: /cleannumbers <country>"); return
    country = " ".join(context.args)
    data = get_countries_data()
    if country not in data:
        await update.message.reply_text(f"❌ Not found: {country}"); return
    data[country] = {} if isinstance(data[country], dict) else []
    save_json(COUNTRIES_FILE, data)
    await update.message.reply_text(f"✅ Cleared: {country}")

# ============================================================
# Admin management commands
# ============================================================
async def cmd_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    try:
        nid = int(context.args[0])
        ids = load_admin_ids()
        if nid in ids: await update.message.reply_text(f"⚠️ Already admin."); return
        ids.append(nid); save_admin_ids(ids)
        await update.message.reply_text(f"✅ Added admin: `{nid}`", parse_mode="Markdown")
    except: await update.message.reply_text("❌ /add_admin <user_id>")

async def cmd_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    try:
        nid = int(context.args[0])
        ids = load_admin_ids()
        if nid not in ids: await update.message.reply_text("⚠️ Not found."); return
        if len(ids) == 1: await update.message.reply_text("❌ Can't remove last admin!"); return
        ids.remove(nid); save_admin_ids(ids)
        await update.message.reply_text(f"✅ Removed: `{nid}`", parse_mode="Markdown")
    except: await update.message.reply_text("❌ /remove_admin <user_id>")

async def cmd_list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    ids = load_admin_ids()
    await update.message.reply_text("👥 Admins:\n" + "\n".join(f"• `{i}`" for i in ids), parse_mode="Markdown")

async def cmd_add_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    try:
        cid = int(context.args[0])
        ids = load_chat_ids()
        if cid in ids: await update.message.reply_text("⚠️ Already exists."); return
        ids.append(cid); save_chat_ids(ids)
        await update.message.reply_text(f"✅ Added: `{cid}`", parse_mode="Markdown")
    except: await update.message.reply_text("❌ /add_chat <chat_id>")

async def cmd_addchats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    try:
        cid = int(context.args[0])
        ids = load_chat_ids()
        if cid in ids: await update.message.reply_text("⚠️ Already exists."); return
        ids.append(cid); save_chat_ids(ids)
        try:
            await bot.send_message(cid, f"🎉 <b>Bot Activated!</b>\n⚡ {BOT_NAME}", parse_mode="HTML")
            await update.message.reply_text(f"✅ Added & activated: `{cid}`", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"✅ Added but test failed: {e}")
    except: await update.message.reply_text("❌ /addchats <chat_id>")

async def cmd_remove_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    try:
        cid = int(context.args[0])
        ids = load_chat_ids()
        if cid not in ids: await update.message.reply_text("⚠️ Not found."); return
        ids.remove(cid); save_chat_ids(ids)
        await update.message.reply_text(f"✅ Removed: `{cid}`", parse_mode="Markdown")
    except: await update.message.reply_text("❌ /remove_chat <chat_id>")

async def cmd_list_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    ids = load_chat_ids()
    await update.message.reply_text("💬 Chats:\n" + "\n".join(f"• `{i}`" for i in ids), parse_mode="Markdown")

async def cmd_activedelete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    cid = update.message.chat_id
    ids = load_auto_delete_chats()
    if cid in ids: await update.message.reply_text("⚠️ Already enabled."); return
    ids.append(cid); save_auto_delete_chats(ids)
    await update.message.reply_text("✅ Auto-delete ON (2 min)")

async def cmd_deactivedelete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    cid = update.message.chat_id
    ids = load_auto_delete_chats()
    if cid not in ids: await update.message.reply_text("⚠️ Not enabled."); return
    ids.remove(cid); save_auto_delete_chats(ids)
    await update.message.reply_text("✅ Auto-delete OFF")

async def cmd_list_autodelete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    ids = load_auto_delete_chats()
    await update.message.reply_text("🗑️ Auto-delete:\n" + "\n".join(f"• `{i}`" for i in ids), parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    cws  = get_countries_with_services()
    unum = load_json(USER_NUMBERS_FILE)
    await update.message.reply_text(
        f"📊 <b>{BOT_NAME} Status</b>\n\n"
        f"👥 Admins: {len(load_admin_ids())}\n"
        f"💬 Groups: {len(load_chat_ids())}\n"
        f"🌍 Countries: {len(cws)}\n"
        f"👤 Users: {len(unum)}\n"
        f"✅ Running!", parse_mode="HTML"
    )

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    full = update.message.text or ""
    parts = full.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text("❌ /broadcast <message>"); return
    btext = parts[1].strip()
    status = await update.message.reply_text("📢 <b>Broadcasting...</b>", parse_mode="HTML")
    asyncio.create_task(_do_broadcast(btext, update.message.chat_id, status.message_id))

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    c = update.message.chat
    msg = f"🆔 ID: `{u.id}`\n👤 {u.first_name}"
    if u.username: msg += f"\n📛 @{u.username}"
    if c.type in ["group", "supergroup"]: msg += f"\n\n💬 Chat: `{c.id}`\n📝 {c.title}"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"⚡ <b>{BOT_NAME} Help</b>\n\n"
        "/start — Start bot\n/id — Get your ID\n\n"
        "<b>Admin:</b>\n/setcountry &lt;name&gt;\n/listcountries\n/deletecountry\n"
        "/cleannumbers &lt;name&gt;\n/broadcast &lt;msg&gt;\n/status",
        parse_mode="HTML"
    )

async def handle_csv_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in load_admin_ids(): return
    doc = update.message.document
    if not doc or not doc.file_name.endswith('.csv'): return
    await update.message.reply_text("📂 CSV received. Use .txt files for number upload.")

# ============================================================
# OTP Check Loop
# ============================================================
async def otp_check_loop():
    global last_number, _api2_last_dt, _api3_last_dt, _api4_last_dt, _api5_last_dt, _api6_last_dt
    print(f"\n🔥 {BOT_NAME} — OTP Loop Started (8s interval)")

    async def safe_fetch(name, fetch_fn):
        """API ko background thread me run karo, slow/fail hone par skip karo"""
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, fetch_fn),
                timeout=20  # 20 sec max wait per API
            )
        except asyncio.TimeoutError:
            print(f"[{name}] Timeout — skipping this round")
            return []
        except Exception as e:
            print(f"[{name}] Error: {e}")
            return []

    while True:
        try:
            # API1
            try:
                loop = asyncio.get_event_loop()
                otp1 = await asyncio.wait_for(
                    loop.run_in_executor(None, fetch_latest_otp),
                    timeout=15
                )
                if otp1 and otp1["number"] != last_number:
                    last_number = otp1["number"]
                    await send_otp(otp1)
            except asyncio.TimeoutError:
                print("[API1] Timeout — skipping")
            except Exception as e:
                print(f"[API1] {e}")

            # API2
            for r in await safe_fetch("API2", fetch_api2):
                if _api2_last_dt is None or r["time"] > _api2_last_dt:
                    _api2_last_dt = r["time"]
                    await send_otp(r)
                    await asyncio.sleep(0.3)

            # API3
            for r in await safe_fetch("API3", fetch_api3):
                if _api3_last_dt is None or r["time"] > _api3_last_dt:
                    _api3_last_dt = r["time"]
                    await send_otp(r)
                    await asyncio.sleep(0.3)

            # API4
            for r in await safe_fetch("API4", fetch_api4):
                if _api4_last_dt is None or r["time"] > _api4_last_dt:
                    _api4_last_dt = r["time"]
                    await send_otp(r)
                    await asyncio.sleep(0.3)

            # API5
            for r in await safe_fetch("API5", fetch_api5):
                if _api5_last_dt is None or r["time"] > _api5_last_dt:
                    _api5_last_dt = r["time"]
                    await send_otp(r)
                    await asyncio.sleep(0.3)

            # API6
            for r in await safe_fetch("API6", fetch_api6):
                if _api6_last_dt is None or r["time"] > _api6_last_dt:
                    _api6_last_dt = r["time"]
                    await send_otp(r)
                    await asyncio.sleep(0.3)

        except Exception as e:
            print(f"[OTP Loop] {e}")

        await asyncio.sleep(8)  # Har 8 second me check karo

# ============================================================
# MAIN
# ============================================================
async def main():
    init_data_files()
    print(f"✅ Admins: {load_admin_ids()}")
    print(f"✅ Chats:  {load_chat_ids()}")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30).read_timeout(30)
        .write_timeout(30).pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start",           start_command))
    app.add_handler(CommandHandler("help",            cmd_help))
    app.add_handler(CommandHandler("id",              cmd_id))
    app.add_handler(CommandHandler("status",          cmd_status))
    app.add_handler(CommandHandler("broadcast",       cmd_broadcast))
    app.add_handler(CommandHandler("add_admin",       cmd_add_admin))
    app.add_handler(CommandHandler("remove_admin",    cmd_remove_admin))
    app.add_handler(CommandHandler("list_admins",     cmd_list_admins))
    app.add_handler(CommandHandler("add_chat",        cmd_add_chat))
    app.add_handler(CommandHandler("addchats",        cmd_addchats))
    app.add_handler(CommandHandler("remove_chat",     cmd_remove_chat))
    app.add_handler(CommandHandler("list_chats",      cmd_list_chats))
    app.add_handler(CommandHandler("activedelete",    cmd_activedelete))
    app.add_handler(CommandHandler("deactivedelete",  cmd_deactivedelete))
    app.add_handler(CommandHandler("list_autodelete", cmd_list_autodelete))
    app.add_handler(CommandHandler("setcountry",      cmd_setcountry))
    app.add_handler(CommandHandler("listcountries",   cmd_listcountries))
    app.add_handler(CommandHandler("deletecountry",   cmd_deletecountry))
    app.add_handler(CommandHandler("cleannumbers",    cmd_cleannumbers))

    app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), handle_csv_file))
    app.add_handler(MessageHandler(filters.Document.TXT,                  handle_txt_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,       handle_text_input))
    app.add_handler(CallbackQueryHandler(callback_router))

    print(f"🤖 {BOT_NAME} Starting...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

    await otp_check_loop()


if __name__ == "__main__":
    while True:
        try:
            print(f"\n[{datetime.now()}] 🚀 Starting bot...")
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\n🛑 Stopped.")
            break
        except Exception as e:
            print(f"[{datetime.now()}] 💥 Crash: {e}\n🔄 Restarting in 5s...")
            time.sleep(5)
