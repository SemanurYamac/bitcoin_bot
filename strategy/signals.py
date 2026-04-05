"""
Bitcoin Trading Bot - Sinyal Üretici
Teknik göstergeleri birleştirerek alım/satım sinyalleri üretir.
"""
import logging
from analysis.indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


class SignalGenerator:
    """
    Çoklu gösterge stratejisi ile AL/SAT sinyalleri üretir.
    Her gösterge bir puan verir, toplam puan eşik değerini geçerse sinyal oluşur.
    """

    # Sinyal ağırlıkları
    WEIGHTS = {
        'rsi': 2.0,
        'macd': 2.5,
        'bollinger': 1.5,
        'ema': 2.0,
        'volume': 1.0,
    }

    # Karar eşikleri
    BUY_THRESHOLD = 5.0    # Bu puan üstünde AL sinyali
    SELL_THRESHOLD = -5.0   # Bu puan altında SAT sinyali

    def generate_signal(self, df, index=-1):
        """
        Tüm göstergeleri değerlendirerek sinyal üretir.

        Args:
            df: Göstergeler eklenmiş DataFrame
            index: Değerlendirilecek satır indeksi

        Returns:
            dict: {signal, score, reasons, details}
                signal: 'BUY', 'SELL', veya 'HOLD'
                score: Toplam puan
                reasons: Sinyal nedenleri listesi
                details: Her göstergenin detaylı bilgisi
        """
        summary = TechnicalIndicators.get_summary(df, index)
        if summary is None:
            return {'signal': 'HOLD', 'score': 0, 'reasons': ['Yetersiz veri'], 'details': {}}

        score = 0
        reasons = []
        details = {}

        # ─── RSI Değerlendirmesi ───────────────────────────────
        rsi_signal = summary['rsi_signal']
        rsi_val = summary['rsi']
        details['rsi'] = {'value': rsi_val, 'signal': rsi_signal}

        if rsi_signal == 'oversold':
            rsi_score = self.WEIGHTS['rsi']
            reasons.append(f"RSI aşırı satım ({rsi_val:.1f})")
        elif rsi_signal == 'overbought':
            rsi_score = -self.WEIGHTS['rsi']
            reasons.append(f"RSI aşırı alım ({rsi_val:.1f})")
        elif rsi_val < 45:
            rsi_score = self.WEIGHTS['rsi'] * 0.3
        elif rsi_val > 55:
            rsi_score = -self.WEIGHTS['rsi'] * 0.3
        else:
            rsi_score = 0

        score += rsi_score
        details['rsi']['score'] = rsi_score

        # ─── MACD Değerlendirmesi ──────────────────────────────
        macd_signal = summary['macd_signal']
        details['macd'] = {'signal': macd_signal, 'histogram': summary['macd_histogram']}

        if macd_signal == 'bullish_crossover':
            macd_score = self.WEIGHTS['macd']
            reasons.append("MACD yükseliş kesişimi (bullish crossover)")
        elif macd_signal == 'bearish_crossover':
            macd_score = -self.WEIGHTS['macd']
            reasons.append("MACD düşüş kesişimi (bearish crossover)")
        elif macd_signal == 'bullish_momentum':
            macd_score = self.WEIGHTS['macd'] * 0.5
            reasons.append("MACD yükseliş momentumu")
        elif macd_signal == 'bearish_momentum':
            macd_score = -self.WEIGHTS['macd'] * 0.5
            reasons.append("MACD düşüş momentumu")
        else:
            macd_score = 0

        score += macd_score
        details['macd']['score'] = macd_score

        # ─── Bollinger Bands Değerlendirmesi ───────────────────
        bb_signal = summary['bollinger_signal']
        details['bollinger'] = {
            'signal': bb_signal,
            'lower': summary['bb_lower'],
            'upper': summary['bb_upper']
        }

        if bb_signal in ('below_lower', 'near_lower'):
            bb_score = self.WEIGHTS['bollinger']
            reasons.append(f"Fiyat Bollinger alt bandında ({bb_signal})")
        elif bb_signal in ('above_upper', 'near_upper'):
            bb_score = -self.WEIGHTS['bollinger']
            reasons.append(f"Fiyat Bollinger üst bandında ({bb_signal})")
        else:
            bb_score = 0

        score += bb_score
        details['bollinger']['score'] = bb_score

        # ─── EMA Değerlendirmesi ───────────────────────────────
        ema_signal = summary['ema_signal']
        details['ema'] = {
            'signal': ema_signal,
            'ema_short': summary['ema_short'],
            'ema_long': summary['ema_long']
        }

        if ema_signal == 'golden_cross':
            ema_score = self.WEIGHTS['ema']
            reasons.append("Golden Cross! (EMA50 > EMA200)")
        elif ema_signal == 'death_cross':
            ema_score = -self.WEIGHTS['ema']
            reasons.append("Death Cross! (EMA50 < EMA200)")
        elif ema_signal == 'uptrend':
            ema_score = self.WEIGHTS['ema'] * 0.4
        elif ema_signal == 'downtrend':
            ema_score = -self.WEIGHTS['ema'] * 0.4
        else:
            ema_score = 0

        score += ema_score
        details['ema']['score'] = ema_score

        # ─── Hacim Değerlendirmesi ─────────────────────────────
        vol_signal = summary['volume_signal']
        details['volume'] = {'signal': vol_signal}

        # Hacim doğrulayıcı olarak kullanılır (sinyal yönünü güçlendirir)
        if vol_signal in ('high', 'very_high'):
            vol_boost = 1.3 if vol_signal == 'very_high' else 1.0
            if score > 0:  # AL yönünde ise hacim güçlendirir
                vol_score = self.WEIGHTS['volume'] * vol_boost
                reasons.append(f"Yüksek hacim onayı ({vol_signal})")
            elif score < 0:
                vol_score = -self.WEIGHTS['volume'] * vol_boost
                reasons.append(f"Yüksek hacim onayı ({vol_signal})")
            else:
                vol_score = 0
        elif vol_signal in ('low', 'very_low'):
            # Düşük hacimde sinyaller daha az güvenilir
            vol_score = 0
            if abs(score) > 3:
                reasons.append(f"⚠️ Düşük hacim - sinyal zayıf ({vol_signal})")
        else:
            vol_score = 0

        score += vol_score
        details['volume']['score'] = vol_score

        # ─── Trend Filtresi (Güvenlik) ─────────────────────────
        # Güçlü düşüş trendinde AL sinyali verme
        if score >= self.BUY_THRESHOLD and ema_signal == 'death_cross':
            score *= 0.5  # Skoru yarıya düşür
            reasons.append("⚠️ Death Cross aktif - sinyal zayıflatıldı")

        # Güçlü yükseliş trendinde SAT sinyali verme
        if score <= self.SELL_THRESHOLD and ema_signal == 'golden_cross':
            score *= 0.5
            reasons.append("⚠️ Golden Cross aktif - sinyal zayıflatıldı")

        # ─── Son Karar ────────────────────────────────────────
        if score >= self.BUY_THRESHOLD:
            signal = 'BUY'
            reasons.insert(0, f"🟢 AL SİNYALİ (skor: {score:.1f})")
        elif score <= self.SELL_THRESHOLD:
            signal = 'SELL'
            reasons.insert(0, f"🔴 SAT SİNYALİ (skor: {score:.1f})")
        else:
            signal = 'HOLD'
            reasons.insert(0, f"⚪ BEKLE (skor: {score:.1f})")

        result = {
            'signal': signal,
            'score': round(score, 2),
            'price': summary['price'],
            'reasons': reasons,
            'details': details,
        }

        if signal != 'HOLD':
            logger.info(f"{'🟢' if signal == 'BUY' else '🔴'} {signal} sinyali! "
                       f"Skor: {score:.1f} | Fiyat: ${summary['price']:,.2f}")

        return result
