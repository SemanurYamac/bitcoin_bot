"""
Bitcoin Trading Bot - Sinyal Üretici (Faz 5 — Momentum Rider)

Strateji: EMA Hizalama + ADX Trend Filtresi + RSI Zone + Hacim Onayı

Giriş Mantığı (TÜMÜ sağlanmalı):
  1. ADX > 25 → Güçlü trend var (en kritik filtre)
  2. EMA9 > EMA21 → Momentum yukarı döndü
  3. Fiyat > EMA50 → Orta vade trend yukarı
  4. RSI 40-65 zonu → Ne aşırı alım ne aşırı satım
  5. MACD bullish → Momentum teyidi
  6. Volume > 1.2× MA → Hacim onayı (sahte breakout önleme)

Çıkış Mantığı:
  - SL: ATR × 1.5 (dinamik, volatiliteye göre)  
  - TP1: ATR × 2.0 @ %40 pozisyon (hızlı kâr kilitleme)
  - TP2: ATR × 3.0 @ %60 kalan (trailing stop ile)

Neden işe yarar:
  - ADX filtresi sideways piyasada işlemi engeller (en büyük kayıp kaynağı)
  - EMA hizalama momentum onayı sağlar
  - RSI 40-65 zone: Ne aşırı yükseliş ne dip (orta enerji = sürdürülebilir)
  - 3:1 R:R hedefi matematiği karlı yapar:
    E = (0.45 × 3R) - (0.55 × 1R) = +0.80R per trade
"""
import logging
import os
import joblib
import numpy as np
import pandas as pd
from analysis.indicators import TechnicalIndicators
from config.settings import (
    BUY_THRESHOLD, SELL_THRESHOLD,
    REGIME_FILTER_MULTIPLIER, EMA_TREND,
    ADX_THRESHOLD,
    RSI_LONG_MIN, RSI_LONG_MAX,
    RSI_SHORT_MIN, RSI_SHORT_MAX,
)

logger = logging.getLogger(__name__)

# Backwards compat
EMA_LONG = EMA_TREND


