"""
Hızlı Test (Eleme Turu)
Sadece BTC, ETH, SOL için 1 yıllık test yapar.
Mean Reversion (Dipten Alma) gibi yeni stratejilerin
hızlıca test edilmesi içindir.
"""
import sys
import os
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.collector import DataCollector
from analysis.indicators import TechnicalIndicators
from backtest.engine import BacktestEngine
import config.settings as settings

logging.basicConfig(level=logging.WARNING, format='%(asctime)s | %(message)s')

COINS = settings.SYMBOLS
START = '2026-01-01'
END = '2026-05-06'
TIMEFRAME = '15m'

# Risk ve Kaldıraç Ayarları (Kullanıcı İsteği: %10 Risk - Scalping için çok agresif)
settings.RISK_PER_TRADE = 0.05
import backtest.engine as engine_mod
engine_mod.RISK_PER_TRADE = settings.RISK_PER_TRADE
engine_mod.ATR_TP2_MULT = 5.0
engine_mod.MAX_POSITION_PERCENT = 0.99  # Max spot limit (%99 kullanarak komisyona yer bırak)

# 🚀 SCALPING AYARLARI (15 Dakikalık Grafik)
settings.ATR_SL_MULT = 1.0   # Çok Dar Stop Loss (Hızlı kaçış)
settings.ATR_TP1_MULT = 1.5  # Hızlı kâr al
settings.ATR_TP2_MULT = 5.0  # Ana hedef
settings.TRAILING_ACTIVATION = 0.015 # %1.5 kâra geçince trailing stop devreye girer
engine_mod.TRAILING_ACTIVATION = settings.TRAILING_ACTIVATION

def main():
    print("=" * 60)
    print("🚀 BÜYÜK TEST: XGBoost AI STRATEJİSİ")
    print(f"Dönem: {START} → {END} (Son 4 Ay - Pasif Gelir Testi)")
    print(f"Coinler: {COINS}")
    print("=" * 60)

    collector = DataCollector()
    total_ret = 0
    
    for symbol in COINS:
        print(f"\n[{symbol}] Test ediliyor...")
        df = collector.fetch_historical_data(symbol, TIMEFRAME, START, END)
        if df.empty:
            continue
            
        df = TechnicalIndicators.calculate_all(df)
        engine = BacktestEngine(initial_balance=1000)
        
        # Verbose true yaparak sadece Mean Reversion alımlarını görelim
        result = engine.run(df, verbose=False)
        
        ret = result['total_return_percent']
        total_ret += ret
        
        print(f"  Getiri: {ret:+.2f}% | İşlem: {result['total_trades']} | Win: {result.get('win_rate', 0):.1f}%")
        
    print("\n" + "=" * 60)
    print(f"📊 ORTALAMA GETİRİ: {total_ret/len(COINS):+.2f}% (Sadece 1 Yılda)")
    print("=" * 60)

if __name__ == '__main__':
    main()
