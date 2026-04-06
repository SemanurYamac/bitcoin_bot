"""
Bitcoin Trading Bot - Telegram Bildirim Modülü (Faz 1)
Score breakdown, rejim bilgisi, profesyonel mesaj formatları.
"""
import logging
import asyncio
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCAN_INTERVAL_MINUTES

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
                asyncio.ensure_future(self._send_message_async(text, parse_mode))
            else:
                loop.run_until_complete(self._send_message_async(text, parse_mode))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._send_message_async(text, parse_mode))

    def send_signal(self, signal_data):
        """
        Trading sinyali gönderir — score breakdown dahil.
        """
        signal = signal_data['signal']

        if signal == 'BUY':
            emoji = '🟢'
            header = '📈 AL SİNYALİ'
        elif signal == 'SELL':
            emoji = '🔴'
            header = '📉 SAT SİNYALİ'
        else:
            return

        reasons = '\n'.join([f"  • {r}" for r in signal_data.get('reasons', [])[1:]])
        symbol_name = signal_data.get('symbol', 'BTC/USDT')

        # Score breakdown formatla
        breakdown = signal_data.get('score_breakdown', {})
        breakdown_lines = []
        for key, val in breakdown.items():
            if key == 'TOPLAM':
                breakdown_lines.append(f"  <b>TOPLAM: {val}</b>")
            else:
                breakdown_lines.append(f"  {key}: {val}")
        breakdown_text = '\n'.join(breakdown_lines)

        message = (
            f"{emoji} <b>{header}</b>\n"
            f"🪙 <b>{symbol_name}</b>\n\n"
            f"💰 Fiyat: <code>${signal_data['price']:,.2f}</code>\n"
            f"📊 Skor: <code>{signal_data['score']}</code>\n\n"
            f"📝 <b>Nedenler:</b>\n{reasons}\n\n"
            f"🔍 <b>Skor Kırılımı:</b>\n{breakdown_text}\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        self.send_message(message)

    def send_trade_notification(self, trade_result):
        """İşlem bildirimi gönderir."""
        side = trade_result.get('side', '').upper()
        emoji = '🟢' if side == 'BUY' else '🔴'

        symbol_name = trade_result.get('symbol', 'BTC/USDT')
        coin = symbol_name.split('/')[0]

        message = (
            f"{emoji} <b>İŞLEM GERÇEKLEŞTİ</b>\n"
            f"🪙 <b>{symbol_name}</b>\n\n"
            f"📌 {side}\n"
            f"💰 Fiyat: <code>${trade_result.get('price', 0):,.2f}</code>\n"
            f"📦 Miktar: <code>{trade_result.get('amount', 0):.8f} {coin}</code>\n"
            f"💵 Toplam: <code>${trade_result.get('cost', 0):,.2f}</code>\n"
            f"💸 Komisyon: <code>${trade_result.get('fee', 0):,.4f}</code>\n"
            f"🛑 Stop-Loss: <code>${trade_result.get('stop_loss', 0):,.2f}</code>\n"
            f"🎯 Take-Profit: <code>${trade_result.get('take_profit', 0):,.2f}</code>\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        self.send_message(message)

    def send_position_closed(self, result):
        """Pozisyon kapanış bildirimi gönderir."""
        emoji = '✅' if result['net_pnl'] > 0 else '❌'
        symbol_name = result.get('symbol', 'BTC/USDT')
        coin = symbol_name.split('/')[0]

        message = (
            f"{emoji} <b>POZİSYON KAPATILDI</b>\n"
            f"🪙 <b>{symbol_name}</b>\n\n"
            f"📌 Giriş: <code>${result['entry_price']:,.2f}</code>\n"
            f"📌 Çıkış: <code>${result['exit_price']:,.2f}</code>\n"
            f"📦 Miktar: <code>{result['amount']:.8f} {coin}</code>\n\n"
            f"{'💰 Kâr' if result['net_pnl'] > 0 else '💸 Zarar'}: "
            f"<code>${result['net_pnl']:+,.2f} ({result['pnl_percent']:+.2f}%)</code>\n"
            f"⏳ Süre: <code>{result['duration']}</code>\n"
            f"⏳ Cooldown: 2 mum bekleniyor\n\n"
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

    def send_scan_summary(self, scan_results, active_positions=0):
        """Tarama döngüsü özetini gönderir."""
        now = datetime.now().strftime('%H:%M')

        buy_signals = [r for r in scan_results if r['signal'] == 'BUY']
        sell_signals = [r for r in scan_results if r['signal'] == 'SELL']
        hold_signals = [r for r in scan_results if r['signal'] == 'HOLD']
        skip_signals = [r for r in scan_results if r['signal'] == 'SKIP']

        lines = [f"📊 <b>TARAMA ÖZETİ</b> ({now})\n"]
        lines.append(f"📌 Aktif Pozisyon: {active_positions}")
        lines.append(f"🟢 AL: {len(buy_signals)} | 🔴 SAT: {len(sell_signals)} | "
                     f"⚪ BEKLE: {len(hold_signals)} | ⏭ ATLA: {len(skip_signals)}\n")

        if buy_signals:
            lines.append("🟢 <b>AL Sinyalleri:</b>")
            for r in sorted(buy_signals, key=lambda x: x['score'], reverse=True):
                coin = r['symbol'].split('/')[0]
                regime = r.get('regime', '')
                lines.append(f"  • {coin} | ${r['price']:,.2f} | skor: {r['score']:+.1f} {regime}")
            lines.append("")

        if sell_signals:
            lines.append("🔴 <b>SAT Sinyalleri:</b>")
            for r in sorted(sell_signals, key=lambda x: x['score']):
                coin = r['symbol'].split('/')[0]
                lines.append(f"  • {coin} | ${r['price']:,.2f} | skor: {r['score']:+.1f}")
            lines.append("")

        if hold_signals:
            sorted_hold = sorted(hold_signals, key=lambda x: x['score'], reverse=True)
            lines.append("⚪ <b>Beklemede:</b>")
            for r in sorted_hold:
                coin = r['symbol'].split('/')[0]
                regime = r.get('regime', '')
                lines.append(f"  • {coin} | ${r['price']:,.2f} | skor: {r['score']:+.1f} {regime}")

        lines.append(f"\n⏰ Sonraki tarama: ~{SCAN_INTERVAL_MINUTES} dakika sonra")

        self.send_message('\n'.join(lines))

    def send_bot_started(self):
        """Bot başlangıç bildirimi."""
        message = (
            f"🤖 <b>Bitcoin Bot Başlatıldı! (Faz 1)</b>\n\n"
            f"🔧 Yeni özellikler:\n"
            f"  • Closed candle sinyal\n"
            f"  • Rejim filtresi (EMA200)\n"
            f"  • Risk-based sizing (%1/trade)\n"
            f"  • Cooldown (2 mum)\n"
            f"  • Fail-safe koruma\n\n"
            f"📊 Piyasa taranıyor...\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.send_message(message)

    def send_protection_mode(self, reason):
        """Protection mode bildirimi."""
        message = (
            f"🛡️ <b>KORUMA MODU AKTİF</b>\n\n"
            f"Sebep: <code>{reason}</code>\n"
            f"Bot yeni işlem açmayacak.\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.send_message(message)
