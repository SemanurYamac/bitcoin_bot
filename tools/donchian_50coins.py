"""
Donchian Optimize — 50 Coin Genişletilmiş Test

Mevcut 20 coin + 30 yeni coin = 50 coin
Optimum config: 1w, entry=6, exit=2, ATR=4.0 (önceki testte +%328 yıllık)

Soru: Daha fazla coin = daha fazla fırsat = daha fazla kâr mı?
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


def aggregate(coin_data, coins, **kwargs):
    all_trades = []
    per_coin = {}
    for c in coins:
        if c not in coin_data:
            continue
        ts = simulate(coin_data[c], c, **kwargs)
        if ts:
            per_coin[c] = ts
        all_trades.extend(ts)
    if not all_trades:
        return None
    return {
        'n': len(all_trades),
        'avg': np.mean(all_trades),
        'win_rate': sum(1 for p in all_trades if p > 0) / len(all_trades) * 100,
        'best': max(all_trades),
        'worst': min(all_trades),
        'total': sum(all_trades),
        'per_coin': per_coin,
    }


def compound_yearly(avg_pct, n_trades, years, position_pct=0.30):
    avg_per = 1 + avg_pct / 100
    effective = (1 - position_pct) + position_pct * avg_per
    final = effective ** n_trades
    if final <= 0:
        return -100
    return (final ** (1/years) - 1) * 100


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    # 50 coin listesi (mevcut 20 + 30 yeni)
    coins_50 = [
        # ── Mevcut 20 ──
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT',
        'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT',
        'ATOM/USDT', 'NEAR/USDT', 'ARB/USDT', 'OP/USDT', 'APT/USDT',
        'INJ/USDT', 'SUI/USDT', 'TIA/USDT', 'FTM/USDT', 'ALGO/USDT',
        # ── Yeni 30 ──
        # Layer 1
        'TRX/USDT', 'XLM/USDT', 'FIL/USDT', 'ICP/USDT', 'EOS/USDT',
        'KAS/USDT', 'SEI/USDT', 'TON/USDT',
        # DeFi
        'UNI/USDT', 'AAVE/USDT', 'COMP/USDT', 'CRV/USDT', 'MKR/USDT',
        'LDO/USDT', 'SNX/USDT', 'RUNE/USDT',
        # Memecoin / Gaming
        'DOGE/USDT', 'SHIB/USDT', 'PEPE/USDT', 'SAND/USDT', 'MANA/USDT',
        'AXS/USDT', 'GALA/USDT',
        # AI / Storage
        'AR/USDT', 'FET/USDT', 'RENDER/USDT',
        # Diğer
        'VET/USDT', 'KAVA/USDT', 'CELO/USDT', 'ZIL/USDT',
    ]

    print('═' * 90)
    print(f'  🐢 DONCHIAN — 50 Coin Genişletilmiş Test')
    print(f'  Config: Weekly TF, Entry=6, Exit=2, ATR=4.0 (önceki en iyi 20-coin: +%328 yıllık)')
    print('═' * 90)

    collector = DataCollector()
    print(f'\n📥 {len(coins_50)} coin verisi indiriliyor (1h base, sonra weekly resample)...')
    raw_data = {}
    failed = []
    for c in coins_50:
        try:
            df = collector.fetch_historical_data(c, '1h', args.start, args.end)
            if not df.empty and len(df) >= 1000:  # min ~6 hafta
                raw_data[c] = df
            else:
                failed.append(c)
        except Exception as e:
            failed.append(c)
        time.sleep(0.05)
    print(f'\n✅ {len(raw_data)}/{len(coins_50)} coin yüklendi')
    if failed:
        print(f'  ❌ Veri yok: {", ".join(failed[:8])}{"..." if len(failed) > 8 else ""}')

    # Weekly resample
    coin_data = {}
    for c, df in raw_data.items():
        weekly = resample(df, '1W')
        if len(weekly) >= 12:  # en az 12 hafta
            coin_data[c] = weekly

    print(f'  ✅ {len(coin_data)} coin haftalık veri uygun\n')

    years = (pd.to_datetime(args.end) - pd.to_datetime(args.start)).days / 365.25

    # ── KARŞILAŞTIRMA ──
    print('  📊 KARŞILAŞTIRMA: 20 coin vs 50 coin')
    print('  ' + '─' * 80)

    coins_20 = coins_50[:20]

    for label, coins_subset in [('20 coin (mevcut)', coins_20), ('50 coin (genişletilmiş)', list(coin_data.keys()))]:
        r = aggregate(coin_data, coins_subset, entry_p=6, exit_p=2, atr_stop_mult=4.0)
        if not r:
            continue
        yearly = compound_yearly(r['avg'], r['n'], years)
        print(f'  {label:<25} | İŞL: {r["n"]:>4} | WIN: {r["win_rate"]:>5.1f}% | '
              f'ORT: {r["avg"]:>+6.2f}% | TOPLAM: {r["total"]:>+8.1f}% | YIL: {yearly:>+7.1f}%')

    # ── Per-coin breakdown ──
    print()
    print('  📊 EN PARLAK COINLER (50 coin içinden, en iyi 15)')
    print('  ' + '─' * 70)
    print(f'  {"COIN":<14} {"İŞL":>4} {"WIN %":>7} {"ORT %":>7} {"TOPLAM %":>10}')
    print('  ' + '─' * 50)

    r_50 = aggregate(coin_data, list(coin_data.keys()), entry_p=6, exit_p=2, atr_stop_mult=4.0)
    if r_50:
        per_coin_stats = []
        for c, trades in r_50['per_coin'].items():
            if not trades:
                continue
            per_coin_stats.append({
                'coin': c,
                'n': len(trades),
                'avg': np.mean(trades),
                'win_rate': sum(1 for p in trades if p > 0) / len(trades) * 100,
                'total': sum(trades),
            })
        per_coin_stats.sort(key=lambda x: x['total'], reverse=True)
        for s in per_coin_stats[:15]:
            print(f'  {s["coin"]:<14} {s["n"]:>4} {s["win_rate"]:>6.1f}% {s["avg"]:>+6.2f}% {s["total"]:>+9.1f}%')

        print()
        print('  📊 EN KÖTÜ COINLER (en alttaki 5)')
        print('  ' + '─' * 50)
        for s in per_coin_stats[-5:]:
            print(f'  {s["coin"]:<14} {s["n"]:>4} {s["win_rate"]:>6.1f}% {s["avg"]:>+6.2f}% {s["total"]:>+9.1f}%')

    print()
    print('═' * 90)


if __name__ == '__main__':
    main()
