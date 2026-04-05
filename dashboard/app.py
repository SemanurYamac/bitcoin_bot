"""
Bitcoin Trading Bot - Streamlit Dashboard
Canlı grafikler, sinyal izleme ve portföy yönetimi arayüzü.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from data.collector import DataCollector
from data.storage import DataStorage
from analysis.indicators import TechnicalIndicators
from strategy.signals import SignalGenerator
from config.settings import SYMBOL, SYMBOLS, MULTI_COIN_MODE, TIMEFRAME


# ─── Sayfa Ayarları ──────────────────────────────────────────────
st.set_page_config(
    page_title="₿ Bitcoin Trading Bot",
    page_icon="🪙",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── CSS Stili ───────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #2d3748;
        margin: 5px 0;
    }
    .buy-signal { color: #00e676; font-weight: bold; font-size: 1.2em; }
    .sell-signal { color: #ff1744; font-weight: bold; font-size: 1.2em; }
    .hold-signal { color: #90a4ae; font-weight: bold; font-size: 1.2em; }
    .stMetric > div { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                       padding: 15px; border-radius: 10px; border: 1px solid #2d3748; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_collector():
    return DataCollector()


@st.cache_resource
def get_storage():
    return DataStorage()


def create_candlestick_chart(df, symbol=SYMBOL, signals_df=None):
    """İnteraktif mum grafiği oluşturur."""
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=(f'{symbol} Fiyat', 'RSI', 'MACD')
    )

    # ─── Mum Grafiği ──────────────────────────────────────
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df['open'], high=df['high'],
            low=df['low'], close=df['close'],
            name=symbol,
            increasing_line_color='#00e676',
            decreasing_line_color='#ff1744'
        ), row=1, col=1
    )

    # Bollinger Bands
    if 'bb_upper' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['bb_upper'], name='BB Üst',
            line=dict(color='rgba(33,150,243,0.3)', width=1),
            showlegend=False
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['bb_lower'], name='BB Alt',
            line=dict(color='rgba(33,150,243,0.3)', width=1),
            fill='tonexty', fillcolor='rgba(33,150,243,0.05)',
            showlegend=False
        ), row=1, col=1)

    # EMA çizgileri
    if 'ema_short' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['ema_short'], name='EMA 50',
            line=dict(color='#ffd54f', width=1.5)
        ), row=1, col=1)
    if 'ema_long' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['ema_long'], name='EMA 200',
            line=dict(color='#e040fb', width=1.5)
        ), row=1, col=1)

    # AL/SAT sinyalleri
    if signals_df is not None and not signals_df.empty:
        buy_signals = signals_df[signals_df['signal'] == 'BUY']
        sell_signals = signals_df[signals_df['signal'] == 'SELL']

        if not buy_signals.empty:
            fig.add_trace(go.Scatter(
                x=buy_signals['timestamp'], y=buy_signals['price'],
                mode='markers', name='AL',
                marker=dict(symbol='triangle-up', size=12, color='#00e676',
                           line=dict(width=2, color='white'))
            ), row=1, col=1)

        if not sell_signals.empty:
            fig.add_trace(go.Scatter(
                x=sell_signals['timestamp'], y=sell_signals['price'],
                mode='markers', name='SAT',
                marker=dict(symbol='triangle-down', size=12, color='#ff1744',
                           line=dict(width=2, color='white'))
            ), row=1, col=1)

    # ─── RSI ──────────────────────────────────────────────
    if 'rsi' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['rsi'], name='RSI',
            line=dict(color='#7c4dff', width=2)
        ), row=2, col=1)

        fig.add_hline(y=70, line=dict(color='#ff1744', dash='dash', width=1), row=2, col=1)
        fig.add_hline(y=30, line=dict(color='#00e676', dash='dash', width=1), row=2, col=1)
        fig.add_hrect(y0=30, y1=70, fillcolor='rgba(124,77,255,0.05)',
                     line_width=0, row=2, col=1)

    # ─── MACD ─────────────────────────────────────────────
    if 'macd' in df.columns:
        colors = ['#00e676' if v > 0 else '#ff1744' for v in df['macd_histogram'].fillna(0)]
        fig.add_trace(go.Bar(
            x=df.index, y=df['macd_histogram'], name='MACD Histogram',
            marker_color=colors, opacity=0.6
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['macd'], name='MACD',
            line=dict(color='#2196f3', width=1.5)
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['macd_signal'], name='Sinyal',
            line=dict(color='#ff9800', width=1.5)
        ), row=3, col=1)

    # ─── Grafik Düzeni ────────────────────────────────────
    fig.update_layout(
        template='plotly_dark',
        height=800,
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=1.02),
        xaxis_rangeslider_visible=False,
        margin=dict(l=50, r=50, t=30, b=30),
        paper_bgcolor='#0e1117',
        plot_bgcolor='#0e1117',
    )

    return fig


def main():
    """Dashboard ana fonksiyonu."""

    # ─── Sidebar ──────────────────────────────────────────
    with st.sidebar:
        st.markdown("## 🪙 Bitcoin Bot")
        st.markdown("---")

        # Coin seçimi
        available_coins = SYMBOLS if MULTI_COIN_MODE else [SYMBOL]
        selected_symbol = st.selectbox(
            "🪙 İşlem Çifti (Coin)",
            available_coins
        )

        st.markdown("---")

        # Veri kaynağı seçimi
        data_source = st.selectbox(
            "📊 Veri Kaynağı",
            ["Canlı Veri (Binance)", "Veritabanı"]
        )

        # Zaman aralığı
        timeframe = st.selectbox(
            "⏰ Zaman Dilimi",
            ["1h", "4h", "1d"],
            index=0
        )

        # Mum sayısı
        candle_count = st.slider("📏 Mum Sayısı", 50, 500, 200)

        st.markdown("---")
        st.markdown("### ⚙️ Strateji Parametreleri")

        # Strateji ayarları
        rsi_oversold = st.slider("RSI Aşırı Satım", 20, 40, 35)
        rsi_overbought = st.slider("RSI Aşırı Alım", 60, 80, 65)

        st.markdown("---")
        refresh = st.button("🔄 Yenile", use_container_width=True)

    # ─── Ana İçerik ───────────────────────────────────────
    st.markdown("# 🪙 Bitcoin Trading Bot Dashboard")

    try:
        collector = get_collector()

        # Veri çek
        with st.spinner("📥 Veri çekiliyor..."):
            if data_source == "Canlı Veri (Binance)":
                df = collector.fetch_ohlcv(symbol=selected_symbol, timeframe=timeframe, limit=candle_count)
            else:
                storage = get_storage()
                df = storage.load_ohlcv(symbol=selected_symbol, timeframe=timeframe)
                if not df.empty:
                    df = df.tail(candle_count)

        if df.empty:
            st.error("❌ Veri bulunamadı! Önce backtesting yaparak veri indirin.")
            return

        # Göstergeleri hesapla
        df = TechnicalIndicators.calculate_all(df)

        # Anlık sinyal
        signal_gen = SignalGenerator()
        current_signal = signal_gen.generate_signal(df)

        # ─── Üst Metrik Kartlar ──────────────────────────
        col1, col2, col3, col4, col5 = st.columns(5)

        current_price = df['close'].iloc[-1]
        prev_price = df['close'].iloc[-2]
        change = ((current_price - prev_price) / prev_price) * 100

        with col1:
            st.metric(f"💰 {selected_symbol.split('/')[0]} Fiyatı", f"${current_price:,.2f}",
                      f"{change:+.2f}%")

        with col2:
            rsi_val = df['rsi'].iloc[-1]
            st.metric("📊 RSI", f"{rsi_val:.1f}",
                      "Aşırı Satım" if rsi_val < 35 else ("Aşırı Alım" if rsi_val > 65 else "Normal"))

        with col3:
            signal_text = current_signal['signal']
            signal_color = '🟢' if signal_text == 'BUY' else ('🔴' if signal_text == 'SELL' else '⚪')
            st.metric(f"{signal_color} Sinyal", signal_text,
                      f"Skor: {current_signal['score']}")

        with col4:
            vol_ratio = df['volume_ratio'].iloc[-1] if 'volume_ratio' in df.columns else 0
            st.metric("📦 Hacim Oranı", f"{vol_ratio:.2f}x",
                      "Yüksek" if vol_ratio > 1.3 else "Normal")

        with col5:
            atr = df['atr'].iloc[-1] if 'atr' in df.columns else 0
            st.metric("📈 ATR", f"${atr:,.2f}", "Volatilite")

        st.markdown("---")

        # ─── Grafik ──────────────────────────────────────
        fig = create_candlestick_chart(df, symbol=selected_symbol)
        st.plotly_chart(fig, use_container_width=True)

        # ─── Sinyal Detayları ────────────────────────────
        st.markdown("---")
        st.markdown("### 📋 Anlık Sinyal Detayları")

        col_l, col_r = st.columns([1, 1])

        with col_l:
            st.markdown("#### 📊 Gösterge Değerleri")

            summary = TechnicalIndicators.get_summary(df)
            if summary:
                indicator_data = {
                    'Gösterge': ['RSI', 'MACD', 'Bollinger', 'EMA Trend', 'Hacim'],
                    'Sinyal': [
                        summary['rsi_signal'],
                        summary['macd_signal'],
                        summary['bollinger_signal'],
                        summary['ema_signal'],
                        summary['volume_signal'],
                    ],
                    'Değer': [
                        f"{summary['rsi']:.1f}",
                        f"{summary['macd_histogram']:.4f}" if summary['macd_histogram'] else 'N/A',
                        f"${summary['bb_lower']:,.0f} - ${summary['bb_upper']:,.0f}",
                        f"EMA50: ${summary['ema_short']:,.0f} | EMA200: ${summary['ema_long']:,.0f}" if summary['ema_long'] else 'N/A',
                        f"{vol_ratio:.2f}x",
                    ]
                }
                st.dataframe(pd.DataFrame(indicator_data), use_container_width=True, hide_index=True)

        with col_r:
            st.markdown("#### 📝 Sinyal Nedenleri")
            for reason in current_signal['reasons']:
                st.markdown(f"- {reason}")

        # ─── Son İşlemler ────────────────────────────────
        st.markdown("---")
        st.markdown("### 📜 Son İşlemler (Tüm Coinler)")

        storage = get_storage()
        # Veritabanından tüm trades çekilir (coin'e özel filtreleme yapılmaz, tüm tablo gösterilir)
        trades = storage.get_trades(limit=20)

        if not trades.empty:
            st.dataframe(trades[['timestamp', 'symbol', 'side', 'price', 'amount', 'profit_loss', 'mode']],
                        use_container_width=True, hide_index=True)
        else:
            st.info("Henüz işlem kaydı bulunmuyor. Backtesting veya paper trading çalıştırın.")

    except Exception as e:
        st.error(f"❌ Hata: {e}")
        st.exception(e)


if __name__ == '__main__':
    main()
