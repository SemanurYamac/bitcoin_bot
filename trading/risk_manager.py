"""
Bitcoin Trading Bot - Risk Yönetimi Modülü
Pozisyon boyutlandırma, stop-loss, take-profit ve drawdown kontrolü.
"""
import logging
from datetime import datetime, date
from config.settings import (
    MAX_POSITION_PERCENT, STOP_LOSS_PERCENT, TAKE_PROFIT_PERCENT,
    MAX_DRAWDOWN_PERCENT, TRAILING_STOP_PERCENT, MAX_DAILY_TRADES
)

logger = logging.getLogger(__name__)


class RiskManager:
    """Risk yönetimi kurallarını uygular."""

    def __init__(self, initial_balance):
        self.initial_balance = initial_balance
        self.peak_balance = initial_balance
        self.daily_trades = 0
        self.last_trade_date = None
        self.active_position = None  # {'side', 'entry_price', 'amount', 'stop_loss', 'take_profit'}

    def can_open_position(self, current_balance, signal):
        """
        Yeni pozisyon açılıp açılamayacağını kontrol eder.

        Returns:
            tuple: (bool, str reason)
        """
        # Günlük işlem sayısı kontrolü
        today = date.today()
        if self.last_trade_date != today:
            self.daily_trades = 0
            self.last_trade_date = today

        if self.daily_trades >= MAX_DAILY_TRADES:
            return False, f"Günlük işlem limiti aşıldı ({MAX_DAILY_TRADES})"

        # Max drawdown kontrolü
        drawdown = (self.peak_balance - current_balance) / self.peak_balance
        if drawdown >= MAX_DRAWDOWN_PERCENT:
            return False, f"Max drawdown aşıldı ({drawdown:.1%} >= {MAX_DRAWDOWN_PERCENT:.1%})"

        # Aktif pozisyon kontrolü
        if self.active_position is not None:
            return False, "Zaten aktif bir pozisyon var"

        # Minimum bakiye kontrolü
        if current_balance < self.initial_balance * 0.05:
            return False, "Bakiye çok düşük, işlem yapılamaz"

        return True, "OK"

    def calculate_position_size(self, current_balance, current_price):
        """
        Pozisyon boyutunu hesaplar.

        Args:
            current_balance: Mevcut USDT bakiyesi
            current_price: BTC'nin anlık fiyatı

        Returns:
            dict: {usdt_amount, btc_amount}
        """
        # Bakiyenin belirli yüzdesini kullan
        usdt_amount = current_balance * MAX_POSITION_PERCENT

        # Minimum emir kontrolü (Binance min notional: $5)
        if usdt_amount < 5.0:
            logger.warning(f"⚠️ Pozisyon çok küçük: ${usdt_amount:.2f} < $5 minimum")
            return {'usdt_amount': 0, 'btc_amount': 0}

        btc_amount = usdt_amount / current_price

        # Dinamik ondalık hassasiyeti (düşük fiyatlı coinler için)
        if current_price < 0.001:
            btc_amount = round(btc_amount, 0)      # PEPE gibi coinler - tam sayı
        elif current_price < 1:
            btc_amount = round(btc_amount, 2)      # Küçük coinler
        elif current_price < 100:
            btc_amount = round(btc_amount, 4)      # Orta coinler
        else:
            btc_amount = round(btc_amount, 8)      # BTC, ETH gibi büyük coinler

        return {
            'usdt_amount': round(usdt_amount, 2),
            'btc_amount': btc_amount,
        }

    def calculate_stop_loss(self, entry_price, side='buy'):
        """Stop-loss fiyatını hesaplar."""
        if side == 'buy':
            return round(entry_price * (1 - STOP_LOSS_PERCENT), 2)
        else:
            return round(entry_price * (1 + STOP_LOSS_PERCENT), 2)

    def calculate_take_profit(self, entry_price, side='buy'):
        """Take-profit fiyatını hesaplar."""
        if side == 'buy':
            return round(entry_price * (1 + TAKE_PROFIT_PERCENT), 2)
        else:
            return round(entry_price * (1 - TAKE_PROFIT_PERCENT), 2)

    def open_position(self, side, entry_price, amount, atr=None, open_time=None):
        """Yeni pozisyon açar ve risk parametrelerini ayarlar.
        
        Args:
            atr: Average True Range - volatiliteye göre dinamik stop-loss için
            open_time: Pozisyon açılış zamanı (backtest için simüle edilen zaman)
        """
        # ATR varsa dinamik stop-loss hesapla (volatil coinler için daha geniş)
        if atr and atr > 0:
            atr_multiplier = 2.0  # 2x ATR stop-loss mesafesi
            dynamic_sl_percent = min(atr * atr_multiplier / entry_price, 0.08)  # Max %8
            dynamic_sl_percent = max(dynamic_sl_percent, 0.02)  # Min %2
        else:
            dynamic_sl_percent = STOP_LOSS_PERCENT

        if side == 'buy':
            stop_loss = round(entry_price * (1 - dynamic_sl_percent), 2)
            take_profit = self.calculate_take_profit(entry_price, side)
        else:
            stop_loss = round(entry_price * (1 + dynamic_sl_percent), 2)
            take_profit = self.calculate_take_profit(entry_price, side)

        self.active_position = {
            'side': side,
            'entry_price': entry_price,
            'amount': amount,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'trailing_stop': None,
            'highest_price': entry_price if side == 'buy' else None,
            'lowest_price': entry_price if side == 'sell' else None,
            'open_time': open_time or datetime.now(),
            'dynamic_sl_percent': dynamic_sl_percent,
        }

        self.daily_trades += 1

        logger.info(
            f"📝 Pozisyon açıldı: {side.upper()} | "
            f"Giriş: ${entry_price:,.2f} | "
            f"Miktar: {amount:.8f} | "
            f"Stop-Loss: ${self.active_position['stop_loss']:,.2f} | "
            f"Take-Profit: ${self.active_position['take_profit']:,.2f}"
        )

        return self.active_position

    def check_exit_conditions(self, current_price):
        """
        Mevcut pozisyon için çıkış koşullarını kontrol eder.

        Returns:
            tuple: (should_exit: bool, reason: str)
        """
        if self.active_position is None:
            return False, ""

        pos = self.active_position
        side = pos['side']

        # ─── Stop-Loss Kontrolü ────────────────────────────────
        if side == 'buy' and current_price <= pos['stop_loss']:
            return True, f"Stop-Loss tetiklendi (${pos['stop_loss']:,.2f})"
        elif side == 'sell' and current_price >= pos['stop_loss']:
            return True, f"Stop-Loss tetiklendi (${pos['stop_loss']:,.2f})"

        # ─── Take-Profit Kontrolü ──────────────────────────────
        if side == 'buy' and current_price >= pos['take_profit']:
            return True, f"Take-Profit tetiklendi (${pos['take_profit']:,.2f})"
        elif side == 'sell' and current_price <= pos['take_profit']:
            return True, f"Take-Profit tetiklendi (${pos['take_profit']:,.2f})"

        # ─── Trailing Stop Kontrolü ────────────────────────────
        if side == 'buy':
            if current_price > pos.get('highest_price', pos['entry_price']):
                pos['highest_price'] = current_price
                # Trailing stop'u güncelle
                pos['trailing_stop'] = current_price * (1 - TRAILING_STOP_PERCENT)

            if pos.get('trailing_stop') and current_price <= pos['trailing_stop']:
                # Trailing stop ancak %3+ kârdayken aktif olsun
                min_profit_for_trail = pos['entry_price'] * 1.03
                if pos['trailing_stop'] > min_profit_for_trail:
                    return True, f"Trailing Stop tetiklendi (${pos['trailing_stop']:,.2f})"

        # ─── Max Pozisyon Süresi (48 saat) ─────────────────────
        if 'open_time' in pos:
            hold_duration = datetime.now() - pos['open_time']
            if hold_duration.total_seconds() > 48 * 3600:  # 48 saat
                current_pnl = (current_price - pos['entry_price']) / pos['entry_price']
                if current_pnl < -0.01:  # Zarardaysa kapat
                    return True, f"Max süre aşıldı (48s) ve zararda ({current_pnl:.2%})"

        return False, ""

    def close_position(self, exit_price):
        """
        Pozisyonu kapatır ve kâr/zararı hesaplar.

        Returns:
            dict: İşlem sonucu
        """
        if self.active_position is None:
            return None

        pos = self.active_position
        side = pos['side']
        entry_price = pos['entry_price']
        amount = pos['amount']

        # Kâr/zarar hesapla
        if side == 'buy':
            pnl = (exit_price - entry_price) * amount
            pnl_percent = (exit_price - entry_price) / entry_price * 100
        else:
            pnl = (entry_price - exit_price) * amount
            pnl_percent = (entry_price - exit_price) / entry_price * 100

        # Komisyon hesapla (%0.1 alış + %0.1 satış)
        fee = (entry_price * amount * 0.001) + (exit_price * amount * 0.001)
        net_pnl = pnl - fee

        result = {
            'side': side,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'amount': amount,
            'pnl': round(pnl, 2),
            'fee': round(fee, 2),
            'net_pnl': round(net_pnl, 2),
            'pnl_percent': round(pnl_percent, 2),
            'duration': datetime.now() - pos['open_time'],
        }

        emoji = '✅' if net_pnl > 0 else '❌'
        logger.info(
            f"{emoji} Pozisyon kapatıldı | "
            f"Giriş: ${entry_price:,.2f} → Çıkış: ${exit_price:,.2f} | "
            f"Kâr/Zarar: ${net_pnl:,.2f} ({pnl_percent:+.2f}%)"
        )

        self.active_position = None
        return result

    def update_peak_balance(self, current_balance):
        """Zirve bakiyeyi günceller."""
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance

    def get_risk_status(self, current_balance):
        """Risk durumu özetini verir."""
        drawdown = (self.peak_balance - current_balance) / self.peak_balance if self.peak_balance > 0 else 0

        return {
            'initial_balance': self.initial_balance,
            'current_balance': current_balance,
            'peak_balance': self.peak_balance,
            'drawdown': round(drawdown * 100, 2),
            'max_drawdown_limit': MAX_DRAWDOWN_PERCENT * 100,
            'daily_trades': self.daily_trades,
            'max_daily_trades': MAX_DAILY_TRADES,
            'has_active_position': self.active_position is not None,
            'active_position': self.active_position,
        }