class SignalGenerator:
    """
    Momentum Rider + XGBoost ML sinyal sistemi.
    """
    
    def __init__(self):
        self.model = None
        model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'xgboost_model.joblib')
        try:
            if os.path.exists(model_path):
                self.model = joblib.load(model_path)
                logger.info(f"🧠 XGBoost AI Modeli yüklendi: {model_path}")
        except Exception as e:
            logger.error(f"⚠️ XGBoost Modeli yüklenemedi: {e}")

    def generate_signal(self, df, index=-1):
        """
        Sinyal üretimi (ML + Momentum).
        
        Öncelikle XGBoost modeline sorulur. Eğer %80+ güvenle BUY diyorsa
        tüm kuralları ezip ALIM sinyali gönderilir. Değilse geleneksel
        puanlama sistemi çalışır.

        Returns:
            dict: {signal, score, reasons, details, adx_value}
        """
        summary = TechnicalIndicators.get_summary(df, index)
        if summary is None:
            return self._hold('Yetersiz veri')

        score    = 0.0
        reasons  = []
        details  = {}
        breakdown = {}

        price      = summary['price']
        atr        = summary.get('atr', 0)
        adx_val    = summary.get('adx', 0)
        adx_signal = summary.get('adx_signal', 'sideways')

        # ═══════════════════════════════════════════════════════
        # HARD GATE 0: Makro Trend Filtresi (EMA200)
        # Fiyat EMA200 altındaysa güçlü ayı trendi var — ML de dahil hiç işlem açma
        # ═══════════════════════════════════════════════════════
        ema_trend_val = summary.get('ema_long')
        ema_slow_val  = summary.get('ema_slow')  # EMA50
        if (ema_trend_val and not pd.isna(ema_trend_val) and price < ema_trend_val
                and ema_slow_val and not pd.isna(ema_slow_val) and ema_slow_val < ema_trend_val):
            return self._hold(
                f'Ayı Rejimi: Fiyat EMA200 altı + EMA50 < EMA200 ({price:.0f} < {ema_trend_val:.0f})',
                adx=adx_val
            )

        # ═══════════════════════════════════════════════════════
        # YENİ: MAKİNE ÖĞRENMESİ (XGBoost AI)
        # Model %75'in üzerinde başarı şansı görüyorsa doğrudan AL
        # ═══════════════════════════════════════════════════════
        if self.model is not None:
            try:
                # Feature'ları hazırla (ml_trainer.py ile birebir aynı olmalı)
                bb_range = summary.get('bb_upper', 0) - summary.get('bb_lower', 0)
                bb_pos = (price - summary.get('bb_lower', 0)) / bb_range if bb_range > 0 else 0.5
                ema_long_val = summary.get('ema_long')
                if ema_long_val is None or pd.isna(ema_long_val) or ema_long_val == 0:
                    ema_dist = 0.0
                else:
                    ema_dist = (price - ema_long_val) / ema_long_val * 100
                    
                ema_short_val = summary.get('ema_short')
                if ema_short_val is None or pd.isna(ema_short_val) or ema_short_val == 0:
                    ema_short_dist = 0.0
                else:
                    ema_short_dist = (price - ema_short_val) / ema_short_val * 100
                
                # EMA50/EMA200 cross değeri
                ema_slow_v = summary.get('ema_slow')
                if ema_long_val and ema_slow_v and not pd.isna(ema_slow_v) and ema_long_val != 0:
                    ema_cross = (ema_slow_v - ema_long_val) / ema_long_val * 100
                else:
                    ema_cross = 0.0

                # Funding rate (df'de varsa, yoksa 0)
                funding_rate = 0.0
                funding_trend = 0.0
                if 'funding_rate' in df.columns:
                    fr_val = df['funding_rate'].iloc[index]
                    funding_rate = float(fr_val) * 1000 if not pd.isna(fr_val) else 0.0
                    fr_window = df['funding_rate'].iloc[max(0, index-3):index+1]
                    funding_trend = float(fr_window.mean()) * 1000 if len(fr_window) > 0 else 0.0

                # StochRSI
                stoch_rsi = summary.get('stoch_rsi_k', 50) or 50

                # Fiyat momentum (son 4 mum)
                if index >= 4:
                    price_4 = df['close'].iloc[index - 4]
                    price_momentum = (price - price_4) / price_4 * 100 if price_4 != 0 else 0.0
                else:
                    price_momentum = 0.0

                # Model sırası: ml_trainer.prepare_ml_features ile birebir aynı olmalı
                feature_list = [
                    summary.get('rsi', 50),
                    summary.get('macd_histogram', 0),
                    bb_pos,
                    summary.get('volume_ratio', 1.0),
                    ema_dist,
                    ema_cross,
                    summary.get('adx', 0),
                    stoch_rsi,
                ]
                # Funding rate özellikleri modelde varsa ekle
                n_features = len(self.model.feature_names_in_) if hasattr(self.model, 'feature_names_in_') else len(feature_list)
                if n_features >= 10:
                    feature_list += [funding_rate, funding_trend, price_momentum]
                elif n_features >= 9:
                    feature_list += [funding_rate, funding_trend]
                features = np.array([feature_list[:n_features]])
                
                # NaN/Inf temizliği
                features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
                
                # Tahmin
                prob = self.model.predict_proba(features)[0][1] # Pozitif sınıf (1) olasılığı
                
                if prob > 0.60: # %60+ Güven (Yüksek kalite filtresi)
                    return {
                        'signal': 'BUY',
                        'score': 10.0,
                        'reasons': [f"🧠 AI SCALP TAHMİNİ: %{prob*100:.1f} Yükseliş İhtimali"],
                        'details': {
                            'breakdown': {'AI_Model': f'+10 (Prob: %{prob*100:.1f})'},
                            'raw_score': 10.0,
                            'threshold': 0.0
                        },
                        'adx': adx_val
                    }
                else:
                    # Model yüklüyse ve yeterli güven yoksa, eski stratejilere gitmesini ENGELLİYORUZ!
                    return {
                        'signal': 'HOLD',
                        'score': 0.0,
                        'reasons': [f"🧠 AI Güven Yetersiz (%{prob*100:.1f})"],
                        'details': {},
                        'adx': adx_val
                    }
            except Exception as e:
                logger.error(f"AI Scalp Error: {e}")

        # ═══════════════════════════════════════════════════════
        # ESKİ: MEAN REVERSION (Dipten Alma / Panik Alımı)
        # Piyasa aşırı satıldığında ve fiyat bollinger bandından taştığında
        # tüm kuralları (ADX dahil) ezip alım yapar.
        # ═══════════════════════════════════════════════════════
        bb_lower = summary.get('bb_lower')
        rsi_val = summary.get('rsi', 50)
        
        # Bollinger alt bandının %2 altındaysa ve RSI < 25 ise (Gerçek Panik)
        if bb_lower and price < (bb_lower * 0.98) and rsi_val < 25:
            return {
                'signal': 'BUY',
                'score': 10.0,
                'reasons': ["🚨 GERÇEK PANİK (Dipten Alım)", f"RSI={rsi_val:.1f}", f"Fiyat BB alt bant %2 altında"],
                'details': {
                    'breakdown': {'MeanReversion': '+10 (Dipten Alım)'},
                    'raw_score': 10.0,
                    'threshold': 0.0
                },
                'adx': adx_val
            }

        # ═══════════════════════════════════════════════════════
        # HARD GATE 1: ADX Filtresi

        # Sideways piyasada EN BÜYÜK kayıp kaynağı trend-following
        # ADX < eşik → hiç işlem yapma
        # ═══════════════════════════════════════════════════════
        if pd.isna(adx_val) or adx_val < ADX_THRESHOLD:
            regime = 'SIDEWAYS' if not pd.isna(adx_val) else 'HESAPLANAMADI'
            return self._hold(
                f"ADX={adx_val:.1f} < {ADX_THRESHOLD} → {regime} piyasa, işlem yok",
                adx=adx_val
            )

        # ADX yönü — bull trend mi bear trend mi?
        is_adx_bull = adx_signal == 'strong_bull'
        is_adx_bear = adx_signal == 'strong_bear'
        breakdown['ADX'] = f"ADX={adx_val:.1f} → {adx_signal}"

        # ═══════════════════════════════════════════════════════
        # HARD GATE 2: EMA200 Rejim Filtresi
        # Genel piyasa yönü yukarı ise → sadece LONG
        # Genel piyasa yönü aşağı ise → BUY sinyallerini sert filtrele
        # ═══════════════════════════════════════════════════════
        ema_trend_val = summary.get('ema_long')
        is_above_trend = price > ema_trend_val if ema_trend_val else True
        buy_multiplier = 1.0 if is_above_trend else REGIME_FILTER_MULTIPLIER

        # ═══════════════════════════════════════════════════════
        # BÖLÜM 1: EMA Hizalama (En Ağırlıklı — 3.0 puan)
        # EMA9 > EMA21 > EMA50 = Tam momentum hizalama
        # ═══════════════════════════════════════════════════════
        alignment = summary.get('ema_alignment', 'neutral')
        ema_f = summary.get('ema_fast')
        ema_m = summary.get('ema_mid')
        ema_s = summary.get('ema_slow')

        if alignment == 'full_bull':               # EMA9>EMA21>EMA50
            ema_score = 3.0
            reasons.append("EMA tam hizalama ↑ (9>21>50)")
        elif alignment == 'partial_bull':           # EMA9>EMA21
            ema_score = 1.5
            reasons.append("EMA kısmi hizalama ↑ (9>21)")
        elif alignment == 'full_bear':              # EMA9<EMA21<EMA50
            ema_score = -3.0
            reasons.append("EMA tam hizalama ↓ (9<21<50)")
        elif alignment == 'partial_bear':           # EMA9<EMA21
            ema_score = -1.5
            reasons.append("EMA kısmi hizalama ↓ (9<21)")
        else:
            ema_score = 0.0

        # EMA9'un EMA21'i yeni kesmesi (EN GÜÇLÜ kurulum)
        try:
            ema_f_prev = df['ema_fast'].iloc[index - 1]
            ema_m_prev = df['ema_mid'].iloc[index - 1]
            if not pd.isna(ema_f_prev) and not pd.isna(ema_m_prev):
                if ema_f_prev <= ema_m_prev and ema_f > ema_m:
                    ema_score += 1.0  # Taze crossover bonus
                    reasons.append("🔥 EMA9 taze kesişim (fresh cross)")
                elif ema_f_prev >= ema_m_prev and ema_f < ema_m:
                    ema_score -= 1.0
                    reasons.append("🔥 EMA9 aşağı kesişim (fresh cross)")
        except (IndexError, KeyError):
            pass

        score += ema_score
        breakdown['EMA'] = f"{ema_score:+.1f} ({alignment})"

        # ═══════════════════════════════════════════════════════
        # BÖLÜM 2: MACD — Momentum Teyidi (2.0 puan)
        # ═══════════════════════════════════════════════════════
        macd_sig = summary.get('macd_signal', 'neutral')

        if macd_sig == 'bullish_crossover':
            macd_score = 2.0
            reasons.append("MACD bullish crossover")
        elif macd_sig == 'bullish_momentum':
            macd_score = 1.0
            reasons.append("MACD momentum ↑")
        elif macd_sig == 'bearish_crossover':
            macd_score = -2.0
            reasons.append("MACD bearish crossover")
        elif macd_sig == 'bearish_momentum':
            macd_score = -1.0
            reasons.append("MACD momentum ↓")
        else:
            macd_score = 0.0

        score += macd_score
        breakdown['MACD'] = f"{macd_score:+.1f} ({macd_sig})"

        # ═══════════════════════════════════════════════════════
        # BÖLÜM 3: RSI Zone Filtresi (2.0 puan)
        # Long zone: RSI 40-65 (trend içinde hareket, aşırı değil)
        # Short zone: RSI 35-60
        # ═══════════════════════════════════════════════════════
        rsi_val = summary.get('rsi', 50)
        rsi_sig = summary.get('rsi_signal', 'neutral')

        if RSI_LONG_MIN <= rsi_val <= RSI_LONG_MAX:
            # İdeal long zone: momentum var ama henüz tüketilmemiş
            rsi_score = 2.0
            reasons.append(f"RSI long zone ({rsi_val:.1f})")
        elif rsi_val < RSI_LONG_MIN:
            # Çok düşük RSI — ya oversold toparlaması ya da devam düşüş
            rsi_score = 1.0 if rsi_sig == 'oversold' else -0.5
        elif rsi_val > RSI_LONG_MAX:
            # Aşırı alım — long için zayıf, short için güçlü
            rsi_score = -2.0
            reasons.append(f"RSI aşırı alım ({rsi_val:.1f})")
        else:
            rsi_score = 0.0

        score += rsi_score
        breakdown['RSI'] = f"{rsi_score:+.1f} (val={rsi_val:.1f})"

        # ═══════════════════════════════════════════════════════
        # BÖLÜM 4: Volume Onayı (1.5 puan)
        # Breakout hacim olmadan → sahte hareket riski yüksek
        # ═══════════════════════════════════════════════════════
        vol_sig = summary.get('volume_signal', 'normal')

        if vol_sig == 'very_high':
            vol_score = 1.5 if score > 0 else -1.5
            reasons.append(f"Hacim patlaması ({vol_sig})")
        elif vol_sig in ('high', 'above_normal'):
            vol_score = 0.8 if score > 0 else -0.8
            reasons.append(f"Yüksek hacim onayı ({vol_sig})")
        elif vol_sig in ('low', 'very_low'):
            vol_score = -0.5
            reasons.append(f"⚠️ Düşük hacim — dikkat")
        else:
            vol_score = 0.0

        score += vol_score
        breakdown['Volume'] = f"{vol_score:+.1f} ({vol_sig})"

        # ═══════════════════════════════════════════════════════
        # BÖLÜM 4.5: Hacim Tuzak Tespiti (YENİ — Penaltı)
        # Fiyat yükseliyor ama hacim düşüyorsa → sahte breakout
        # Hacim spike sonrası düşüş → tuzak olasılığı
        # ═══════════════════════════════════════════════════════
        trap_penalty = 0.0
        vol_divergence = summary.get('volume_price_divergence', False)
        is_trap = summary.get('is_trap_risk', False)
        trap_desc = summary.get('volume_trap_desc', '')

        if vol_divergence and score > 0:
            trap_penalty = -1.5
            reasons.append(f"⚠️ Hacim-fiyat uyumsuzluğu — sahte breakout riski")
        elif is_trap and score > 0:
            trap_penalty = -1.0
            reasons.append(f"⚠️ Hacim tuzağı tespit edildi")

        score += trap_penalty
        if trap_penalty != 0:
            breakdown['VolTrap'] = f"{trap_penalty:+.1f} ({trap_desc[:30]}...)"

        # ═══════════════════════════════════════════════════════
        # BÖLÜM 5: EMA200 Rejim Bonus/Penaltı (1.5 puan)
        # ═══════════════════════════════════════════════════════
        if is_above_trend:
            regime_score = 1.5 if score > 0 else 0.0
            breakdown['Regime'] = f"+1.5 (EMA200 üstü, BULLISH)"
        else:
            regime_score = -1.0 if score > 0 else 0.0
            breakdown['Regime'] = f"-1.0 (EMA200 altı, BEARISH)"

        score += regime_score

        # ═══════════════════════════════════════════════════════
        # ADX Yönü — Ters trend işlemi engelle
        # ADX strong_bull iken SELL → puanı zorlaştır
        # ADX strong_bear iken BUY → puanı zorlaştır
        # ═══════════════════════════════════════════════════════
        effective_buy_threshold  = BUY_THRESHOLD * buy_multiplier
        effective_sell_threshold = SELL_THRESHOLD

        # ADX yönü ile sinyal yönü uyumlu mu?
        if is_adx_bull and score < 0:
            score *= 0.6  # ADX yukari, biz sat diyoruz → zayıflat
            reasons.append("⚠️ ADX bull trend — SAT sinyali zayıflatıldı")
        elif is_adx_bear and score > 0:
            score *= 0.6  # ADX aşağı, biz al diyoruz → zayıflat
            reasons.append("⚠️ ADX bear trend — AL sinyali zayıflatıldı")

        breakdown['Threshold'] = (f"BUY={effective_buy_threshold:.1f} | "
                                  f"SELL={effective_sell_threshold:.1f}")
        breakdown['TOPLAM'] = f"{score:+.1f}"

        # ═══════════════════════════════════════════════════════
        # KARAR
        # ═══════════════════════════════════════════════════════
        if score >= effective_buy_threshold:
            signal = 'BUY'
            reasons.insert(0, f"🟢 AL SİNYALİ (skor: {score:.1f} ≥ {effective_buy_threshold:.1f})")
        elif score <= effective_sell_threshold:
            signal = 'SELL'
            reasons.insert(0, f"🔴 SAT SİNYALİ (skor: {score:.1f})")
        else:
            signal = 'HOLD'
            reasons.insert(0, f"⚪ BEKLE (skor: {score:.1f}, BUY eşiği: {effective_buy_threshold:.1f})")

        if signal != 'HOLD':
            logger.info(
                f"{'🟢' if signal == 'BUY' else '🔴'} {signal} | "
                f"Skor: {score:.1f} | ADX: {adx_val:.1f} | "
                f"EMA: {alignment} | Fiyat: ${price:,.4f}"
            )

        return {
            'signal':          signal,
            'score':           round(score, 2),
            'price':           price,
            'adx':             adx_val,
            'ema_alignment':   alignment,
            'reasons':         reasons,
            'details':         details,
            'score_breakdown': breakdown,
        }

    # ──────────────────────────────────────────────────────────
    # Yardımcılar
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _hold(reason, adx=None):
        """HOLD sinyali döndürür."""
        return {
            'signal':          'HOLD',
            'score':           0,
            'price':           0,
            'adx':             adx,
            'ema_alignment':   'neutral',
            'reasons':         [reason],
            'details':         {},
            'score_breakdown': {'Reason': reason},
        }
