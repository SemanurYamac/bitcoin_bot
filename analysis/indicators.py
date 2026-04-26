"""
Bitcoin Trading Bot - Teknik Göstergeler Modülü (Faz 5 — Momentum Rider)

Faz 5 Eklemeleri:
  - ADX (Average Directional Index): Trend gücü filtresi
    ADX > 25 → güçlü trend var → işlem yap
    ADX < 20 → sideways → bekle
  - EMA9, EMA21: Hızlı momentum EMA'ları (yeni)
  - EMA50: Orta vade trend (yeni, EMA_SHORT → EMA50)
  - EMA Hizalama: EMA9 > EMA21 > EMA50 = tam momentum
"""
import pandas as pd
import pandas_ta as ta
import numpy as np
import logging
from config.settings import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BOLLINGER_PERIOD, BOLLINGER_STD,
    EMA_FAST, EMA_MID, EMA_SLOW, EMA_TREND,
    ADX_PERIOD, VOLUME_MA_PERIOD
)

logger = logging.getLogger(__name__)

# Backwards compat için EMA_LONG = EMA_TREND
EMA_LONG = EMA_TREND


class TechnicalIndicators:
    """Teknik analiz göstergelerini hesaplar ve DataFrame'e ekler."""

    @staticmethod
    def calculate_all(df):
        """
        Tüm teknik göstergeleri hesaplar ve DataFrame'e ekler.

        Faz 5 göstergeleri:
          - RSI 14 (momentum osilatör)
          - MACD 12/26/9 (trend dönüşü)
          - Bollinger Bands 20/2 (volatilite kanalı)
          - EMA 9, 21, 50, 200 (hizalama + trend yönü)
          - ATR 14 (volatilite → dinamik SL/TP)
          - ADX 14 (trend gücü filtresi) ← YENİ
          - Volume MA + Ratio (hacim onayı)
          - StochRSI (hızlı momentum osilatör)

        Args:
            df: pandas DataFrame (open, high, low, close, volume sütunları)

        Returns:
            pandas DataFrame: Göstergeler eklenmiş DataFrame
        """
        df = df.copy()

        # ── RSI ─────────────────────────────────────────────────
        df['rsi'] = ta.rsi(df['close'], length=RSI_PERIOD)

        # ── MACD ────────────────────────────────────────────────
        macd_result = ta.macd(df['close'],
                               fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
        macd_cols = macd_result.columns.tolist()
        df['macd']           = macd_result[macd_cols[0]]
        df['macd_histogram'] = macd_result[macd_cols[1]]
        df['macd_signal_line'] = macd_result[macd_cols[2]]

        # ── Bollinger Bands ──────────────────────────────────────
        bbands = ta.bbands(df['close'], length=BOLLINGER_PERIOD, std=BOLLINGER_STD)
        df['bb_lower']     = bbands.iloc[:, 0]
        df['bb_middle']    = bbands.iloc[:, 1]
        df['bb_upper']     = bbands.iloc[:, 2]
        df['bb_bandwidth'] = bbands.iloc[:, 3] if bbands.shape[1] > 3 else np.nan
        df['bb_percent']   = bbands.iloc[:, 4] if bbands.shape[1] > 4 else np.nan

        # ── EMA Göstergeleri (Faz 5 — 4 Katman) ────────────────
        # EMA9:  Hızlı momentum — giriş zamanlaması
        # EMA21: Orta momentum — trend doğrulama
        # EMA50: Orta vade trend — yön filtresi
        # EMA200: Uzun vade trend — rejim filtresi
        df['ema_fast']  = ta.ema(df['close'], length=EMA_FAST)   # 9
        df['ema_mid']   = ta.ema(df['close'], length=EMA_MID)    # 21
        df['ema_slow']  = ta.ema(df['close'], length=EMA_SLOW)   # 50
        df['ema_trend'] = ta.ema(df['close'], length=EMA_TREND)  # 200

        # Backwards compat için eski isimler
        df['ema_short'] = df['ema_slow']   # eski EMA_SHORT = 50
        df['ema_long']  = df['ema_trend']  # eski EMA_LONG  = 200

        # ── SMA ─────────────────────────────────────────────────
        df['sma_20'] = ta.sma(df['close'], length=20)
        df['sma_50'] = ta.sma(df['close'], length=50)

        # ── Volume ──────────────────────────────────────────────
        df['volume_ma']    = ta.sma(df['volume'], length=VOLUME_MA_PERIOD)
        df['volume_ratio'] = df['volume'] / df['volume_ma']

        # ── ATR — Dinamik SL/TP Hesabı ──────────────────────────
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

        # ── ADX — Trend Gücü Filtresi (Faz 5 YENİ) ─────────────
        # ADX > 25: Güçlü trend → işlem yap
        # ADX 20-25: Zayıf trend → dikkatli ol
        # ADX < 20: Sideways → bekle
        adx_result = ta.adx(df['high'], df['low'], df['close'], length=ADX_PERIOD)
        if adx_result is not None and not adx_result.empty:
            adx_cols = adx_result.columns.tolist()
            df['adx']    = adx_result[adx_cols[0]]  # ADX değeri
            df['adx_dmp'] = adx_result[adx_cols[1]] # +DI (Directional Movement +)
            df['adx_dmn'] = adx_result[adx_cols[2]] # -DI (Directional Movement -)
        else:
            df['adx'] = np.nan
            df['adx_dmp'] = np.nan
            df['adx_dmn'] = np.nan

        # ── StochRSI ─────────────────────────────────────────────
        stoch_rsi = ta.stochrsi(df['close'], length=14)
        if stoch_rsi is not None and not stoch_rsi.empty:
            df['stoch_rsi_k'] = stoch_rsi.iloc[:, 0]
            df['stoch_rsi_d'] = stoch_rsi.iloc[:, 1]
        else:
            df['stoch_rsi_k'] = np.nan
            df['stoch_rsi_d'] = np.nan

        logger.debug(f"📊 Teknik göstergeler hesaplandı ({len(df)} mum, "
                     f"son ADX={df['adx'].iloc[-1]:.1f} "
                     f"RSI={df['rsi'].iloc[-1]:.1f})")
        return df

    # ──────────────────────────────────────────────────────────────
    # Sinyal Fonksiyonları
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def get_rsi_signal(rsi_value):
        """RSI sinyali verir."""
        if rsi_value <= RSI_OVERSOLD:
            return 'oversold'
        elif rsi_value >= RSI_OVERBOUGHT:
            return 'overbought'
        return 'neutral'

    @staticmethod
    def get_macd_signal(df, index=-1):
        """MACD sinyali verir (crossover tespiti)."""
        if len(df) < 2:
            return 'neutral'
        current_hist = df['macd_histogram'].iloc[index]
        prev_hist    = df['macd_histogram'].iloc[index - 1]
        if pd.isna(current_hist) or pd.isna(prev_hist):
            return 'neutral'
        if prev_hist < 0 and current_hist > 0:
            return 'bullish_crossover'
        elif prev_hist > 0 and current_hist < 0:
            return 'bearish_crossover'
        elif current_hist > 0 and current_hist > prev_hist:
            return 'bullish_momentum'
        elif current_hist < 0 and current_hist < prev_hist:
            return 'bearish_momentum'
        return 'neutral'

    @staticmethod
    def get_bollinger_signal(df, index=-1):
        """Bollinger Band sinyali verir."""
        close    = df['close'].iloc[index]
        bb_lower = df['bb_lower'].iloc[index]
        bb_upper = df['bb_upper'].iloc[index]
        if pd.isna(bb_lower) or pd.isna(bb_upper):
            return 'neutral'
        if close <= bb_lower:
            return 'below_lower'
        elif close <= bb_lower * 1.02:
            return 'near_lower'
        elif close >= bb_upper:
            return 'above_upper'
        elif close >= bb_upper * 0.98:
            return 'near_upper'
        return 'neutral'

    @staticmethod
    def get_ema_alignment(df, index=-1):
        """
        EMA hizalanma durumunu verir.

        Returns:
          'full_bull'   : EMA9 > EMA21 > EMA50 → tam yukarı momentum
          'partial_bull': EMA9 > EMA21 (EMA50 altında) → zayıf yükseliş
          'full_bear'   : EMA9 < EMA21 < EMA50 → tam aşağı momentum
          'partial_bear': EMA9 < EMA21 → zayıf düşüş
          'neutral'     : karışık
        """
        ema_f = df['ema_fast'].iloc[index]
        ema_m = df['ema_mid'].iloc[index]
        ema_s = df['ema_slow'].iloc[index]
        if any(pd.isna(v) for v in [ema_f, ema_m, ema_s]):
            return 'neutral'
        if ema_f > ema_m > ema_s:
            return 'full_bull'
        elif ema_f > ema_m:
            return 'partial_bull'
        elif ema_f < ema_m < ema_s:
            return 'full_bear'
        elif ema_f < ema_m:
            return 'partial_bear'
        return 'neutral'

    @staticmethod
    def get_ema_signal(df, index=-1):
        """EMA Golden Cross / Death Cross sinyali (backwards compat)."""
        if len(df) < 2:
            return 'neutral'
        ema_short      = df['ema_short'].iloc[index]
        ema_long       = df['ema_long'].iloc[index]
        prev_ema_short = df['ema_short'].iloc[index - 1]
        prev_ema_long  = df['ema_long'].iloc[index - 1]
        if any(pd.isna(v) for v in [ema_short, ema_long, prev_ema_short, prev_ema_long]):
            return 'neutral'
        if prev_ema_short <= prev_ema_long and ema_short > ema_long:
            return 'golden_cross'
        elif prev_ema_short >= prev_ema_long and ema_short < ema_long:
            return 'death_cross'
        elif ema_short > ema_long:
            return 'uptrend'
        elif ema_short < ema_long:
            return 'downtrend'
        return 'neutral'

    @staticmethod
    def get_adx_signal(df, index=-1):
        """
        ADX trend gücü sinyali verir.

        Returns:
          'strong_bull' : ADX > 25 ve +DI > -DI → güçlü yükseliş trendi
          'strong_bear' : ADX > 25 ve -DI > +DI → güçlü düşüş trendi
          'weak_trend'  : ADX 20-25 arası → zayıf trend
          'sideways'    : ADX < 20 → yatay piyasa
        """
        adx = df['adx'].iloc[index]
        dmp = df['adx_dmp'].iloc[index]
        dmn = df['adx_dmn'].iloc[index]
        if pd.isna(adx):
            return 'neutral'
        if adx > 25:
            return 'strong_bull' if dmp > dmn else 'strong_bear'
        elif adx > 20:
            return 'weak_trend'
        return 'sideways'

    @staticmethod
    def get_volume_signal(df, index=-1):
        """Hacim sinyali verir."""
        volume_ratio = df['volume_ratio'].iloc[index]
        if pd.isna(volume_ratio):
            return 'neutral'
        if volume_ratio > 2.0:
            return 'very_high'
        elif volume_ratio > 1.5:
            return 'high'
        elif volume_ratio > 1.2:
            return 'above_normal'
        elif volume_ratio < 0.5:
            return 'very_low'
        elif volume_ratio < 0.7:
            return 'low'
        return 'normal'

    @staticmethod
    def get_summary(df, index=-1):
        """Tüm göstergelerin özetini verir."""
        if df.empty or len(df) < EMA_LONG:
            return None
        rsi_val = df['rsi'].iloc[index]
        close   = df['close'].iloc[index]
        if pd.isna(rsi_val) or pd.isna(close):
            return None
        return {
            'price':            close,
            'rsi':              rsi_val,
            'rsi_signal':       TechnicalIndicators.get_rsi_signal(rsi_val),
            'macd_signal':      TechnicalIndicators.get_macd_signal(df, index),
            'bollinger_signal': TechnicalIndicators.get_bollinger_signal(df, index),
            'ema_signal':       TechnicalIndicators.get_ema_signal(df, index),
            'ema_alignment':    TechnicalIndicators.get_ema_alignment(df, index),
            'adx_signal':       TechnicalIndicators.get_adx_signal(df, index),
            'volume_signal':    TechnicalIndicators.get_volume_signal(df, index),
            # Ham değerler
            'ema_fast':         df['ema_fast'].iloc[index],
            'ema_mid':          df['ema_mid'].iloc[index],
            'ema_slow':         df['ema_slow'].iloc[index],
            'ema_short':        df['ema_short'].iloc[index],
            'ema_long':         df['ema_long'].iloc[index],
            'adx':              df['adx'].iloc[index],
            'bb_lower':         df['bb_lower'].iloc[index],
            'bb_upper':         df['bb_upper'].iloc[index],
            'macd_histogram':   df['macd_histogram'].iloc[index],
            'atr':              df['atr'].iloc[index],
        }
