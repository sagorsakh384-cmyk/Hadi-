import requests
import json
import time
import re
import asyncio
import os
from telegram import Bot
from telegram.error import TelegramError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import logging
from datetime import datetime

# লগিং কনফিগারেশন
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class OTPMonitorBot:
    def __init__(self, telegram_token, group_chat_id, session_cookie, phpsessid, target_url, host):
        self.telegram_token = telegram_token
        self.group_chat_id = group_chat_id
        self.session_cookie = session_cookie  # sesskey (Q05RR0FRUERCTg==)
        self.phpsessid = phpsessid            # PHPSESSID cookie
        self.target_url = target_url
        self.host = host
        self.processed_otps = set()
        self.start_time = datetime.now()
        self.total_otps_sent = 0
        self.last_otp_time = None
        self.is_monitoring = True
        
        # OTP প্যাটার্ন ডিটেকশন
        self.otp_patterns = [
            r'\b\d{3}-\d{3}\b',  # 123-456 ফরম্যাট
            r'\b\d{5}\b',        # 5 ডিজিট কোড
            r'code\s*\d+',       # "code 12345"
            r'code:\s*\d+',      # "code: 12345"
            r'কোড\s*\d+',        # বাংলা "কোড 12345"
            r'\b\d{6}\b',        # 6 ডিজিট কোড
            r'\b\d{4}\b',        # 4 ডিজিট কোড
            r'Your WhatsApp code \d+-\d+',
            r'WhatsApp code \d+-\d+',
            r'Telegram code \d+',
        ]
    
    def hide_phone_number(self, phone_number):
        """ফোন নাম্বার হাইড করুন (মাঝের ৩টি ডিজিট)"""
        if len(phone_number) >= 8:
            return phone_number[:5] + '***' + phone_number[-4:]
        return phone_number
    
    def extract_operator_name(self, operator):
        """অপারেটর থেকে শুধু দেশের নাম এক্সট্র্যাক্ট করুন"""
        parts = operator.split()
        if parts:
            return parts[0]
        return operator
    
    async def send_telegram_message(self, message, chat_id=None, reply_markup=None):
        """টেলিগ্রামে মেসেজ সেন্ড করুন"""
        if chat_id is None:
            chat_id = self.group_chat_id
            
        try:
            bot = Bot(token=self.telegram_token)
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            return True
        except TelegramError as e:
            logger.error(f"❌ Telegram Error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Send Message Error: {e}")
            return False
    
    async def send_startup_message(self):
        """বট শুরু হলে স্টার্টআপ মেসেজ সেন্ড করুন"""
        startup_msg = f"""
🚀 **𝐎𝐓𝐏 𝐌𝐨𝐧𝐢𝐭𝐨𝐫 𝐁𝐨𝐭 𝐀𝐜𝐭𝐢𝐯𝐚𝐭𝐞𝐝** 🚀
➖➖➖➖➖➖➖➖➖➖➖

✅ **𝐒𝐭𝐚𝐭𝐮𝐬:** `𝐋𝐈𝐕𝐄 & 𝐌𝐎𝐍𝐈𝐓𝐎𝐑𝐈𝐍𝐆`
⚡ **𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞:** `𝐈𝐌𝐌𝐄𝐃𝐈𝐀𝐓𝐄`
📡 **𝐌𝐨𝐝𝐞:** `𝐑𝐄𝐀𝐋-𝐓𝐈𝐌𝐄`

🎯 **𝐅𝐞𝐚𝐭𝐮𝐫𝐞𝐬:**
• First OTP Only
• Live Monitoring
• Auto Detection

⏰ **𝐒𝐭𝐚𝐫𝐭 𝐓𝐢𝐦𝐞:** `{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}`

🔔 **𝐍𝐨𝐭𝐞:** Only the FIRST OTP will be forwarded!

➖➖➖➖➖➖➖➖➖➖➖
🤖 **𝐎𝐓𝐏 𝐌𝐨𝐧𝐢𝐭𝐨𝐫 𝐁𝐨𝐭**
        """
        
        keyboard = [
            [InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/FBDEALZONEOWNER")],
            [InlineKeyboardButton("📢 Channel", url="https://t.me/FBDEALZONEofficial")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        success = await self.send_telegram_message(startup_msg, reply_markup=reply_markup)
        if success:
            logger.info("✅ Startup message sent to group")
        return success
    
    def extract_otp(self, message):
        """মেসেজ থেকে OTP এক্সট্র্যাক্ট করুন"""
        for pattern in self.otp_patterns:
            matches = re.findall(pattern, message, re.IGNORECASE)
            if matches:
                return matches[0]
        return None
    
    def create_otp_id(self, timestamp, phone_number, message):
        """ইউনিক OTP ID তৈরি করুন"""
        return f"{timestamp}_{phone_number}"
    
    def format_message(self, sms_data):
        """SMS ডেটা ফরম্যাট করুন - iColumns=7 অনুযায়ী"""
        timestamp = sms_data[0]
        operator = sms_data[1]
        phone_number = sms_data[2]
        platform = sms_data[3]
        message = sms_data[5]
        cost = sms_data[6] if len(sms_data) > 6 else "N/A"
        
        hidden_phone = self.hide_phone_number(phone_number)
        operator_name = self.extract_operator_name(operator)
        otp_code = self.extract_otp(message)
        current_time = datetime.now().strftime("%H:%M:%S")
        
        formatted_msg = f"""
🔥 **𝐅𝐈𝐑𝐒𝐓 𝐎𝐓𝐏 𝐑𝐄𝐂𝐄𝐈𝐕𝐄𝐃** 🔥
➖➖➖➖➖➖➖➖➖➖➖

📅 **𝐓𝐢𝐦𝐞:** `{timestamp}`
📱 **𝐍𝐮𝐦𝐛𝐞𝐫:** `{hidden_phone}`
🏢 **𝐎𝐩𝐞𝐫𝐚𝐭𝐨𝐫:** `{operator_name}`
📟 **𝐏𝐥𝐚𝐭𝐟𝐨𝐫𝐦:** `{platform}`

🟢 **𝐎𝐓𝐏 𝐂𝐨𝐝𝐞:** `{otp_code if otp_code else 'Processing...'}`

💰 **𝐂𝐨𝐬𝐭:** `{cost}`

📝 **𝐌𝐞𝐬𝐬𝐚𝐠𝐞:**
`{message}`

➖➖➖➖➖➖➖➖➖➖➖
🤖 **𝐎𝐓𝐏 𝐌𝐨𝐧𝐢𝐭𝐨𝐫 𝐁𝐨𝐭**
        """
        return formatted_msg
    
    def create_response_buttons(self):
        """রেস্পন্স বাটন তৈরি করুন"""
        keyboard = [
            [
                InlineKeyboardButton("📱 Number Channel", url="https://t.me/FBDEALZONEofficial")
            ],
            [
                InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/FBDEALZONEOWNER"),
                InlineKeyboardButton("📢 Channel", url="https://t.me/FBDEALZONEofficial")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def fetch_sms_data(self):
        """ওয়েবসাইট থেকে SMS ডেটা ফেচ করুন - আপডেটেড প্যারামিটার"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 16; 23129RN51X Build/BP2A.250605.031.A3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.7632.120 Mobile Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'http://{self.host}/ints/agent/SMSCDRStats',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en;q=0.9,fr-DZ;q=0.8,fr;q=0.7,ru-RU;q=0.6,ru;q=0.5,kk-KZ;q=0.4,kk;q=0.3,ar-AE;q=0.2,ar;q=0.1,es-ES;q=0.1,es;q=0.1,uk-UA;q=0.1,uk;q=0.1,pt-PT;q=0.1,pt;q=0.1,fa-IR;q=0.1,fa;q=0.1,ms-MY;q=0.1,ms;q=0.1,bn-BD;q=0.1,bn;q=0.1',
            'Cookie': f'PHPSESSID={self.phpsessid}',
            'Connection': 'keep-alive'
        }
        
        current_date = time.strftime("%Y-%m-%d")
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
            'sesskey': self.session_cookie,
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
            '_': str(int(time.time() * 1000))
        }
        
        try:
            response = requests.get(
                f"http://{self.host}{self.target_url}",
                headers=headers,
                params=params,
                timeout=10,
                verify=False
            )
            
            if response.status_code == 200:
                if response.text.strip():
                    try:
                        data = response.json()
                        return data
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON decode error: {e}")
                        return None
                else:
                    return None
            else:
                logger.error(f"HTTP {response.status_code}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return None
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return None
    
    async def monitor_loop(self):
        """মেইন মনিটরিং লুপ - শুধু প্রথম OTP এবং 0.50 সেকেন্ড ইন্টারভাল"""
        logger.info("🚀 OTP Monitoring Started - FIRST OTP ONLY")
        await self.send_startup_message()
        
        check_count = 0
        
        while self.is_monitoring:
            try:
                check_count += 1
                current_time = datetime.now().strftime("%H:%M:%S")
                
                logger.info(f"🔍 Check #{check_count} at {current_time}")
                
                # API কল
                data = self.fetch_sms_data()
                
                if data and 'aaData' in data:
                    sms_list = data['aaData']
                    
                    # বৈধ SMS ফিল্টার করুন (iColumns=7 অনুযায়ী)
                    valid_sms = [sms for sms in sms_list if len(sms) >= 9 and isinstance(sms[0], str) and ':' in sms[0]]
                    
                    if valid_sms:
                        # ✅ শুধু প্রথম SMS নিন
                        first_sms = valid_sms[0]
                        timestamp = first_sms[0]
                        phone_number = first_sms[2]
                        message_text = first_sms[5]
                        
                        # OTP ID তৈরি করুন
                        otp_id = self.create_otp_id(timestamp, phone_number, message_text)
                        
                        # ✅ শুধুমাত্র নতুন প্রথম OTP চেক করুন
                        if otp_id not in self.processed_otps:
                            logger.info(f"🚨 FIRST OTP DETECTED: {timestamp}")
                            
                            otp_code = self.extract_otp(message_text)
                            if otp_code:
                                logger.info(f"🔢 OTP Code: {otp_code}")
                                
                                formatted_msg = self.format_message(first_sms)
                                reply_markup = self.create_response_buttons()
                                
                                success = await self.send_telegram_message(
                                    formatted_msg, 
                                    reply_markup=reply_markup
                                )
                                
                                if success:
                                    # ✅ প্রসেসড লিস্টে এড করুন
                                    self.processed_otps.add(otp_id)
                                    self.total_otps_sent += 1
                                    self.last_otp_time = current_time
                                    
                                    logger.info(f"✅ FIRST OTP SENT: {timestamp} - Total: {self.total_otps_sent}")
                                else:
                                    logger.error(f"❌ Failed to send OTP: {timestamp}")
                        else:
                            logger.debug(f"⏩ First OTP Already Processed: {timestamp}")
                    else:
                        logger.info("ℹ️ No valid SMS records found")
                
                else:
                    logger.warning("⚠️ No data from API")
                
                # প্রতি 20 চেকে স্ট্যাটাস
                if check_count % 20 == 0:
                    logger.info(f"📊 Status - Total First OTPs: {self.total_otps_sent}")
                
                # ✅ 0.50 সেকেন্ড অপেক্ষা
                await asyncio.sleep(0.50)
                
            except Exception as e:
                logger.error(f"❌ Monitor Loop Error: {e}")
                await asyncio.sleep(1)

async def main():
    # Environment Variables থেকে কনফিগারেশন লোড করুন
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8590402708:AAFXVeapNCGZTxjDx-8tLGAXeG19LS4NTjg")
    GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "-1003701215218")
    SESSION_COOKIE = os.environ.get("SESSION_COOKIE", "Q05RR0FRUERCUQ==")
    PHPSESSID = os.environ.get("PHPSESSID", "hq1j3qpuo2v8bmh4i9p8ihc752")
    HOST = os.environ.get("HOST", "185.2.83.39")
    TARGET_URL = os.environ.get("TARGET_URL", "/ints/agent/res/data_smscdr.php")
    
    print("=" * 50)
    print("🤖 OTP MONITOR BOT - FIRST OTP ONLY")
    print("=" * 50)
    print("⚡ Mode: FIRST OTP ONLY")
    print("⏰ Check Interval: 0.50 SECONDS")
    print("📱 Group ID:", GROUP_CHAT_ID)
    print("🌐 Host:", HOST)
    print("📊 iColumns: 9")
    print("📥 Display Length: 25")
    print("🎯 Feature: Only first OTP from JSON")
    print("🚀 Starting bot...")
    
    # OTP মনিটর বট তৈরি করুন
    otp_bot = OTPMonitorBot(
        telegram_token=TELEGRAM_BOT_TOKEN,
        group_chat_id=GROUP_CHAT_ID,
        session_cookie=SESSION_COOKIE,
        phpsessid=PHPSESSID,
        target_url=TARGET_URL,
        host=HOST
    )
    
    print("✅ BOT STARTED SUCCESSFULLY!")
    print("🎯 Monitoring: ACTIVE")
    print("🚀 Mode: FIRST OTP ONLY")
    print("⏰ Check Speed: 0.50 seconds")
    print("📊 Each first OTP sent ONLY ONCE")
    print("-" * 50)
    print("🛑 Press Ctrl+C to stop the bot")
    print("=" * 50)
    
    # মনিটরিং শুরু করুন
    try:
        await otp_bot.monitor_loop()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user!")
        otp_bot.is_monitoring = False
        print(f"📊 Final Stats - Total OTPs Sent: {otp_bot.total_otps_sent}")
        print("👋 Goodbye!")

if __name__ == "__main__":
    # SSL warning disable
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # এসিঙ্ক্রোনাস মেইন ফাংশন রান করুন
    asyncio.run(main())
