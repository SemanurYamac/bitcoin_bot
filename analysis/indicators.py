"""
Bitcoin Trading Bot - Teknik Göstergeler Modülü
RSI, MACD, Bollinger, EMA ve diğer teknik analiz göstergelerini hesaplar.
"""
import pandas as pd
import pandas_ta as ta
import numpy as np
import logging
from config.settings import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BOLLINGER_PERIOD, BOLLINGER_STD,
    EMA_SHORT, EMA_LONG, VOLUME_MA_PERIOD
)

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """Teknik analiz göstergelerini hesaplar ve DataFrame'e ekler."""

    @staticmethod
    def calculate_all(df):
        """
        Tüm teknik göstergeleri hesaplar ve DataFrame'e ekler.

        Args:
            df: pandas DataFrame (open, high, low, close, volume sütunları)

        Returns:
            pandas DataFrame: Göstergeler eklenmiş DataFrame
        """
        df = df.copy()

        # RSI - Relative Strength Index
        df['rsi'] = ta.rsi(df['close'], length=RSI_PERIOD)

        # MACD - Moving Average Convergence Divergence
        macd_result = ta.macd(df['close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
        # pandas-ta sütun isimleri: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
        macd_cols = macd_result.columns.tolist()
        df['macd'] = macd_result[macd_cols[0]]           # MACD line
        df['macd_histogram'] = macd_result[macd_cols[1]]  # Histogram
        df['macd_signal'] = macd_result[macd_cols[2]]     # Signal line

        # Bollinger Bands
        bbands = ta.bbands(df['close'], length=BOLLINGER_PERIOD, std=BOLLINGER_STD)
        df['bb_lower'] = bbands.iloc[:, 0]   # Alt bant
        df['bb_middle'] = bbands.iloc[:, 1]  # Orta bant (SMA)
        df['bb_upper'] = bbands.iloc[:, 2]   # Üst bant
        df['bb_bandwidth'] = bbands.iloc[:, 3] if bbands.shape[1] > 3 else None
        df['bb_percent'] = bbands.iloc[:, 4] if bbands.shape[1] > 4 else None

        # EMA - Exponential Moving Average
        df['ema_short'] = ta.ema(df['close'], length=EMA_SHORT)
        df['ema_long'] = ta.ema(df['close'], length=EMA_LONG)

        # SMA - Simple Moving Average
        df['sma_20'] = ta.sma(df['close'], length=20)
        df['sma_50'] = ta.sma(df['close'], length=50)

        # Volume Moving Average
        df['volume_ma'] = ta.sma(df['volume'], length=VOLUME_MA_PERIOD)
        df['volume_ratio'] = df['volume'] / df['volume_ma']

        # ATR - Average True Range (volatilite ölçümü)
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

        # Stochastic RSI
        stoch_rsi = ta.stochrsi(df['close'], length=14)
        if stoch_rsi is not None and not stoch_rsi.empty:
            df['stoch_rsi_k'] = stoch_rsi.iloc[:, 0]
            df['stoch_rsi_d'] = stoch_rsi.iloc[:, 1]

        logger.info(f"📊 Teknik göstergeler hesaplandı ({len(df)} mum)")
        return df

    @staticmethod
    def get_rsi_signal(rsi_value):
        """RSI sinyali verir."""
        if rsi_value <= RSI_OVERSOLD:
            return 'oversold'   # Aşırı satım → AL sinyali
        elif rsi_value >= RSI_OVERBOUGHT:
            return 'overbought'  # Aşırı alım → SAT sinyali
        return 'neutral'

    @staticmethod
    def get_macd_signal(df, index=-1):
        """MACD sinyali verir (crossover tespiti)."""
        if len(df) < 2:
            return 'neutral'

        current_hist = df['macd_histogram'].iloc[index]
        prev_hist = df['macd_histogram'].iloc[index - 1]

        if pd.isna(current_hist) or pd.isna(prev_hist):
            return 'neutral'

        # Histogram negatiften pozitife → AL sinyali (bullish crossover)
        if prev_hist < 0 and current_hist > 0:
            return 'bullish_crossover'
        # Histogram pozitiften negatife → SAT sinyali (bearish crossover)
        elif prev_hist > 0 and current_hist < 0:
            return 'bearish_crossover'
        # Histogram pozitif ve artıyor → devam eden yükseliş
        elif current_hist > 0 and current_hist > prev_hist:
            return 'bullish_momentum'
        # Histogram negatif ve düşüyor → devam eden düşüş
        elif current_hist < 0 and current_hist < prev_hist:
            return 'bearish_momentum'

        return 'neutral'

    @staticmethod
    def get_bollinger_signal(df, index=-1):
        """Bollinger Band sinyali verir."""
        close = df['close'].iloc[index]
        bb_lower = df['bb_lower'].iloc[index]
        bb_upper = df['bb_upper'].iloc[index]
        bb_middle = df['bb_middle'].iloc[index]

        if pd.isna(bb_lower) or pd.isna(bb_upper):
            return 'neutral'

        # Fiyat alt banda temas/geçti → AL sinyali
        if close <= bb_lower:
            return 'below_lower'
        # Fiyat alt bandın yakınında (%2 mesafe)
        elif close <= bb_lower * 1.02:
            return 'near_lower'
        # Fiyat üst banda temas/geçti → SAT sinyali
        elif close >= bb_upper:
            return 'above_upper'
        # Fiyat üst bandın yakınında (%2 mesafe)
        elif close >= bb_upper * 0.98:
            return 'near_upper'

        return 'neutral'

    @staticmethod
    def get_ema_signal(df, index=-1):
        """EMA Golden Cross / Death Cross sinyali verir."""
        if len(df) < 2:
            return 'neutral'

        ema_short = df['ema_short'].iloc[index]
        ema_long = df['ema_long'].iloc[index]
        prev_ema_short = df['ema_short'].iloc[index - 1]
        prev_ema_long = df['ema_long'].iloc[index - 1]

        if any(pd.isna(v) for v in [ema_short, ema_long, prev_ema_short, prev_ema_long]):
            return 'neutral'

        # Golden Cross: EMA50 EMA200'ü yukarı kesiyor → güçlü AL
        if prev_ema_short <= prev_ema_long and ema_short > ema_long:
            return 'golden_cross'
        # Death Cross: EMA50 EMA200'ü aşağı kesiyor → güçlü SAT
        elif prev_ema_short >= prev_ema_long and ema_short < ema_long:
            return 'death_cross'
        # EMA50 > EMA200 → yükselen trend
        elif ema_short > ema_long:
            return 'uptrend'
        # EMA50 < EMA200 → düşen trend
        elif ema_short < ema_long:
            return 'downtrend'

        return 'neutral'

    @staticmethod
    def get_volume_signal(df, index=-1):
        """Hacim sinyali verir."""
        volume_ratio = df['volume_ratio'].iloc[index]

        if pd.isna(volume_ratio):
            return 'neutral'

        if volume_ratio > 2.0:
            return 'very_high'   # Çok yüksek hacim
        elif volume_ratio > 1.3:
            return 'high'        # Ortalama üstü hacim
        elif volume_ratio < 0.5:
            return 'very_low'    # Çok düşük hacim
        elif volume_ratio < 0.7:
            return 'low'         # Ortalama altı hacim

        return 'normal'

    @staticmethod
    def get_summary(df, index=-1):
        """Tüm göstergelerin özetini verir."""
        if df.empty or len(df) < EMA_LONG:
            return None

        rsi_val = df['rsi'].iloc[index]
        close = df['close'].iloc[index]

        # NaN kontrolü — göstergeler hesaplanamadıysa None dön
        if pd.isna(rsi_val) or pd.isna(close):
            return None

        return {
            'price': close,
            'rsi': rsi_val,
            'rsi_signal': TechnicalIndicators.get_rsi_signal(rsi_val),
            'macd_signal': TechnicalIndicators.get_macd_signal(df, index),
            'bollinger_signal': TechnicalIndicators.get_bollinger_signal(df, index),
            'ema_signal': TechnicalIndicators.get_ema_signal(df, index),
            'volume_signal': TechnicalIndicators.get_volume_signal(df, index),
            'ema_short': df['ema_short'].iloc[index],
            'ema_long': df['ema_long'].iloc[index],
            'bb_lower': df['bb_lower'].iloc[index],
            'bb_upper': df['bb_upper'].iloc[index],
            'macd_histogram': df['macd_histogram'].iloc[index],
            'atr': df['atr'].iloc[index],
        }
