"""
Bitcoin Trading Bot - Telegram Bildirim Modülü
Alım/satım sinyallerini ve durum raporlarını Telegram üzerinden gönderir.
"""
import logging
import asyncio
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram üzerinden bildirim gönderir."""

    def __init__(self, token=None, chat_id=None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.bot = None
        self.enabled = bool(self.token and self.chat_id)

        if self.enabled:
            self.bot = Bot(token=self.token)
            logger.info("✅ Telegram bot bağlantısı hazır")
        else:
            logger.warning("⚠️ Telegram bildirim devre dışı (token veya chat_id eksik)")

    async def _send_message_async(self, text, parse_mode='HTML'):
        """Asenkron mesaj gönderir."""
        if not self.enabled:
            logger.debug(f"Telegram devre dışı, mesaj gönderilmedi: {text[:50]}...")
            return False

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode
            )
            return True
        except TelegramError as e:
            logger.error(f"❌ Telegram hata: {e}")
            return False

    def send_message(self, text, parse_mode='HTML'):
        """Senkron mesaj gönderir."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Eğer bir event loop zaten çalışıyorsa
                asyncio.ensure_future(self._send_message_async(text, parse_mode))
            else:
                loop.run_until_complete(self._send_message_async(text, parse_mode))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._send_message_async(text, parse_mode))

    def send_signal(self, signal_data):
        """
        Trading sinyali gönderir.

        Args:
            signal_data: dict with signal, score, price, reasons
        """
        signal = signal_data['signal']
        
        if signal == 'BUY':
            emoji = '🟢'
            header = '📈 AL SİNYALİ'
        elif signal == 'SELL':
            emoji = '🔴'
            header = '📉 SAT SİNYALİ'
        else:
            return  # HOLD sinyali bildirmiyoruz

        reasons = '\n'.join([f"  • {r}" for r in signal_data.get('reasons', [])[1:]])

        message = (
            f"{emoji} <b>{header}</b>\n\n"
            f"💰 Fiyat: <code>${signal_data['price']:,.2f}</code>\n"
            f"📊 Skor: <code>{signal_data['score']}</code>\n\n"
            f"📝 <b>Nedenler:</b>\n{reasons}\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        self.send_message(message)

    def send_trade_notification(self, trade_result):
        """İşlem bildirimi gönderir."""
        side = trade_result.get('side', '').upper()
        emoji = '🟢' if side == 'BUY' else '🔴'

        message = (
            f"{emoji} <b>İŞLEM GERÇEKLEŞTİ</b>\n\n"
            f"📌 {side}\n"
            f"💰 Fiyat: <code>${trade_result.get('price', 0):,.2f}</code>\n"
            f"📦 Miktar: <code>{trade_result.get('amount', 0):.6f} BTC</code>\n"
            f"💵 Toplam: <code>${trade_result.get('cost', 0):,.2f}</code>\n"
            f"💸 Komisyon: <code>${trade_result.get('fee', 0):,.4f}</code>\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        self.send_message(message)

    def send_position_closed(self, result):
        """Pozisyon kapanış bildirimi gönderir."""
        emoji = '✅' if result['net_pnl'] > 0 else '❌'

        message = (
            f"{emoji} <b>POZİSYON KAPATILDI</b>\n\n"
            f"📌 Giriş: <code>${result['entry_price']:,.2f}</code>\n"
            f"📌 Çıkış: <code>${result['exit_price']:,.2f}</code>\n"
            f"📦 Miktar: <code>{result['amount']:.6f} BTC</code>\n\n"
            f"{'💰 Kâr' if result['net_pnl'] > 0 else '💸 Zarar'}: "
            f"<code>${result['net_pnl']:+,.2f} ({result['pnl_percent']:+.2f}%)</code>\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        self.send_message(message)

    def send_daily_report(self, report_data):
        """Günlük rapor gönderir."""
        message = (
            f"📊 <b>GÜNLÜK RAPOR</b>\n"
            f"{'━' * 20}\n\n"
            f"💰 Bakiye: <code>${report_data.get('balance', 0):,.2f}</code>\n"
            f"📈 Günlük Değişim: <code>{report_data.get('daily_change', 0):+.2f}%</code>\n"
            f"📊 Toplam Getiri: <code>{report_data.get('total_return', 0):+.2f}%</code>\n\n"
            f"🔄 Bugünkü İşlem: <code>{report_data.get('daily_trades', 0)}</code>\n"
            f"📌 Aktif Pozisyon: <code>{'Var' if report_data.get('has_position') else 'Yok'}</code>\n\n"
            f"💹 BTC Fiyatı: <code>${report_data.get('btc_price', 0):,.2f}</code>\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        self.send_message(message)

    def send_error(self, error_message):
        """Hata bildirimi gönderir."""
        message = (
            f"🚨 <b>HATA</b>\n\n"
            f"<code>{error_message}</code>\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.send_message(message)

    def send_bot_started(self):
        """Bot başlangıç bildirimi."""
        message = (
            f"🤖 <b>Bitcoin Bot Başlatıldı!</b>\n\n"
            f"📊 Piyasa taranıyor...\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.send_message(message)
