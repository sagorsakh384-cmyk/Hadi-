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

# লগিং কনফিগারেশন - আরও ডিটেইলড করা হলো
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # DEBUG লেভেলে পরিবর্তন করা হলো
)
logger = logging.getLogger(__name__)

class OTPMonitorBot:
    def __init__(self, telegram_token, group_chat_id, session_cookie, target_url, sesskey):
        self.telegram_token = telegram_token
        self.group_chat_id = group_chat_id
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
        self.telegram_bot = Bot(token=self.telegram_token)  # বট অবজেক্ট আগেই তৈরি করে রাখা
        
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
        """টেলিগ্রামে মেসেজ সেন্ড করুন - ডিবাগ সহ"""
        if chat_id is None:
            chat_id = self.group_chat_id
            
        try:
            logger.debug(f"📤 Attempting to send message to chat_id: {chat_id}")
            logger.debug(f"📝 Message preview: {message[:100]}...")
            
            # মেসেজ পাঠান
            sent_message = await self.telegram_bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Message sent successfully! Message ID: {sent_message.message_id}")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Telegram Error: {e}")
            logger.error(f"❌ Error type: {type(e).__name__}")
            logger.error(f"❌ Chat ID: {chat_id}")
            return False
        except Exception as e:
            logger.error(f"❌ Send Message Error: {e}")
            logger.error(f"❌ Error type: {type(e).__name__}")
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
        
        logger.info("📤 Sending startup message...")
        success = await self.send_telegram_message(startup_msg, reply_markup=reply_markup)
        
        if success:
            logger.info("✅ Startup message sent to group")
        else:
            logger.error("❌ Failed to send startup message!")
            # টেলিগ্রাম কানেকশন টেস্ট
            await self.test_telegram_connection()
        
        return success
    
    async def test_telegram_connection(self):
        """টেলিগ্রাম কানেকশন টেস্ট করুন"""
        try:
            logger.info("🔍 Testing Telegram connection...")
            me = await self.telegram_bot.get_me()
            logger.info(f"✅ Bot connected! Username: @{me.username}")
            logger.info(f"✅ Bot ID: {me.id}")
            logger.info(f"✅ Bot name: {me.first_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Bot connection failed: {e}")
            return False
    
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
        """SMS ডেটা ফরম্যাট করুন"""
        timestamp = sms_data[0]
        operator = sms_data[1]
        phone_number = sms_data[2]
        platform = sms_data[3]
        message = sms_data[5]
        cost = sms_data[7]
        
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
                InlineKeyboardButton("📱 Number Channel", url="https://t.me/FBDEALZONENUMBER")
            ],
            [
                InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/FBDEALZONEOWNER"),
                InlineKeyboardButton("📢 Channel", url="https://t.me/FBDEALZONEofficial")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def fetch_sms_data(self):
        """ওয়েবসাইট থেকে SMS ডেটা ফেচ করুন"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 16; 23129RN51X Build/BP2A.250605.031.A3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.7632.120 Mobile Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': 'http://185.2.83.39/ints/agent/SMSCDRStats',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en;q=0.9,fr-DZ;q=0.8,fr;q=0.7,ru-RU;q=0.6,ru;q=0.5,kk-KZ;q=0.4,kk;q=0.3,ar-AE;q=0.2,ar;q=0.1,es-ES;q=0.1,es;q=0.1,uk-UA;q=0.1,uk;q=0.1,pt-PT;q=0.1,pt;q=0.1,fa-IR;q=0.1,fa;q=0.1,ms-MY;q=0.1,ms;q=0.1,bn-BD;q=0.1,bn;q=0.1',
            'Cookie': f'PHPSESSID={self.session_cookie}',
            'Connection': 'keep-alive',
            'Host': '185.2.83.39'
        }
        
        current_date = time.strftime("%Y-%m-%d")
        current_timestamp = str(int(time.time() * 1000))
        
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
            logger.debug(f"🌐 Fetching data from API...")
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
                
                if response.text.strip():
                    try:
                        data = response.json()
                        logger.debug(f"✅ API data received. Records: {len(data.get('aaData', []))}")
                        return data
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON Decode Error: {e}")
                        logger.debug(f"Response text: {response.text[:200]}")
                        return None
                else:
                    logger.warning("Empty response from server")
                    return None
            else:
                logger.warning(f"HTTP Error {response.status_code}")
                self.consecutive_errors += 1
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request Exception: {e}")
            self.consecutive_errors += 1
            return None
        except Exception as e:
            logger.error(f"Unexpected Error: {e}")
            self.consecutive_errors += 1
            return None
    
    async def monitor_loop(self):
        """মেইন মনিটরিং লুপ"""
        logger.info("🚀 OTP Monitoring Started - FIRST OTP ONLY")
        
        # টেলিগ্রাম কানেকশন টেস্ট
        await self.test_telegram_connection()
        
        # স্টার্টআপ মেসেজ পাঠান
        await self.send_startup_message()
        
        check_count = 0
        last_error_alert = 0
        
        while self.is_monitoring:
            try:
                check_count += 1
                current_time = datetime.now().strftime("%H:%M:%S")
                
                if check_count % 10 == 0:
                    logger.info(f"🔍 Check #{check_count} at {current_time}")
                
                # API কল
                data = self.fetch_sms_data()
                
                if data and 'aaData' in data:
                    sms_list = data['aaData']
                    
                    if sms_list:
                        logger.debug(f"📨 Total SMS records: {len(sms_list)}")
                        
                        # বৈধ SMS ফিল্টার করুন
                        valid_sms = []
                        for sms in sms_list:
                            if len(sms) >= 8 and isinstance(sms[0], str) and ':' in sms[0]:
                                valid_sms.append(sms)
                        
                        logger.debug(f"✅ Valid SMS records: {len(valid_sms)}")
                        
                        if valid_sms:
                            # প্রথম SMS নিন
                            first_sms = valid_sms[0]
                            timestamp = first_sms[0]
                            phone_number = first_sms[2]
                            message_text = first_sms[5]
                            
                            # OTP ID তৈরি করুন
                            otp_id = self.create_otp_id(timestamp, phone_number, message_text)
                            
                            if otp_id not in self.processed_otps:
                                logger.info(f"🚨 FIRST OTP DETECTED: {timestamp}")
                                logger.info(f"📱 Phone: {phone_number}")
                                logger.info(f"📝 Message: {message_text[:100]}...")
                                
                                otp_code = self.extract_otp(message_text)
                                if otp_code:
                                    logger.info(f"🔢 OTP Code: {otp_code}")
                                
                                formatted_msg = self.format_message(first_sms)
                                reply_markup = self.create_response_buttons()
                                
                                # টেলিগ্রামে পাঠান
                                logger.info("📤 Sending to Telegram...")
                                success = await self.send_telegram_message(
                                    formatted_msg, 
                                    reply_markup=reply_markup
                                )
                                
                                if success:
                                    self.processed_otps.add(otp_id)
                                    self.total_otps_sent += 1
                                    self.last_otp_time = current_time
                                    logger.info(f"✅ FIRST OTP SENT! Total: {self.total_otps_sent}")
                                else:
                                    logger.error(f"❌ Failed to send OTP to Telegram")
                            else:
                                logger.debug(f"⏩ OTP already processed: {timestamp}")
                    else:
                        logger.debug("ℹ️ No SMS records found")
                
                # 0.50 সেকেন্ড অপেক্ষা
                await asyncio.sleep(0.50)
                
            except Exception as e:
                logger.error(f"❌ Monitor Loop Error: {e}")
                logger.exception("Full traceback:")
                self.consecutive_errors += 1
                await asyncio.sleep(1)

async def main():
    # কনফিগারেশন
    TELEGRAM_BOT_TOKEN = "8590402708:AAFXVeapNCGZTxjDx-8tLGAXeG19LS4NTjg"
    GROUP_CHAT_ID = "-1003701215218"  # এটা সঠিক কিনা চেক করুন
    SESSION_COOKIE = "ivg4t4sp9vg92kvujmquiun3fa"
    SESSKEY = "Q05RR0FRUERCUA=="
    TARGET_URL = "http://185.2.83.39/ints/agent/res/data_smscdr.php"
    
    print("=" * 60)
    print("🤖 OTP MONITOR BOT - FIRST OTP ONLY")
    print("=" * 60)
    print(f"⚡ Mode: FIRST OTP ONLY")
    print(f"⏰ Check Interval: 0.50 SECONDS")
    print(f"📱 Group ID: {GROUP_CHAT_ID}")
    print(f"🌐 Target Host: 185.2.83.39")
    print(f"🔑 Sesskey: {SESSKEY}")
    print("=" * 60)
    
    # বট তৈরি করুন
    otp_bot = OTPMonitorBot(
        telegram_token=TELEGRAM_BOT_TOKEN,
        group_chat_id=GROUP_CHAT_ID,
        session_cookie=SESSION_COOKIE,
        target_url=TARGET_URL,
        sesskey=SESSKEY
    )
    
    print("✅ BOT INITIALIZED!")
    print("🚀 Starting monitoring loop...")
    print("-" * 60)
    print("🛑 Press Ctrl+C to stop")
    print("=" * 60)
    
    try:
        await otp_bot.monitor_loop()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user!")
        otp_bot.is_monitoring = False
        print(f"📊 Final Stats - Total OTPs Sent: {otp_bot.total_otps_sent}")
        print("👋 Goodbye!")

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    asyncio.run(main())