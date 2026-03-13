import requests
import json
import time
import re
import asyncio
from telegram import Bot
from telegram.error import TelegramError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import logging
from datetime import datetime

# লগিং কনফিগারেশন
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

class OTPMonitorBot:
    def __init__(self, telegram_token, group_chat_id, session_cookie, target_url, sesskey):
        self.telegram_token = telegram_token
        self.group_chat_id = str(group_chat_id).strip()  # স্ট্রিং হিসেবে নিশ্চিত করা
        self.session_cookie = session_cookie
        self.target_url = target_url
        self.sesskey = sesskey
        self.processed_otps = set()
        self.start_time = datetime.now()
        self.total_otps_sent = 0
        self.last_otp_time = None
        self.is_monitoring = True
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        self.telegram_bot = Bot(token=self.telegram_token)
        
        # OTP প্যাটার্ন ডিটেকশন
        self.otp_patterns = [
            r'\b\d{3}-\d{3}\b',
            r'\b\d{5}\b',
            r'code\s*:?\s*(\d+)',
            r'কোড\s*:?\s*(\d+)',
            r'otp\s*:?\s*(\d+)',
            r'password\s*:?\s*(\d+)',
            r'verification\s*code\s*:?\s*(\d+)',
            r'(\d{4,6})',
        ]
    
    def hide_phone_number(self, phone_number):
        """ফোন নাম্বার হাইড করুন"""
        if len(phone_number) >= 8:
            return phone_number[:5] + '***' + phone_number[-4:]
        return phone_number
    
    def extract_operator_name(self, operator):
        """অপারেটর থেকে শুধু নাম এক্সট্র্যাক্ট করুন"""
        if operator and isinstance(operator, str):
            parts = operator.split()
            if parts:
                return parts[0]
        return operator or "Unknown"
    
    async def test_telegram_connection(self):
        """টেলিগ্রাম কানেকশন টেস্ট"""
        try:
            logger.info("🔍 Testing Telegram connection...")
            me = await self.telegram_bot.get_me()
            logger.info(f"✅ Bot connected! Username: @{me.username}")
            logger.info(f"✅ Bot ID: {me.id}")
            logger.info(f"✅ Bot name: {me.first_name}")
            
            # টেস্ট মেসেজ পাঠান
            test_msg = f"🔄 Bot is online!\n⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            await self.telegram_bot.send_message(
                chat_id=self.group_chat_id,
                text=test_msg
            )
            logger.info(f"✅ Test message sent to group: {self.group_chat_id}")
            return True
        except TelegramError as e:
            logger.error(f"❌ Telegram connection failed: {e}")
            logger.error(f"❌ Chat ID: {self.group_chat_id}")
            logger.error(f"❌ Error type: {type(e).__name__}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            return False
    
    async def send_telegram_message(self, message, chat_id=None, reply_markup=None):
        """টেলিগ্রামে মেসেজ সেন্ড করুন"""
        if chat_id is None:
            chat_id = self.group_chat_id
            
        try:
            logger.debug(f"📤 Sending message to chat_id: {chat_id}")
            
            sent_message = await self.telegram_bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Message sent! Message ID: {sent_message.message_id}")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Telegram Error: {e}")
            if "chat not found" in str(e).lower():
                logger.error(f"❌ Chat ID {chat_id} not found! Make sure bot is added to the group.")
            elif "forbidden" in str(e).lower():
                logger.error(f"❌ Bot is forbidden from sending messages. Check bot permissions.")
            return False
        except Exception as e:
            logger.error(f"❌ Send Message Error: {e}")
            return False
    
    async def send_startup_message(self):
        """স্টার্টআপ মেসেজ পাঠান"""
        startup_msg = f"""
🚀 **𝐎𝐓𝐏 𝐌𝐨𝐧𝐢𝐭𝐨𝐫 𝐁𝐨𝐭 𝐀𝐜𝐭𝐢𝐯𝐚𝐭𝐞𝐝** 🚀
➖➖➖➖➖➖➖➖➖➖➖

✅ **Status:** `LIVE & MONITORING`
⚡ **Response:** `IMMEDIATE`
⏰ **Start Time:** `{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}`

📊 **Statistics:**
• Total OTPs Sent: `{self.total_otps_sent}`
• Monitoring: `ACTIVE`

➖➖➖➖➖➖➖➖➖➖➖
🤖 **OTP Monitor Bot**
        """
        
        keyboard = [
            [InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/FBDEALZONEOWNER")],
            [InlineKeyboardButton("📢 Channel", url="https://t.me/FBDEALZONEofficial")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        return await self.send_telegram_message(startup_msg, reply_markup=reply_markup)
    
    def extract_otp(self, message):
        """মেসেজ থেকে OTP এক্সট্র্যাক্ট করুন"""
        if not message:
            return None
            
        message = str(message).lower()
        
        for pattern in self.otp_patterns:
            matches = re.findall(pattern, message, re.IGNORECASE)
            if matches:
                # গ্রুপ থাকলে প্রথম গ্রুপ, না হলে পুরো ম্যাচ
                if isinstance(matches[0], tuple):
                    return matches[0][0]
                return matches[0]
        return None
    
    def create_otp_id(self, timestamp, phone_number):
        """ইউনিক OTP ID তৈরি করুন"""
        return f"{timestamp}_{phone_number}"
    
    def format_message(self, sms_data):
        """SMS ডেটা ফরম্যাট করুন"""
        try:
            timestamp = sms_data[0] if len(sms_data) > 0 else "Unknown"
            operator = sms_data[1] if len(sms_data) > 1 else "Unknown"
            phone_number = sms_data[2] if len(sms_data) > 2 else "Unknown"
            platform = sms_data[3] if len(sms_data) > 3 else "Unknown"
            message = sms_data[5] if len(sms_data) > 5 else "No message"
            cost = sms_data[7] if len(sms_data) > 7 else "0"
            
            hidden_phone = self.hide_phone_number(phone_number)
            operator_name = self.extract_operator_name(operator)
            otp_code = self.extract_otp(message)
            
            formatted_msg = f"""
🔥 **𝐅𝐈𝐑𝐒𝐓 𝐎𝐓𝐏 𝐑𝐄𝐂𝐄𝐈𝐕𝐄𝐃** 🔥
➖➖➖➖➖➖➖➖➖➖➖

📅 **Time:** `{timestamp}`
📱 **Number:** `{hidden_phone}`
🏢 **Operator:** `{operator_name}`
📟 **Platform:** `{platform}`

🟢 **OTP Code:** `{otp_code if otp_code else 'Not Found'}`

📝 **Message:**
`{message}`

➖➖➖➖➖➖➖➖➖➖➖
🤖 **OTP Monitor Bot**
            """
            return formatted_msg
        except Exception as e:
            logger.error(f"Error formatting message: {e}")
            return "Error formatting OTP message"
    
    def create_response_buttons(self):
        """রেস্পন্স বাটন তৈরি করুন"""
        keyboard = [
            [
                InlineKeyboardButton("📱 Number Channel", url="https://t.me/FBDEALZONENUMBER")
            ],
            [
                InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/FBDEALZONEOWNER"),
                InlineKeyboardButton("📢 Channel", url="https://t.me/FBDEALZONEofficial")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def fetch_sms_data(self):
        """ওয়েবসাইট থেকে SMS ডেটা ফেচ করুন - আপডেটেড URL"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 16; 23129RN51X Build/BP2A.250605.031.A3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.7632.120 Mobile Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': 'http://185.2.83.39/ints/agent/SMSCDRStats',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cookie': f'PHPSESSID={self.session_cookie}',
            'Connection': 'keep-alive',
            'Host': '185.2.83.39'
        }
        
        current_date = time.strftime("%Y-%m-%d")
        current_timestamp = str(int(time.time() * 1000))
        
        # URL এনকোডিং ঠিক করা
        params = {
            'fdate1': f'{current_date} 00:00:00',
            'fdate2': f'{current_date} 23:59:59',
            'frange': '',
            'fclient': '',
            'fnum': '',
            'fcli': '',
            'fgdate': '',
            'fgmonth': '',
            'fgrange': '',
            'fgclient': '',
            'fgnumber': '',
            'fgcli': '',
            'fg': '0',
            'sesskey': self.sesskey,
            'sEcho': '1',
            'iColumns': '9',
            'sColumns': ',,,,,,,,',
            'iDisplayStart': '0',
            'iDisplayLength': '25',
            'mDataProp_0': '0',
            'sSearch_0': '',
            'bRegex_0': 'false',
            'bSearchable_0': 'true',
            'bSortable_0': 'true',
            'mDataProp_1': '1',
            'sSearch_1': '',
            'bRegex_1': 'false',
            'bSearchable_1': 'true',
            'bSortable_1': 'true',
            'mDataProp_2': '2',
            'sSearch_2': '',
            'bRegex_2': 'false',
            'bSearchable_2': 'true',
            'bSortable_2': 'true',
            'mDataProp_3': '3',
            'sSearch_3': '',
            'bRegex_3': 'false',
            'bSearchable_3': 'true',
            'bSortable_3': 'true',
            'mDataProp_4': '4',
            'sSearch_4': '',
            'bRegex_4': 'false',
            'bSearchable_4': 'true',
            'bSortable_4': 'true',
            'mDataProp_5': '5',
            'sSearch_5': '',
            'bRegex_5': 'false',
            'bSearchable_5': 'true',
            'bSortable_5': 'true',
            'mDataProp_6': '6',
            'sSearch_6': '',
            'bRegex_6': 'false',
            'bSearchable_6': 'true',
            'bSortable_6': 'true',
            'mDataProp_7': '7',
            'sSearch_7': '',
            'bRegex_7': 'false',
            'bSearchable_7': 'true',
            'bSortable_7': 'true',
            'mDataProp_8': '8',
            'sSearch_8': '',
            'bRegex_8': 'false',
            'bSearchable_8': 'true',
            'bSortable_8': 'false',
            'sSearch': '',
            'bRegex': 'false',
            'iSortCol_0': '0',
            'sSortDir_0': 'desc',
            'iSortingCols': '1',
            '_': current_timestamp
        }
        
        try:
            logger.debug(f"🌐 Fetching data from: {self.target_url}")
            
            response = requests.get(
                self.target_url,
                headers=headers,
                params=params,
                timeout=10,
                verify=False
            )
            
            logger.debug(f"📡 API Response Status: {response.status_code}")
            
            if response.status_code == 200:
                self.consecutive_errors = 0
                
                if response.text and response.text.strip():
                    try:
                        data = response.json()
                        logger.debug(f"✅ API data received. Records: {len(data.get('aaData', []))}")
                        return data
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON Decode Error: {e}")
                        logger.debug(f"Response preview: {response.text[:200]}")
                        return None
                else:
                    logger.warning("Empty response from server")
                    return None
            else:
                logger.warning(f"HTTP Error {response.status_code}")
                self.consecutive_errors += 1
                return None
                
        except Exception as e:
            logger.error(f"Request Error: {e}")
            self.consecutive_errors += 1
            return None
    
    async def monitor_loop(self):
        """মেইন মনিটরিং লুপ"""
        logger.info("🚀 Starting OTP Monitoring...")
        
        # টেলিগ্রাম কানেকশন টেস্ট
        connection_ok = await self.test_telegram_connection()
        if not connection_ok:
            logger.error("❌ Telegram connection failed! Check your bot token and group ID.")
            logger.info("📝 Make sure:")
            logger.info("1. Bot token is correct")
            logger.info(f"2. Bot is added to group with ID: {self.group_chat_id}")
            logger.info("3. Bot has permission to send messages")
            return
        
        # স্টার্টআপ মেসেজ
        await self.send_startup_message()
        
        check_count = 0
        
        while self.is_monitoring:
            try:
                check_count += 1
                
                if check_count % 20 == 0:
                    current_time = datetime.now().strftime("%H:%M:%S")
                    logger.info(f"🔍 Check #{check_count} at {current_time}")
                
                # API কল
                data = self.fetch_sms_data()
                
                if data and 'aaData' in data:
                    sms_list = data.get('aaData', [])
                    
                    if sms_list and len(sms_list) > 0:
                        # প্রথম SMS
                        first_sms = sms_list[0]
                        
                        if len(first_sms) >= 6:
                            timestamp = first_sms[0] if len(first_sms) > 0 else ""
                            phone_number = first_sms[2] if len(first_sms) > 2 else ""
                            
                            if timestamp and phone_number:
                                otp_id = self.create_otp_id(timestamp, phone_number)
                                
                                if otp_id not in self.processed_otps:
                                    logger.info(f"🚨 NEW OTP DETECTED!")
                                    logger.info(f"📱 Phone: {phone_number}")
                                    
                                    # টেলিগ্রামে পাঠান
                                    formatted_msg = self.format_message(first_sms)
                                    reply_markup = self.create_response_buttons()
                                    
                                    success = await self.send_telegram_message(
                                        formatted_msg, 
                                        reply_markup=reply_markup
                                    )
                                    
                                    if success:
                                        self.processed_otps.add(otp_id)
                                        self.total_otps_sent += 1
                                        logger.info(f"✅ OTP SENT! Total: {self.total_otps_sent}")
                
                # 0.50 সেকেন্ড অপেক্ষা
                await asyncio.sleep(0.50)
                
            except Exception as e:
                logger.error(f"❌ Loop Error: {e}")
                logger.exception("Full traceback:")
                await asyncio.sleep(1)

async def main():
    # কনফিগারেশন
    TELEGRAM_BOT_TOKEN = "8590402708:AAFXVeapNCGZTxjDx-8tLGAXeG19LS4NTjg"
    GROUP_CHAT_ID = "-1003701215218"  # এই আইডি ভেরিফাই করুন
    SESSION_COOKIE = "ivg4t4sp9vg92kvujmquiun3fa"
    SESSKEY = "Q05RR0FRUERCUA=="
    TARGET_URL = "http://185.2.83.39/ints/agent/res/data_smscdr.php"
    
    print("=" * 60)
    print("🤖 OTP MONITOR BOT")
    print("=" * 60)
    print(f"📱 Group ID: {GROUP_CHAT_ID}")
    print(f"🌐 Target URL: {TARGET_URL}")
    print(f"🔑 Sesskey: {SESSKEY}")
    print("=" * 60)
    
    # বট তৈরি
    bot = OTPMonitorBot(
        telegram_token=TELEGRAM_BOT_TOKEN,
        group_chat_id=GROUP_CHAT_ID,
        session_cookie=SESSION_COOKIE,
        target_url=TARGET_URL,
        sesskey=SESSKEY
    )
    
    print("✅ Bot initialized!")
    print("🚀 Starting...")
    print("=" * 60)
    
    try:
        await bot.monitor_loop()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user!")
        print(f"📊 Total OTPs Sent: {bot.total_otps_sent}")
        print("👋 Goodbye!")

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()
    
    asyncio.run(main())