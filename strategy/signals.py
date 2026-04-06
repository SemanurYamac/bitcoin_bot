"""
Bitcoin Trading Bot - Sinyal Üretici (Faz 1)
Rejim filtresi, closed candle desteği, score breakdown, config-driven ağırlıklar.
"""
import logging
from analysis.indicators import TechnicalIndicators
from config.settings import (
    SIGNAL_WEIGHTS, BUY_THRESHOLD, SELL_THRESHOLD,
    REGIME_FILTER_MULTIPLIER, EMA_LONG
)

logger = logging.getLogger(__name__)


class SignalGenerator:
    """
    Çoklu gösterge stratejisi ile AL/SAT sinyalleri üretir.
    Rejim filtresi: EMA200 altında long threshold artırılır.
    """

    def generate_signal(self, df, index=-1):
        """
        Tüm göstergeleri değerlendirerek sinyal üretir.

        Args:
            df: Göstergeler eklenmiş DataFrame
            index: Değerlendirilecek satır indeksi (-1 = son kapanmış mum)

        Returns:
            dict: {signal, score, reasons, details, score_breakdown}
        """
        summary = TechnicalIndicators.get_summary(df, index)
        if summary is None:
            return {
                'signal': 'HOLD', 'score': 0,
                'reasons': ['Yetersiz veri'],
                'details': {}, 'score_breakdown': {}
            }

        score = 0
        reasons = []
        details = {}
        score_breakdown = {}  # Her göstergenin puan kırılımı

        # ─── RSI Değerlendirmesi ───────────────────────────────
        rsi_signal = summary['rsi_signal']
        rsi_val = summary['rsi']
        details['rsi'] = {'value': rsi_val, 'signal': rsi_signal}

        if rsi_signal == 'oversold':
            rsi_score = SIGNAL_WEIGHTS['rsi']
            reasons.append(f"RSI aşırı satım ({rsi_val:.1f})")
        elif rsi_signal == 'overbought':
            rsi_score = -SIGNAL_WEIGHTS['rsi']
            reasons.append(f"RSI aşırı alım ({rsi_val:.1f})")
        elif rsi_val < 45:
            rsi_score = SIGNAL_WEIGHTS['rsi'] * 0.3
        elif rsi_val > 55:
            rsi_score = -SIGNAL_WEIGHTS['rsi'] * 0.3
        else:
            rsi_score = 0

        score += rsi_score
        details['rsi']['score'] = rsi_score
        score_breakdown['RSI'] = f"{rsi_score:+.1f} (val={rsi_val:.1f}, {rsi_signal})"

        # ─── MACD Değerlendirmesi ──────────────────────────────
        macd_signal = summary['macd_signal']
        details['macd'] = {'signal': macd_signal, 'histogram': summary['macd_histogram']}

        if macd_signal == 'bullish_crossover':
            macd_score = SIGNAL_WEIGHTS['macd']
            reasons.append("MACD yükseliş kesişimi (bullish crossover)")
        elif macd_signal == 'bearish_crossover':
            macd_score = -SIGNAL_WEIGHTS['macd']
            reasons.append("MACD düşüş kesişimi (bearish crossover)")
        elif macd_signal == 'bullish_momentum':
            macd_score = SIGNAL_WEIGHTS['macd'] * 0.5
            reasons.append("MACD yükseliş momentumu")
        elif macd_signal == 'bearish_momentum':
            macd_score = -SIGNAL_WEIGHTS['macd'] * 0.5
            reasons.append("MACD düşüş momentumu")
        else:
            macd_score = 0

        score += macd_score
        details['macd']['score'] = macd_score
        score_breakdown['MACD'] = f"{macd_score:+.1f} ({macd_signal})"

        # ─── Bollinger Bands Değerlendirmesi ───────────────────
        bb_signal = summary['bollinger_signal']
        details['bollinger'] = {
            'signal': bb_signal,
            'lower': summary['bb_lower'],
            'upper': summary['bb_upper']
        }

        if bb_signal in ('below_lower', 'near_lower'):
            bb_score = SIGNAL_WEIGHTS['bollinger']
            reasons.append(f"Fiyat Bollinger alt bandında ({bb_signal})")
        elif bb_signal in ('above_upper', 'near_upper'):
            bb_score = -SIGNAL_WEIGHTS['bollinger']
            reasons.append(f"Fiyat Bollinger üst bandında ({bb_signal})")
        else:
            bb_score = 0

        score += bb_score
        details['bollinger']['score'] = bb_score
        score_breakdown['Bollinger'] = f"{bb_score:+.1f} ({bb_signal})"

        # ─── EMA Değerlendirmesi ───────────────────────────────
        ema_signal = summary['ema_signal']
        details['ema'] = {
            'signal': ema_signal,
            'ema_short': summary['ema_short'],
            'ema_long': summary['ema_long']
        }

        if ema_signal == 'golden_cross':
            ema_score = SIGNAL_WEIGHTS['ema']
            reasons.append("Golden Cross! (EMA50 > EMA200)")
        elif ema_signal == 'death_cross':
            ema_score = -SIGNAL_WEIGHTS['ema']
            reasons.append("Death Cross! (EMA50 < EMA200)")
        elif ema_signal == 'uptrend':
            ema_score = SIGNAL_WEIGHTS['ema'] * 0.4
        elif ema_signal == 'downtrend':
            ema_score = -SIGNAL_WEIGHTS['ema'] * 0.4
        else:
            ema_score = 0

        score += ema_score
        details['ema']['score'] = ema_score
        score_breakdown['EMA'] = f"{ema_score:+.1f} ({ema_signal})"

        # ─── Hacim Değerlendirmesi ─────────────────────────────
        vol_signal = summary['volume_signal']
        details['volume'] = {'signal': vol_signal}

        if vol_signal in ('high', 'very_high'):
            vol_boost = 1.3 if vol_signal == 'very_high' else 1.0
            if score > 0:
                vol_score = SIGNAL_WEIGHTS['volume'] * vol_boost
                reasons.append(f"Yüksek hacim onayı ({vol_signal})")
            elif score < 0:
                vol_score = -SIGNAL_WEIGHTS['volume'] * vol_boost
                reasons.append(f"Yüksek hacim onayı ({vol_signal})")
            else:
                vol_score = 0
        elif vol_signal in ('low', 'very_low'):
            vol_score = 0
            if abs(score) > 3:
                reasons.append(f"⚠️ Düşük hacim - sinyal zayıf ({vol_signal})")
        else:
            vol_score = 0

        score += vol_score
        details['volume']['score'] = vol_score
        score_breakdown['Volume'] = f"{vol_score:+.1f} ({vol_signal})"

        # ─── REJİM FİLTRESİ (Faz 1 — Kritik) ──────────────────
        # EMA200 altında long sinyaller çok daha zor
        current_price = summary['price']
        ema_long_val = summary['ema_long']
        is_bearish_regime = current_price < ema_long_val if ema_long_val else False

        buy_threshold = BUY_THRESHOLD
        sell_threshold = SELL_THRESHOLD

        if is_bearish_regime:
            buy_threshold = BUY_THRESHOLD * REGIME_FILTER_MULTIPLIER
            score_breakdown['Regime'] = f"BEARISH (fiyat < EMA200, BUY eşiği {buy_threshold:.1f})"
        else:
            score_breakdown['Regime'] = f"BULLISH (fiyat > EMA200, BUY eşiği {buy_threshold:.1f})"

        # ─── Trend Filtresi (Güvenlik) ─────────────────────────
        if score >= buy_threshold and ema_signal == 'death_cross':
            score *= 0.5
            reasons.append("⚠️ Death Cross aktif - sinyal zayıflatıldı")

        if score <= sell_threshold and ema_signal == 'golden_cross':
            score *= 0.5
            reasons.append("⚠️ Golden Cross aktif - sinyal zayıflatıldı")

        # ─── Son Karar (rejim-aware threshold) ─────────────────
        if score >= buy_threshold:
            signal = 'BUY'
            reasons.insert(0, f"🟢 AL SİNYALİ (skor: {score:.1f}, eşik: {buy_threshold:.1f})")
        elif score <= sell_threshold:
            signal = 'SELL'
            reasons.insert(0, f"🔴 SAT SİNYALİ (skor: {score:.1f})")
        else:
            signal = 'HOLD'
            reasons.insert(0, f"⚪ BEKLE (skor: {score:.1f}, BUY eşiği: {buy_threshold:.1f})")

        score_breakdown['TOPLAM'] = f"{score:+.1f}"

        result = {
            'signal': signal,
            'score': round(score, 2),
            'price': summary['price'],
            'reasons': reasons,
            'details': details,
            'score_breakdown': score_breakdown,
        }

        if signal != 'HOLD':
            logger.info(
                f"{'🟢' if signal == 'BUY' else '🔴'} {signal} sinyali! "
                f"Skor: {score:.1f} | Fiyat: ${summary['price']:,.2f} | "
                f"Rejim: {'BEARISH' if is_bearish_regime else 'BULLISH'}"
            )

        return result
