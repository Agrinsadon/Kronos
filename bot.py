"""
bot.py — Pääohjelma: ajastus + Telegram-ilmoitukset
Käynnistä: python bot.py
"""

import asyncio
import schedule
import time
import threading
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TARGET_BALANCE, STARTING_BALANCE
from trader import run_trading_cycle, load_state, portfolio_value


async def send_message(text: str):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=chunk, parse_mode="HTML")
    except TelegramError as e:
        print(f"❌ Telegram virhe: {e}")

def telegram(text: str):
    asyncio.run(send_message(text))


def format_daily_report(result: dict) -> str:
    s = result["summary"]
    actions = result["actions"]

    filled = int(s["progress_to_goal_pct"] / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)

    days_est = s.get("days_to_goal_estimate", 999)
    if days_est < 999:
        eta_text = f"⏱ Arvioitu aika tavoitteeseen: <b>{days_est} päivää</b> nykyvauhdilla"
    else:
        eta_text = "⏱ Arvioitu aika: lasketaan kun kauppoja on enemmän"

    trades_text = "\n\n".join(actions) if actions else "😴 Ei kauppoja tänään"
    positions_text = ", ".join(s["positions"]) if s["positions"] else "Ei avoimia positioita"

    daily_rate = s.get("daily_rate", 0)
    monthly_proj = ((1 + daily_rate/100) ** 30 - 1) * 100

    return (
        f"🚀 <b>KRONOS TRADER — Päiväraportti</b>\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'─'*32}\n\n"
        f"💰 <b>Portfolio:</b> {s['portfolio_value']:.2f}€\n"
        f"🏦 <b>Käteinen:</b> {s['cash']:.2f}€\n"
        f"📈 <b>Kokonaistuotto:</b> {s['total_return_pct']:+.2f}%\n"
        f"📅 <b>Päivätuotto (ka):</b> {daily_rate:+.2f}%\n"
        f"📆 <b>Kuukausiprojektio:</b> {monthly_proj:+.1f}%\n\n"
        f"🎯 <b>Tavoite: 500€ → 5000€</b>\n"
        f"{bar} {s['progress_to_goal_pct']:.1f}%\n"
        f"{eta_text}\n\n"
        f"📋 <b>Positiot:</b> {positions_text}\n"
        f"🔢 <b>Kauppoja:</b> {s['total_trades']} | "
        f"✅ <b>Win rate:</b> {s['win_rate']:.1f}%\n"
        f"🌐 <b>Universumi:</b> {s.get('universe_size', '?')} osaketta\n\n"
        f"{'─'*32}\n"
        f"{trades_text}"
    )


def daily_job():
    print(f"\n🔔 Päivittäinen sykli: {datetime.now()}")
    telegram("⏳ <b>Kronos Trader</b> aloittaa päivittäisen skannauksen...\n(Kestää ~5-15 min)")
    try:
        result = run_trading_cycle()
        telegram(format_daily_report(result))
        if result["summary"]["portfolio_value"] >= TARGET_BALANCE:
            telegram(
                f"🎉🎉🎉 <b>TAVOITE SAAVUTETTU!</b> 🎉🎉🎉\n\n"
                f"Portfolio: <b>{result['summary']['portfolio_value']:.2f}€</b>\n"
                f"500€ → 5000€ tehty! 🚀"
            )
    except Exception as e:
        telegram(f"❌ <b>Virhe:</b>\n{str(e)}")
        print(f"Virhe: {e}")


def send_startup_message():
    state = load_state()
    pv = portfolio_value(state)
    telegram(
        f"🤖 <b>Kronos Trader käynnistetty!</b>\n\n"
        f"💰 Aloitussaldo: {STARTING_BALANCE}€\n"
        f"🎯 Tavoite: {TARGET_BALANCE}€ (10x)\n"
        f"📊 Nykyarvo: {pv:.2f}€\n"
        f"⚡ Strategia: Aggressiivinen\n"
        f"🌐 Universumi: S&P 500 + Nasdaq 100\n\n"
        f"🕓 Skannaus joka arkipäivä klo 16:30"
    )


def run_scheduler():
    schedule.every().monday.at("16:30").do(daily_job)
    schedule.every().tuesday.at("16:30").do(daily_job)
    schedule.every().wednesday.at("16:30").do(daily_job)
    schedule.every().thursday.at("16:30").do(daily_job)
    schedule.every().friday.at("16:30").do(daily_job)
    print("⏰ Ajastin käynnissä — klo 16:30 ark.")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    print("🚀 Kronos Trader (aggressiivinen) käynnistyy...")
    send_startup_message()
    print("\n▶️  Ensimmäinen sykli käynnistyy...")
    daily_job()
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    print("\n✅ Botti pyörii! Ctrl+C lopettaa.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Pysäytetty.")
        telegram("🛑 <b>Kronos Trader pysäytetty.</b>")