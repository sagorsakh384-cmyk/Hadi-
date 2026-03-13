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

# লগিং কনফিগারেশন - ফাইল লগিং যোগ করা হলো
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,
    handlers=[
        logging.FileHandler('otp_bot_debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class OTPMonitorBot:
    def __init__(self, telegram_token, group_chat_id, session_cookie, target_url, sesskey):
        self.telegram_token = telegram_token
        self.group_chat_id = str(group_chat_id).strip()
        self.session_cookie = session_cookie
        self.target_url = target_url
        self.sesskey = sesskey
        self.processed_otps = set()
        self.start_time = datetime.now()
        self.total_otps_sent = 0
        self.total_otps_detected = 0
        self.last_otp_time = None
        self.is_monitoring = True
        self.telegram_bot = Bot(token=self.telegram_token)
        
        # OTP প্যাটার্ন
        self.otp_patterns = [
            r'\b\d{3}-\d{3}\b',
            r'\b\d{5}\b',
            r'\b\d{6}\b',
            r'code[:\s]*(\d+)',
            r'otp[:\s]*(\d+)',
            r'password[:\s]*(\d+)',
            r'verification[:\s]*(\d+)',
            r'কোড[:\s]*(\d+)',
        ]
    
    async def debug_telegram(self):
        """টেলিগ্রাম কানেকশন ডিটেইলড ডিবাগ"""
        logger.info("=" * 60)
        logger.info("🔍 TELEGRAM DEBUG MODE")
        logger.info("=" * 60)
        
        try:
            # বটের ইনফো
            me = await self.telegram_bot.get_me()
            logger.info(f"✅ Bot Info:")
            logger.info(f"   - Username: @{me.username}")
            logger.info(f"   - Bot ID: {me.id}")
            logger.info(f"   - Name: {me.first_name}")
            logger.info(f"   - Can Join Groups: {me.can_join_groups}")
            logger.info(f"   - Can Read Messages: {me.can_read_all_group_messages}")
            
            # গ্রুপ আইডি ভেরিফিকেশন
            logger.info(f"📱 Target Group ID: {self.group_chat_id}")
            
            # টেস্ট মেসেজ
            logger.info("📤 Sending test message to group...")
            
            test_msg = (
                f"🔧 **Debug Test Message**\n\n"
                f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"🤖 Bot: @{me.username}\n"
                f"📱 Group ID: `{self.group_chat_id}`\n\n"
                f"If you see this, Telegram is working!"
            )
            
            keyboard = [[InlineKeyboardButton("✅ Working", callback_data="test")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            sent = await self.telegram_bot.send_message(
                chat_id=self.group_chat_id,
                text=test_msg,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
            logger.info(f"✅ Test message sent! Message ID: {sent.message_id}")
            logger.info("=" * 60)
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Telegram Error: {e}")
            logger.error(f"   - Error Type: {type(e).__name__}")
            logger.error(f"   - Error Details: {str(e)}")
            
            if "chat not found" in str(e).lower():
                logger.error("   ⚠️ GROUP NOT FOUND! Make sure:")
                logger.error("     1. Group ID is correct (including negative sign)")
                logger.error("     2. Bot is added to the group")
                logger.error("     3. Bot is not banned from the group")
            elif "forbidden" in str(e).lower():
                logger.error("   ⚠️ BOT FORBIDDEN! Make sure:")
                logger.error("     1. Bot has permission to send messages")
                logger.error("     2. Bot is not restricted in the group")
            elif "token" in str(e).lower():
                logger.error("   ⚠️ INVALID TOKEN! Check your bot token")
            
            logger.info("=" * 60)
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected Error: {e}")
            return False
    
    async def send_telegram_message(self, message, reply_markup=None):
        """টেলিগ্রাম মেসেজ পাঠান"""
        try:
            logger.debug(f"📤 Sending message to {self.group_chat_id}")
            logger.debug(f"📝 Message preview: {message[:100]}...")
            
            sent = await self.telegram_bot.send_message(
                chat_id=self.group_chat_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Message sent! ID: {sent.message_id}")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Send failed: {e}")
            return False
    
    def fetch_sms_data(self):
        """API থেকে ডেটা ফেচ করুন"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 16; 23129RN51X Build/BP2A.250605.031.A3) AppleWebKit/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': 'http://185.2.83.39/ints/agent/SMSCDRStats',
            'Cookie': f'PHPSESSID={self.session_cookie}',
            'Connection': 'keep-alive',
        }
        
        current_date = time.strftime("%Y-%m-%d")
        params = {
            'fdate1': f'{current_date} 00:00:00',
            'fdate2': f'{current_date} 23:59:59',
            'frange': '', 'fclient': '', 'fnum': '', 'fcli': '',
            'fgdate': '', 'fgmonth': '', 'fgrange': '', 'fgclient': '',
            'fgnumber': '', 'fgcli': '', 'fg': '0',
            'sesskey': self.sesskey,
            'sEcho': '1',
            'iColumns': '9',
            'sColumns': ',,,,,,,,',
            'iDisplayStart': '0',
            'iDisplayLength': '25',
            'sSearch': '', 'bRegex': 'false',
            'iSortCol_0': '0', 'sSortDir_0': 'desc', 'iSortingCols': '1',
            '_': str(int(time.time() * 1000))
        }
        
        # কলাম ডিফাইন করুন
        for i in range(9):
            params[f'mDataProp_{i}'] = str(i)
            params[f'sSearch_{i}'] = ''
            params[f'bRegex_{i}'] = 'false'
            params[f'bSearchable_{i}'] = 'true'
            params[f'bSortable_{i}'] = 'true' if i != 8 else 'false'
        
        try:
            logger.debug(f"🌐 Fetching: {self.target_url}")
            response = requests.get(
                self.target_url,
                headers=headers,
                params=params,
                timeout=10,
                verify=False
            )
            
            logger.debug(f"📡 Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                records = len(data.get('aaData', []))
                logger.debug(f"✅ Records: {records}")
                
                if records > 0:
                    # প্রথম রেকর্ড দেখান
                    first = data['aaData'][0]
                    logger.debug(f"📨 First SMS: {first[0]} - {first[2]} - {first[5][:50]}...")
                
                return data
            else:
                logger.warning(f"⚠️ HTTP {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Fetch error: {e}")
            return None
    
    def extract_otp(self, message):
        """OTP এক্সট্র্যাক্ট করুন"""
        if not message:
            return None
        
        for pattern in self.otp_patterns:
            match = re.search(pattern, str(message), re.IGNORECASE)
            if match:
                # গ্রুপ থাকলে গ্রুপ, না হলে পুরো ম্যাচ
                if match.groups():
                    return match.group(1)
                return match.group(0)
        return None
    
    def format_message(self, sms):
        """মেসেজ ফরম্যাট করুন"""
        try:
            return f"""
🔥 **𝐍𝐄𝐖 𝐎𝐓𝐏 𝐃𝐄𝐓𝐄𝐂𝐓𝐄𝐃** 🔥
➖➖➖➖➖➖➖➖➖➖

📅 **Time:** `{sms[0] if len(sms)>0 else 'N/A'}`
📱 **Number:** `{self.hide_phone_number(sms[2]) if len(sms)>2 else 'N/A'}`
🏢 **Operator:** `{sms[1] if len(sms)>1 else 'N/A'}`
📟 **Platform:** `{sms[3] if len(sms)>3 else 'N/A'}`

🔢 **OTP:** `{self.extract_otp(sms[5]) if len(sms)>5 else 'N/A'}`

📝 **Message:**
`{sms[5] if len(sms)>5 else 'N/A'}`

➖➖➖➖➖➖➖➖➖➖
🤖 **OTP Monitor Bot**
            """
        except Exception as e:
            logger.error(f"Format error: {e}")
            return "Error formatting message"
    
    def hide_phone_number(self, phone):
        """ফোন নাম্বার হাইড করুন"""
        if phone and len(phone) >= 8:
            return phone[:5] + '***' + phone[-4:]
        return phone or 'Unknown'
    
    async def monitor_loop(self):
        """মেইন লুপ"""
        logger.info("🚀 Starting monitor loop")
        
        # প্রথমে টেলিগ্রাম ডিবাগ
        telegram_ok = await self.debug_telegram()
        if not telegram_ok:
            logger.error("❌ Telegram not working! Fix Telegram issues first.")
            return
        
        check_count = 0
        
        while self.is_monitoring:
            try:
                check_count += 1
                
                if check_count % 20 == 0:
                    logger.info(f"🔄 Check #{check_count}")
                
                # ডেটা ফেচ
                data = self.fetch_sms_data()
                
                if data and 'aaData' in data and data['aaData']:
                    sms_list = data['aaData']
                    first_sms = sms_list[0]
                    
                    # ইউনিক আইডি
                    sms_id = f"{first_sms[0]}_{first_sms[2]}"
                    
                    # নতুন OTP?
                    if sms_id not in self.processed_otps:
                        self.total_otps_detected += 1
                        logger.info(f"🎯 NEW OTP #{self.total_otps_detected}")
                        logger.info(f"   Time: {first_sms[0]}")
                        logger.info(f"   Phone: {first_sms[2]}")
                        
                        # টেলিগ্রামে পাঠান
                        msg = self.format_message(first_sms)
                        keyboard = [[
                            InlineKeyboardButton("📢 Channel", url="https://t.me/FBDEALZONEofficial"),
                            InlineKeyboardButton("👨‍💻 Owner", url="https://t.me/FBDEALZONEOWNER")
                        ]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        sent = await self.send_telegram_message(msg, reply_markup)
                        
                        if sent:
                            self.processed_otps.add(sms_id)
                            self.total_otps_sent += 1
                            logger.info(f"✅ SENT! Total: {self.total_otps_sent}")
                        else:
                            logger.error("❌ Failed to send!")
                
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Loop error: {e}")
                await asyncio.sleep(1)

async def main():
    # কনফিগারেশন
    TELEGRAM_BOT_TOKEN = "8590402708:AAFXVeapNCGZTxjDx-8tLGAXeG19LS4NTjg"
    GROUP_CHAT_ID = "-1003701215218"  # এই আইডি ভেরিফাই করুন
    SESSION_COOKIE = "ivg4t4sp9vg92kvujmquiun3fa"
    SESSKEY = "Q05RR0FRUERCUA=="
    TARGET_URL = "http://185.2.83.39/ints/agent/res/data_smscdr.php"
    
    print("\n" + "="*60)
    print("🤖 OTP MONITOR BOT - DEBUG MODE")
    print("="*60)
    print(f"📱 Group ID: {GROUP_CHAT_ID}")
    print(f"🔑 Sesskey: {SESSKEY}")
    print("="*60 + "\n")
    
    bot = OTPMonitorBot(
        telegram_token=TELEGRAM_BOT_TOKEN,
        group_chat_id=GROUP_CHAT_ID,
        session_cookie=SESSION_COOKIE,
        target_url=TARGET_URL,
        sesskey=SESSKEY
    )
    
    try:
        await bot.monitor_loop()
    except KeyboardInterrupt:
        print("\n🛑 Stopped")
        print(f"📊 Detected: {bot.total_otps_detected}, Sent: {bot.total_otps_sent}")

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()
    asyncio.run(main())