"""
run.py — نقطة الدخول الرئيسية لتشغيل البوت

الاستخدام:
    python run.py
"""

from music_bot.main import run
from keep_alive import start as start_keep_alive

if __name__ == "__main__":
    start_keep_alive()  # سيرفر صغير يلبي شرط Render Web Service + UptimeRobot
    run()
