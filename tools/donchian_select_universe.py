"""
Adaptive Universe Selection — En sağlam 50 coin'i seç + Sürekli Optimize Sistemi.

Mantık (kurumsal hedge fund yaklaşımı):
    1. Top 100 hacimli USDT pair tara
    2. Donchian Weekly stratejisinde her birinin son 4 yıl performansını ölç
    3. Filtreler:
       - Min 5 trade (yeterli istatistik)
       - Pozitif ortalama P&L
       - Win rate >= %35
       - Min 1 yıl tarihçe (yeni hype coinleri hariç)
    4. Filtre geçenleri toplam P&L'a göre rankla
    5. En iyi 50'yi seç → data/donchian_universe.json'a kaydet

Periyodik rebuild:
    Bu script'i her 3 ayda bir çalıştır → universe güncellenir
    Bot bu listeyi okur, yeni iyi performansları yakalar, kötüleri bırakır
"""
import sys
import os
import argparse
import json
import logging
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import pandas as pd
import numpy as np
import pandas_ta as ta

from data.collector import DataCollector


COMMISSION = 0.001
LARGE_CAP = {'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'SOL/USDT'}
MID_CAP = {'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT'}

UNIVERSE_PATH = Path(__file__).parent.parent / 'data' / 'donchian_universe.json'


def get_slippage(symbol):
    if symbol in LARGE_CAP: return 0.002
    if symbol in MID_CAP: return 0.004
    return 0.007


def resample(df_1h, freq='1W'):
    return df_1h.resample(freq).agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()


def simulate(df, symbol, entry_p=6, exit_p=2, atr_stop_mult=4.0):
    if df.empty or len(df) < entry_p + 20:
        return []
    df = df.copy()
    df['donchian_high'] = df['high'].rolling(entry_p).max().shift(1)
    df['donchian_low'] = df['low'].rolling(exit_p).min().shift(1)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    slip = get_slippage(symbol)
    trades = []
    pos = None

    for i in range(entry_p + 15, len(df)):
        row = df.iloc[i]
        close = float(row['close'])
        high = float(row['high'])
        low = float(row['low'])
        atr = float(row['atr']) if not pd.isna(row['atr']) else 0
        d_high = float(row['donchian_high']) if not pd.isna(row['donchian_high']) else 0
        d_low = float(row['donchian_low']) if not pd.isna(row['donchian_low']) else 0

        if pos is not None:
            if low <= pos['stop']:
                exit_p_val = pos['stop'] * (1 - slip)
                pnl = (exit_p_val - pos['entry']) / pos['entry'] * 100 - 0.2
                trades.append(pnl)
                pos = None
                continue
            if low <= d_low and d_low > 0:
                exit_p_val = d_low * (1 - slip)
                pnl = (exit_p_val - pos['entry']) / pos['entry'] * 100 - 0.2
                trades.append(pnl)
                pos = None
                continue
            new_stop = close - atr * atr_stop_mult
            if new_stop > pos['stop']:
                pos['stop'] = new_stop

        if pos is None and high >= d_high and d_high > 0 and atr > 0:
            entry = d_high * (1 + slip)
            pos = {'entry': entry, 'stop': entry - atr * atr_stop_mult}

    if pos is not None:
        last_close = float(df.iloc[-1]['close']) * (1 - slip)
        pnl = (last_close - pos['entry']) / pos['entry'] * 100 - 0.2
        trades.append(pnl)

    return trades


def get_top_volume_pairs(top_n=120):
    """Binance'den top N hacimli USDT pair'i çek."""
    exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
    tickers = exchange.fetch_tickers()
    skip = {'USDC/USDT', 'BUSD/USDT', 'TUSD/USDT', 'FDUSD/USDT', 'DAI/USDT',
            'USDP/USDT', 'EUR/USDT', 'TRY/USDT', 'BRL/USDT', 'GBP/USDT', 'AUD/USDT', 'JPY/USDT'}
    usdt = [(s, t) for s, t in tickers.items()
             if s.endswith('/USDT') and s not in skip
             and t.get('quoteVolume') and t['quoteVolume'] > 0]
    usdt.sort(key=lambda x: x[1]['quoteVolume'], reverse=True)
    return [s for s, _ in usdt[:top_n]]


def passes_filter(stats: dict, min_trades=5, min_avg=0.5, min_win_rate=35) -> bool:
    """Bir coin'in filtreyi geçip geçmediğini kontrol eder."""
    return (
        stats['n'] >= min_trades and
        stats['avg'] >= min_avg and
        stats['win_rate'] >= min_win_rate
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    parser.add_argument('--top-volume', type=int, default=120, help='Hacim top N tara')
    parser.add_argument('--select', type=int, default=50, help='En iyi N coin seç')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    print('═' * 90)
    print(f'  🎯 ADAPTIVE UNIVERSE SELECTION — En Sağlam {args.select} Coin\'i Seç')
    print(f'  Tarama: Top {args.top_volume} hacimli USDT pair')
    print(f'  Strateji: Donchian Weekly 6/2, ATR=4.0')
    print(f'  Filtreler: min 5 işlem | ortalama %0.5+ | win rate %35+')
    print('═' * 90)

    print('\n🔍 Top hacimli pair listesi alınıyor...')
    candidates = get_top_volume_pairs(args.top_volume)
    print(f'  ✅ {len(candidates)} aday coin')

    collector = DataCollector()
    print(f'\n📥 {len(candidates)} coin verisi indiriliyor...')
    raw_data = {}
    for i, c in enumerate(candidates):
        try:
            df = collector.fetch_historical_data(c, '1h', args.start, args.end)
            if not df.empty and len(df) >= 8760:  # min 1 yıl 1h veri
                raw_data[c] = df
        except Exception:
            pass
        if (i + 1) % 30 == 0:
            print(f'  {i + 1}/{len(candidates)} indirildi, {len(raw_data)} kullanılabilir')
        time.sleep(0.05)

    print(f'\n✅ {len(raw_data)} coin yeterli geçmişe sahip (min 1 yıl)\n')

    # Weekly resample + Donchian backtest
    print(f'🔬 Backtest çalışıyor...')
    coin_stats = []
    for c, df_1h in raw_data.items():
        weekly = resample(df_1h, '1W')
        if len(weekly) < 12:
            continue
        trades = simulate(weekly, c, entry_p=6, exit_p=2, atr_stop_mult=4.0)
        if not trades:
            continue
        coin_stats.append({
            'coin': c,
            'n': len(trades),
            'avg': float(np.mean(trades)),
            'win_rate': sum(1 for p in trades if p > 0) / len(trades) * 100,
            'best': float(max(trades)),
            'worst': float(min(trades)),
            'total': float(sum(trades)),
        })

    print(f'  ✅ {len(coin_stats)} coin\'de backtest tamam')

    # Filtre uygula
    print(f'\n🔬 Filtre uygulanıyor...')
    passed = [s for s in coin_stats if passes_filter(s)]
    failed = [s for s in coin_stats if not passes_filter(s)]
    print(f'  ✅ Filtre geçen: {len(passed)} coin')
    print(f'  ❌ Filtre eleyen: {len(failed)} coin')

    # En iyi N seç (toplam P&L'a göre sırala)
    passed.sort(key=lambda x: x['total'], reverse=True)
    selected = passed[:args.select]

    print(f'\n📊 SEÇİLEN {len(selected)} COIN (toplam P&L sıralı)')
    print('  ' + '─' * 70)
    print(f'  {"COIN":<14} {"İŞL":>4} {"WIN %":>7} {"ORT %":>7} {"BEST":>7} {"WORST":>7} {"TOPLAM":>9}')
    print('  ' + '─' * 65)
    for s in selected:
        print(f'  {s["coin"]:<14} {s["n"]:>4} {s["win_rate"]:>6.1f}% '
              f'{s["avg"]:>+6.2f}% {s["best"]:>+6.1f}% {s["worst"]:>+6.1f}% {s["total"]:>+8.1f}%')

    # JSON'a kaydet
    UNIVERSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    universe_data = {
        'created_at': datetime.utcnow().isoformat(timespec='seconds'),
        'config': {
            'strategy': 'Donchian Weekly 6/2 ATR=4.0',
            'backtest_start': args.start,
            'backtest_end': args.end,
            'filter': {'min_trades': 5, 'min_avg_pct': 0.5, 'min_win_rate': 35},
        },
        'selected_count': len(selected),
        'coins': [s['coin'] for s in selected],
        'detailed_stats': selected,
    }
    with open(UNIVERSE_PATH, 'w') as f:
        json.dump(universe_data, f, indent=2)
    print(f'\n💾 Kaydedildi: {UNIVERSE_PATH}')

    # Toplam beklenen performans
    if selected:
        total_n = sum(s['n'] for s in selected)
        total_pnl = sum(s['total'] for s in selected)
        avg_avg = np.mean([s['avg'] for s in selected])
        avg_wr = np.mean([s['win_rate'] for s in selected])
        years = (pd.to_datetime(args.end) - pd.to_datetime(args.start)).days / 365.25

        # Realistic compound (position %10)
        avg_per = 1 + avg_avg / 100
        effective = 0.9 + 0.1 * avg_per
        final = effective ** total_n
        yearly = (final ** (1/years) - 1) * 100 if final > 0 else -100

        print(f'\n📈 SEÇİLEN PORTFÖY ÖZETİ:')
        print(f'  Toplam işlem (4 yıl): {total_n}')
        print(f'  Ortalama win rate: %{avg_wr:.1f}')
        print(f'  Ortalama P&L/işlem: +%{avg_avg:.2f}')
        print(f'  Toplam P&L (lineer): +%{total_pnl:.0f}')
        print(f'  Yıllık eşdeğer (pos %10): +%{yearly:.1f}')

    print()
    print('═' * 90)
    print('  💡 SONRAKI ADIM:')
    print('  1. Donchian bot bu data/donchian_universe.json\'ı okur')
    print('  2. Periyodik rebuild: bu script\'i 3 ayda bir çalıştır → universe güncellenir')
    print('  3. Bot performansa göre adaptive davranır')
    print('═' * 90)


if __name__ == '__main__':
    main()
