"""
Donchian Channel Breakout — Turtle Traders klasiği.

Tarih:
    1983'te Richard Dennis ve William Eckhardt 21 acemi trader'ı eğitti
    ("Turtles") ve sadece bu kuralları öğretti. Sonraki 5 yılda $175M kâr.

Sistem 1 (kısa vadeli):
    - 20-gün high kırılınca AL
    - 10-gün low kırılınca SAT
    - Stop-loss: ATR × 2 (giriş altında)

Sistem 2 (uzun vadeli):
    - 55-gün high kırılınca AL
    - 20-gün low kırılınca SAT
    - Stop-loss: ATR × 2

Realistic slippage dahil (coin tipine göre).
"""
import sys
import os
import argparse
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import pandas_ta as ta

from data.collector import DataCollector


COMMISSION = 0.001
LARGE_CAP = {'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'SOL/USDT'}
MID_CAP = {'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT'}


def get_slippage(symbol: str) -> float:
    """Coin tipine göre slippage."""
    if symbol in LARGE_CAP:
        return 0.002   # %0.2
    if symbol in MID_CAP:
        return 0.004   # %0.4
    return 0.007       # %0.7


def resample_daily(df_1h: pd.DataFrame) -> pd.DataFrame:
    """1h veriyi günlük OHLCV'ye dönüştürür."""
    return df_1h.resample('1D').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna()


def simulate_donchian(df: pd.DataFrame, symbol: str,
                       entry_period: int, exit_period: int,
                       atr_stop_mult: float = 2.0) -> dict:
    """
    Donchian breakout simülasyonu.

    df: günlük OHLC
    entry_period: kaç günlük high'ı kıracak (giriş)
    exit_period: kaç günlük low'ı kıracak (çıkış)
    atr_stop_mult: stop-loss ATR çarpanı
    """
    if df.empty or len(df) < entry_period + 50:
        return {'trades': []}

    df = df.copy()
    df['donchian_high'] = df['high'].rolling(entry_period).max().shift(1)
    df['donchian_low'] = df['low'].rolling(exit_period).min().shift(1)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    slip = get_slippage(symbol)
    trades = []
    pos = None  # {'entry', 'stop', 'amount_pct'}

    for i in range(entry_period + 20, len(df)):
        row = df.iloc[i]
        close = float(row['close'])
        high = float(row['high'])
        low = float(row['low'])
        atr = float(row['atr']) if not pd.isna(row['atr']) else 0
        d_high = float(row['donchian_high']) if not pd.isna(row['donchian_high']) else 0
        d_low = float(row['donchian_low']) if not pd.isna(row['donchian_low']) else 0

        # POZİSYON YÖNETİMİ
        if pos is not None:
            # Stop-loss kontrolü
            if low <= pos['stop']:
                exit_p = pos['stop'] * (1 - slip)  # market sell slippage
                pnl_pct = (exit_p - pos['entry']) / pos['entry'] * 100 - 2 * COMMISSION * 100
                trades.append({'pnl_pct': pnl_pct, 'reason': 'SL', 'days': i - pos['idx']})
                pos = None
                continue

            # Donchian low çıkışı
            if low <= d_low and d_low > 0:
                exit_p = d_low * (1 - slip)
                pnl_pct = (exit_p - pos['entry']) / pos['entry'] * 100 - 2 * COMMISSION * 100
                trades.append({'pnl_pct': pnl_pct, 'reason': 'donchian_exit', 'days': i - pos['idx']})
                pos = None
                continue

            # Trailing stop yukarı çek (yeni high'a göre)
            new_stop = close - atr * atr_stop_mult
            if new_stop > pos['stop']:
                pos['stop'] = new_stop

        # ENTRY
        if pos is None and high >= d_high and d_high > 0 and atr > 0:
            entry = d_high * (1 + slip)  # market buy slippage
            pos = {
                'entry': entry,
                'stop': entry - atr * atr_stop_mult,
                'idx': i,
            }

    # Son açık pozisyonu kapat
    if pos is not None:
        last_close = float(df.iloc[-1]['close']) * (1 - slip)
        pnl_pct = (last_close - pos['entry']) / pos['entry'] * 100 - 2 * COMMISSION * 100
        trades.append({'pnl_pct': pnl_pct, 'reason': 'eof', 'days': len(df) - pos['idx']})

    return {'trades': trades}


def aggregate(coin_data: dict, coins: list, entry_p: int, exit_p: int):
    all_trades = []
    for c in coins:
        if c not in coin_data:
            continue
        r = simulate_donchian(coin_data[c], c, entry_p, exit_p)
        all_trades.extend(r['trades'])
    if not all_trades:
        return None
    pnls = [t['pnl_pct'] for t in all_trades]
    days = [t['days'] for t in all_trades]
    wins = sum(1 for p in pnls if p > 0)
    return {
        'n': len(pnls),
        'avg': np.mean(pnls),
        'win_rate': wins / len(pnls) * 100,
        'best': max(pnls),
        'worst': min(pnls),
        'total': sum(pnls),
        'avg_days': np.mean(days),
        'sl_count': sum(1 for t in all_trades if t['reason'] == 'SL'),
        'donchian_exits': sum(1 for t in all_trades if t['reason'] == 'donchian_exit'),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    print('═' * 90)
    print('  🐢 DONCHIAN BREAKOUT — Turtle Traders Klasiği (Realistic Slippage)')
    print('  System 1: 20g high entry, 10g low exit | System 2: 55g high, 20g low exit')
    print('═' * 90)

    coins = [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT',
        'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT',
        'ATOM/USDT', 'NEAR/USDT', 'ARB/USDT', 'OP/USDT', 'APT/USDT',
        'INJ/USDT', 'SUI/USDT', 'TIA/USDT', 'FTM/USDT', 'ALGO/USDT',
    ]

    collector = DataCollector()
    print(f'\n📥 {len(coins)} coin verisi indiriliyor + günlük resample...')
    coin_data = {}
    for c in coins:
        df_1h = collector.fetch_historical_data(c, '1h', args.start, args.end)
        if not df_1h.empty:
            df_daily = resample_daily(df_1h)
            if len(df_daily) >= 80:  # min 80 gün veri
                coin_data[c] = df_daily
                print(f'  ✓ {c}: {len(df_daily)} gün')
        time.sleep(0.05)
    print(f'\n✅ {len(coin_data)} coin kullanılabilir\n')

    # Test sistemleri
    systems = [
        ('System 1 (20/10 — kısa)',  20, 10),
        ('System 2 (55/20 — uzun)',  55, 20),
        ('Hibrit (40/15)',           40, 15),
    ]

    print('  📊 SİSTEM KARŞILAŞTIRMASI (Realistic slippage)')
    print('  ' + '─' * 86)
    print(f'  {"SİSTEM":<26} {"İŞL":>5} {"WIN %":>7} {"ORT %":>8} {"BEST":>7} {"WORST":>7} {"SL/DON":>9} {"AVG GÜN":>8} {"TOPLAM %":>10}')
    print('  ' + '─' * 86)

    results = []
    for name, ep, exp in systems:
        r = aggregate(coin_data, coins, ep, exp)
        if not r:
            continue
        results.append((name, r))
        print(f'  {name:<26} {r["n"]:>5} {r["win_rate"]:>6.1f}% '
              f'{r["avg"]:>+7.2f}% {r["best"]:>+6.1f}% {r["worst"]:>+6.1f}% '
              f'{f"{r["sl_count"]}/{r["donchian_exits"]}":>9} {r["avg_days"]:>7.1f} {r["total"]:>+9.1f}%')

    # En iyi sistemi seç
    if results:
        best = max(results, key=lambda x: x[1]['total'])
        best_name, best_r = best
        print()
        print(f'  🏆 EN İYİ: {best_name} (toplam %{best_r["total"]:.1f}, ort %{best_r["avg"]:+.2f}/işlem)')

        # Compound
        print()
        print('  💰 COMPOUND ($1000 başlangıç, sermaye reinvest):')
        avg_per = 1 + best_r['avg'] / 100
        n = best_r['n']
        # Her işlem sermayenin %30'u (gerçekçi position sizing)
        position_pct = 0.30
        effective_avg = (1 - position_pct) + position_pct * avg_per
        final_full = 1000 * (avg_per ** n)
        final_sized = 1000 * (effective_avg ** n)
        years = (pd.to_datetime(args.end) - pd.to_datetime(args.start)).days / 365.25

        print(f'    Tam allocation: $1000 → ${final_full:,.0f} (matematik, gerçekçi değil)')
        print(f'    %30 position sizing: $1000 → ${final_sized:,.0f}')
        if final_sized > 1000:
            yearly = (final_sized / 1000) ** (1 / years) - 1
            print(f'    Yıllık eşdeğer: +%{yearly*100:.1f}')

    print()
    print('═' * 90)
    print('  💡 YORUM:')
    print('  • Donchian breakout: trend follow, boğa pazarında parlak')
    print('  • Whipsaw riski: sideways pazarda sürekli stop-out')
    print('  • Avg gün = ortalama pozisyon süresi (uzun → trend yakalama)')
    print('═' * 90)


if __name__ == '__main__':
    main()
