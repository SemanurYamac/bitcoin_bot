"""
Bitcoin Trading Bot - Risk Yönetimi (Faz 1)
Risk-based position sizing, cooldown, max portfolio exposure, fail-safe.
"""
import logging
from datetime import datetime, date
from config.settings import (
    RISK_PER_TRADE, MAX_POSITION_PERCENT, MAX_PORTFOLIO_EXPOSURE,
    STOP_LOSS_PERCENT, TAKE_PROFIT_PERCENT,
    MAX_DRAWDOWN_PERCENT, TRAILING_STOP_PERCENT, TRAILING_ACTIVATION,
    MAX_DAILY_TRADES, COOLDOWN_CANDLES,
    PARTIAL_TP_ENABLED, PARTIAL_TP_R_MULTIPLE,
    PARTIAL_TP_CLOSE_PERCENT, PARTIAL_TP_MOVE_SL_TO_BE
)

logger = logging.getLogger(__name__)


class RiskManager:
    """Risk yönetimi — risk-based sizing, cooldown, drawdown koruması."""

    def __init__(self, symbol, initial_balance, state_manager=None):
        self.symbol = symbol
        self.state_manager = state_manager
        self.initial_balance = initial_balance
        self.peak_balance = initial_balance
        self.daily_trades = 0
        self.last_trade_date = None
        self.active_position = None
        # Cooldown tracking
        self.last_exit_candle_ts = None  # Pozisyon kapanış mum timestamp'i
        self.cooldown_remaining = 0
        # Protection mode
        self.protection_mode = False

        self._load_state()

    def _load_state(self):
        """Disk üzerinde kaydedilmiş bir state varsa (çökme sonrası) geri yükler."""
        if self.state_manager:
            stored_state = self.state_manager.get_coin_state(self.symbol)
            if stored_state:
                self.active_position = stored_state.get('active_position')
                self.cooldown_remaining = stored_state.get('cooldown_remaining', 0)
                if self.active_position:
                    logger.info(f"🔄 {self.symbol} için yarım kalan pozisyon başarıyla geri yüklendi.")

    def _save_state(self):
        """Mevcut risk durumunu diske kaydeder."""
        if self.state_manager:
            state_data = {
                'active_position': self.active_position,
                'cooldown_remaining': self.cooldown_remaining
            }
            self.state_manager.save_coin_state(self.symbol, state_data)

    def can_open_position(self, current_balance, signal, total_exposure=0):
        """
        Yeni pozisyon açılıp açılamayacağını kontrol eder.

        Args:
            current_balance: Mevcut USDT bakiyesi
            signal: Sinyal verisi
            total_exposure: Tüm açık pozisyonların toplam değeri

        Returns:
            tuple: (bool, str reason)
        """
        # Protection mode kontrolü
        if self.protection_mode:
            return False, "Protection mode aktif — işlem yapılamaz"

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
            self.protection_mode = True
            return False, f"Max drawdown aşıldı ({drawdown:.1%}), protection mode aktif!"

        # Aktif pozisyon kontrolü
        if self.active_position is not None:
            return False, "Zaten aktif bir pozisyon var"

        # Cooldown kontrolü
        if self.cooldown_remaining > 0:
            return False, f"Cooldown aktif — {self.cooldown_remaining} mum kaldı"

        # Portföy maruziyet kontrolü
        if total_exposure >= current_balance * MAX_PORTFOLIO_EXPOSURE:
            return False, f"Max portföy maruziyeti aşıldı ({MAX_PORTFOLIO_EXPOSURE:.0%})"

        # Minimum bakiye kontrolü
        if current_balance < self.initial_balance * 0.05:
            return False, "Bakiye çok düşük, işlem yapılamaz"

        return True, "OK"

    def calculate_position_size(self, current_balance, current_price, atr=None):
        """
        Risk-based position sizing.

        Formül: position_value = (bakiye × risk_per_trade) / stop_distance
        Sonra MAX_POSITION_PERCENT ile sınırla.

        Args:
            current_balance: Mevcut USDT bakiyesi
            current_price: Coin'in anlık fiyatı
            atr: ATR değeri (varsa dinamik stop-loss için)

        Returns:
            dict: {usdt_amount, coin_amount, stop_loss_price, stop_distance}
        """
        # Stop-loss mesafesini hesapla (ATR varsa dinamik, yoksa sabit)
        if atr and atr > 0:
            atr_multiplier = 2.0
            stop_distance = min(atr * atr_multiplier / current_price, 0.08)
            stop_distance = max(stop_distance, 0.02)  # Min %2
        else:
            stop_distance = STOP_LOSS_PERCENT

        # Risk-based sizing: position_value = risk_amount / stop_distance
        risk_amount = current_balance * RISK_PER_TRADE
        position_value = risk_amount / stop_distance

        # MAX_POSITION_PERCENT ile sınırla
        max_value = current_balance * MAX_POSITION_PERCENT
        position_value = min(position_value, max_value)

        # Minimum emir kontrolü (Binance min notional: $5)
        if position_value < 5.0:
            logger.warning(f"⚠️ Pozisyon çok küçük: ${position_value:.2f} < $5 minimum")
            return {'usdt_amount': 0, 'coin_amount': 0, 'stop_loss_price': 0, 'stop_distance': 0}

        coin_amount = position_value / current_price

        # Dinamik ondalık hassasiyeti
        if current_price < 0.001:
            coin_amount = round(coin_amount, 0)
        elif current_price < 1:
            coin_amount = round(coin_amount, 2)
        elif current_price < 100:
            coin_amount = round(coin_amount, 4)
        else:
            coin_amount = round(coin_amount, 8)

        stop_loss_price = round(current_price * (1 - stop_distance), 2)

        logger.info(
            f"📏 Pozisyon boyutu: ${position_value:.2f} "
            f"(risk: ${risk_amount:.2f}, SL mesafe: {stop_distance:.1%})"
        )

        return {
            'usdt_amount': round(position_value, 2),
            'coin_amount': coin_amount,
            'stop_loss_price': stop_loss_price,
            'stop_distance': stop_distance,
        }

    def calculate_take_profit(self, entry_price, side='buy'):
        """Take-profit fiyatını hesaplar."""
        if side == 'buy':
            return round(entry_price * (1 + TAKE_PROFIT_PERCENT), 2)
        else:
            return round(entry_price * (1 - TAKE_PROFIT_PERCENT), 2)

    def open_position(self, side, entry_price, amount, atr=None, open_time=None, stop_loss_price=None):
        """Yeni pozisyon açar ve risk parametrelerini ayarlar."""
        # Stop-loss hesapla
        if stop_loss_price:
            sl = stop_loss_price
        elif atr and atr > 0:
            atr_multiplier = 2.0
            dynamic_sl = min(atr * atr_multiplier / entry_price, 0.08)
            dynamic_sl = max(dynamic_sl, 0.02)
            sl = round(entry_price * (1 - dynamic_sl), 2) if side == 'buy' else round(entry_price * (1 + dynamic_sl), 2)
        else:
            sl = round(entry_price * (1 - STOP_LOSS_PERCENT), 2) if side == 'buy' else round(entry_price * (1 + STOP_LOSS_PERCENT), 2)

        take_profit = self.calculate_take_profit(entry_price, side)

        # ─── Partial TP Fiyatını Hesapla ───────────────────────────
        # 1R = giriş - stop_loss (risk mesafesi)
        # Partial TP = giriş + (R_MULTIPLE × 1R)
        if side == 'buy':
            risk_per_unit = sl - entry_price   # negatif olarak tutuyoruz → aşağıda abs
            # Gerçek risk: entry - sl, partial_tp = entry + multiple * (entry - sl)
            one_r = entry_price - sl
            partial_tp_price = round(entry_price + PARTIAL_TP_R_MULTIPLE * one_r, 2)
        else:
            one_r = sl - entry_price
            partial_tp_price = round(entry_price - PARTIAL_TP_R_MULTIPLE * one_r, 2)

        self.active_position = {
            'side': side,
            'entry_price': entry_price,
            'amount': amount,
            'stop_loss': sl,
            'take_profit': take_profit,
            'trailing_stop': None,
            'trailing_activated': False,
            'highest_price': entry_price if side == 'buy' else None,
            'lowest_price': entry_price if side == 'sell' else None,
            'open_time': (open_time or datetime.now()).isoformat(),
            # Partial TP alanları
            'partial_tp_price': partial_tp_price,
            'partial_tp_triggered': False,
        }

        self.daily_trades += 1
        self.cooldown_remaining = 0

        logger.info(
            f"📝 Pozisyon açıldı: {side.upper()} | "
            f"Giriş: ${entry_price:,.2f} | "
            f"Miktar: {amount:.8f} | "
            f"Stop-Loss: ${sl:,.2f} | "
            f"Take-Profit: ${take_profit:,.2f} | "
            f"Partial TP ({PARTIAL_TP_R_MULTIPLE}R): ${partial_tp_price:,.2f}"
        )

        self._save_state()
        return self.active_position

    def check_partial_tp(self, current_price) -> tuple:
        """
        Kısmi kâr alma (Partial Take-Profit) koşulunu kontrol eder.

        Partial TP şartları:
          - PARTIAL_TP_ENABLED = True olmalı
          - Pozisyon açık olmalı
          - Partial TP daha önce tetiklenmemiş olmalı
          - Fiyat partial_tp_price'a ulaşmış olmalı

        Returns:
            (bool, str): (tetiklenmeli_mi, neden)
        """
        if not PARTIAL_TP_ENABLED:
            return False, ""

        if self.active_position is None:
            return False, ""

        pos = self.active_position

        # Zaten tetiklendiyse bir daha tetikleme
        if pos.get('partial_tp_triggered', False):
            return False, ""

        partial_tp_price = pos.get('partial_tp_price')
        if partial_tp_price is None:
            return False, ""

        side = pos['side']
        if side == 'buy' and current_price >= partial_tp_price:
            return True, (
                f"Partial TP tetiklendi ({PARTIAL_TP_R_MULTIPLE}R @ "
                f"${partial_tp_price:,.2f}) — "
                f"%{PARTIAL_TP_CLOSE_PERCENT*100:.0f} kapatılıyor"
            )
        elif side == 'sell' and current_price <= partial_tp_price:
            return True, (
                f"Partial TP tetiklendi ({PARTIAL_TP_R_MULTIPLE}R @ "
                f"${partial_tp_price:,.2f}) — "
                f"%{PARTIAL_TP_CLOSE_PERCENT*100:.0f} kapatılıyor"
            )

        return False, ""

    def execute_partial_close(self, exit_price: float) -> dict:
        """
        Pozisyonun PARTIAL_TP_CLOSE_PERCENT'ini kapatır.

        İşlem adımları:
          1. Kapatılacak ve kalacak miktarları hesapla
          2. Kapatılan kısım için PnL hesapla (komisyon dahil)
          3. Pozisyon miktarını kalan miktar ile güncelle
          4. partial_tp_triggered = True olarak işaretle
          5. PARTIAL_TP_MOVE_SL_TO_BE = True ise SL → breakeven
          6. State'i diske kaydet

        Args:
            exit_price: Gerçekleşen satış fiyatı

        Returns:
            dict: Kısmi kapanış sonuç bilgisi
        """
        if self.active_position is None:
            logger.error("execute_partial_close: Açık pozisyon yok!")
            return {}

        pos = self.active_position
        entry_price = pos['entry_price']
        total_amount = pos['amount']
        side = pos['side']

        close_amount = total_amount * PARTIAL_TP_CLOSE_PERCENT
        remaining_amount = total_amount * (1 - PARTIAL_TP_CLOSE_PERCENT)

        # Kısmi kâr/zarar hesabı
        if side == 'buy':
            gross_pnl = (exit_price - entry_price) * close_amount
            pnl_percent = (exit_price - entry_price) / entry_price * 100
        else:
            gross_pnl = (entry_price - exit_price) * close_amount
            pnl_percent = (entry_price - exit_price) / entry_price * 100

        # Komisyon: %0.1 alış + %0.1 satış
        fee = (entry_price * close_amount * 0.001) + (exit_price * close_amount * 0.001)
        net_pnl = gross_pnl - fee

        result = {
            'side': 'partial_sell',
            'symbol': None,           # Çağıran tarafından doldurulur
            'entry_price': entry_price,
            'exit_price': exit_price,
            'partial_tp_price': pos.get('partial_tp_price'),
            'r_multiple': PARTIAL_TP_R_MULTIPLE,
            'close_percent': PARTIAL_TP_CLOSE_PERCENT,
            'close_amount': round(close_amount, 8),
            'remaining_amount': round(remaining_amount, 8),
            'gross_pnl': round(gross_pnl, 2),
            'fee': round(fee, 4),
            'net_pnl': round(net_pnl, 2),
            'pnl_percent': round(pnl_percent, 2),
        }

        # ─────────────────────────────────────────────────────────
        # Pozisyon Durumunu Güncelle
        # ─────────────────────────────────────────────────────────
        pos['amount'] = round(remaining_amount, 8)
        pos['partial_tp_triggered'] = True

        old_sl = pos['stop_loss']

        # SL breakeven'a çek (kalan %50 için sıfır risk)
        if PARTIAL_TP_MOVE_SL_TO_BE:
            pos['stop_loss'] = round(entry_price, 8)
            logger.info(
                f"🔒 [{side.upper()}] SL breakeven'a taşındı: "
                f"${old_sl:,.2f} → ${pos['stop_loss']:,.2f}"
            )

        self._save_state()

        logger.info(
            f"💰 PARTIAL TP | "
            f"Giriş: ${entry_price:,.2f} → Çıkış: ${exit_price:,.2f} | "
            f"Kapatılan: {close_amount:.8f} (%{PARTIAL_TP_CLOSE_PERCENT*100:.0f}) | "
            f"Kalan: {remaining_amount:.8f} | "
            f"Net PnL: ${net_pnl:+,.2f} ({pnl_percent:+.2f}%)"
        )

        return result

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
            state_changed = False
            if current_price > pos.get('highest_price', pos['entry_price']):
                pos['highest_price'] = current_price
                pos['trailing_stop'] = current_price * (1 - TRAILING_STOP_PERCENT)
                state_changed = True

            # Trailing sadece yeterli kâr oluşunca aktif
            min_profit_price = pos['entry_price'] * (1 + TRAILING_ACTIVATION)
            if pos.get('trailing_stop') and current_price <= pos['trailing_stop']:
                if pos['highest_price'] >= min_profit_price:
                    pos['trailing_activated'] = True
                    self._save_state()
                    return True, f"Trailing Stop tetiklendi (${pos['trailing_stop']:,.2f})"
                    
            if state_changed:
                self._save_state()

        # ─── Max Pozisyon Süresi (48 saat) ─────────────────────
        if 'open_time' in pos:
            open_dt = datetime.fromisoformat(pos['open_time'])
            hold_duration = datetime.now() - open_dt
            if hold_duration.total_seconds() > 48 * 3600:
                current_pnl = (current_price - pos['entry_price']) / pos['entry_price']
                if current_pnl < -0.01:
                    return True, f"Max süre aşıldı (48s) ve zararda ({current_pnl:.2%})"

        return False, ""

    def close_position(self, exit_price):
        """Pozisyonu kapatır, kâr/zararı hesaplar, cooldown başlatır."""
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

        # Komisyon (%0.1 alış + %0.1 satış)
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
            'duration': str(datetime.now() - datetime.fromisoformat(pos['open_time'])),
        }

        emoji = '✅' if net_pnl > 0 else '❌'
        logger.info(
            f"{emoji} Pozisyon kapatıldı | "
            f"Giriş: ${entry_price:,.2f} → Çıkış: ${exit_price:,.2f} | "
            f"Kâr/Zarar: ${net_pnl:,.2f} ({pnl_percent:+.2f}%)"
        )

        # Cooldown başlat
        self.cooldown_remaining = COOLDOWN_CANDLES
        self.last_exit_candle_ts = datetime.now().isoformat()
        self.active_position = None
        self._save_state()

        return result

    def decrement_cooldown(self):
        """Yeni mum kapanışında cooldown sayacını azalt."""
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            logger.info(f"⏳ Cooldown: {self.cooldown_remaining} mum kaldı")
            self._save_state()

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
            'cooldown_remaining': self.cooldown_remaining,
            'protection_mode': self.protection_mode,
        }
