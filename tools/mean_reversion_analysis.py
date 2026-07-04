"""
Mean Reversion Bot — RSI Oversold Bounce (Dipten Alım Stratejisi)

Mantık (Donchian'ın TAM TERSİ):
    Donchian: "Yeni high'a ulaştı, trende katıl"
    Mean Reversion: "Aşırı düştü, dipten geri dönecek"

Sinyaller:
    Giriş: RSI < threshold + (opsiyonel) Bollinger alt band kırılması
    Çıkış: RSI > threshold (mean'e dönüş) + ATR stop loss

Test edilecek 4 varyasyon:
    V1: RSI<25 entry, RSI>70 exit (klasik)
    V2: RSI<20 entry, RSI>65 exit (sıkı)
    V3: RSI<25 + BB alt band entry, BB middle exit (BB-based)
    V4: RSI<30 entry, ATR×2 TP / ATR×1.5 SL (ATR-based)

Realistic slippage dahil.
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
    if symbol in LARGE_CAP: return 0.002
    if symbol in MID_CAP: return 0.004
    return 0.007


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['rsi'] = ta.rsi(df['close'], length=14)
    bb = ta.bbands(df['close'], length=20, std=2)
    df['bb_lower'] = bb.iloc[:, 0]
    df['bb_middle'] = bb.iloc[:, 1]
    df['bb_upper'] = bb.iloc[:, 2]
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    return df


def simulate(df: pd.DataFrame, symbol: str, variation: str,
             rsi_entry: float = 25, rsi_exit: float = 70,
             use_bb_lower: bool = False, use_bb_middle: bool = False,
             atr_tp_mult: float = 2.0, atr_sl_mult: float = 1.5,
             max_hold_hours: int = 168) -> dict:
    """
    Mean reversion simülasyonu.
    """
    if df.empty or len(df) < 50:
        return {'trades': []}

    df = add_indicators(df)
    slip = get_slippage(symbol)
    trades = []
    pos = None

    for i in range(50, len(df)):
        row = df.iloc[i]
        close = float(row['close'])
        high = float(row['high'])
        low = float(row['low'])
        rsi = float(row['rsi']) if not pd.isna(row['rsi']) else 50
        bb_lower = float(row['bb_lower']) if not pd.isna(row['bb_lower']) else 0
        bb_middle = float(row['bb_middle']) if not pd.isna(row['bb_middle']) else 0
        atr = float(row['atr']) if not pd.isna(row['atr']) else 0

        # POZİSYON YÖNETİMİ
        if pos is not None:
            # Stop loss
            if low <= pos['stop']:
                exit_p = pos['stop'] * (1 - slip)
                pnl_pct = (exit_p - pos['entry']) / pos['entry'] * 100 - 2 * COMMISSION * 100
                trades.append({'pnl_pct': pnl_pct, 'reason': 'SL', 'hours': i - pos['idx']})
                pos = None
                continue

            # ATR TP
            if 'tp' in pos and pos['tp'] and high >= pos['tp']:
                exit_p = pos['tp'] * (1 - slip)
                pnl_pct = (exit_p - pos['entry']) / pos['entry'] * 100 - 2 * COMMISSION * 100
                trades.append({'pnl_pct': pnl_pct, 'reason': 'ATR_TP', 'hours': i - pos['idx']})
                pos = None
                continue

            # RSI exit
            if rsi >= rsi_exit:
                exit_p = close * (1 - slip)
                pnl_pct = (exit_p - pos['entry']) / pos['entry'] * 100 - 2 * COMMISSION * 100
                trades.append({'pnl_pct': pnl_pct, 'reason': 'RSI_exit', 'hours': i - pos['idx']})
                pos = None
                continue

            # BB middle exit
            if use_bb_middle and close >= bb_middle:
                exit_p = close * (1 - slip)
                pnl_pct = (exit_p - pos['entry']) / pos['entry'] * 100 - 2 * COMMISSION * 100
                trades.append({'pnl_pct': pnl_pct, 'reason': 'BB_mid', 'hours': i - pos['idx']})
                pos = None
                continue

            # Time stop
            if (i - pos['idx']) >= max_hold_hours:
                exit_p = close * (1 - slip)
                pnl_pct = (exit_p - pos['entry']) / pos['entry'] * 100 - 2 * COMMISSION * 100
                trades.append({'pnl_pct': pnl_pct, 'reason': 'time', 'hours': i - pos['idx']})
                pos = None
                continue

        # GİRİŞ
        if pos is None and rsi < rsi_entry:
            # BB alt band gerekli mi?
            if use_bb_lower and not (close < bb_lower):
                continue

            entry = close * (1 + slip)
            stop = entry - atr * atr_sl_mult if atr > 0 else entry * 0.95
            tp = entry + atr * atr_tp_mult if atr > 0 and variation == 'V4' else None

            pos = {
                'entry': entry,
                'stop': stop,
                'tp': tp,
                'idx': i,
            }

    # Son açık pozisyonu kapat
    if pos is not None:
        last_close = float(df.iloc[-1]['close']) * (1 - slip)
        pnl_pct = (last_close - pos['entry']) / pos['entry'] * 100 - 2 * COMMISSION * 100
        trades.append({'pnl_pct': pnl_pct, 'reason': 'eof', 'hours': len(df) - pos['idx']})

    return {'trades': trades}


def aggregate(coin_data, coins, variation, **kwargs):
    all_trades = []
    for c in coins:
        if c not in coin_data:
            continue
        r = simulate(coin_data[c], c, variation, **kwargs)
        all_trades.extend(r['trades'])
    if not all_trades:
        return None
    pnls = [t['pnl_pct'] for t in all_trades]
    hours = [t['hours'] for t in all_trades]
    return {
        'n': len(pnls),
        'avg': np.mean(pnls),
        'win_rate': sum(1 for p in pnls if p > 0) / len(pnls) * 100,
        'best': max(pnls),
        'worst': min(pnls),
        'total': sum(pnls),
        'avg_hours': np.mean(hours),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    print('═' * 90)
    print('  📉 MEAN REVERSION — RSI Oversold Bounce (Realistic Slippage)')
    print('  Donchian\'ın tersi: dipten al, geri dönüşü yakala')
    print('═' * 90)

    coins = [
        'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT',
        'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT',
        'ATOM/USDT', 'NEAR/USDT', 'ARB/USDT', 'OP/USDT', 'APT/USDT',
        'INJ/USDT', 'SUI/USDT', 'TIA/USDT', 'FTM/USDT', 'ALGO/USDT',
    ]

    collector = DataCollector()
    print(f'\n📥 {len(coins)} coin verisi indiriliyor...')
    coin_data = {}
    for c in coins:
        df = collector.fetch_historical_data(c, '1h', args.start, args.end)
        if not df.empty:
            coin_data[c] = df
            print(f'  ✓ {c}')
        time.sleep(0.05)
    print(f'\n✅ {len(coin_data)} coin yüklendi\n')

    variations = [
        ('V1: RSI<25, exit RSI>70',     'V1', dict(rsi_entry=25, rsi_exit=70)),
        ('V2: RSI<20 (sıkı), >65',      'V2', dict(rsi_entry=20, rsi_exit=65)),
        ('V3: RSI<25 + BB low → BB mid','V3', dict(rsi_entry=25, rsi_exit=99, use_bb_lower=True, use_bb_middle=True)),
        ('V4: RSI<30 + ATR TP/SL',      'V4', dict(rsi_entry=30, rsi_exit=99, atr_tp_mult=2.0, atr_sl_mult=1.5)),
    ]

    print('  📊 VARYASYON KARŞILAŞTIRMASI (Realistic slippage)')
    print('  ' + '─' * 86)
    print(f'  {"VARYASYON":<32} {"İŞL":>5} {"WIN %":>7} {"ORT %":>8} {"BEST":>7} {"WORST":>7} {"AVG SAAT":>9} {"TOPLAM %":>10}')
    print('  ' + '─' * 86)

    results = []
    for label, var, params in variations:
        r = aggregate(coin_data, coins, variation=var, **params)
        if not r:
            continue
        results.append((label, r))
        print(f'  {label:<32} {r["n"]:>5} {r["win_rate"]:>6.1f}% '
              f'{r["avg"]:>+7.2f}% {r["best"]:>+6.1f}% {r["worst"]:>+6.1f}% '
              f'{r["avg_hours"]:>8.1f} {r["total"]:>+9.1f}%')

    if results:
        best = max(results, key=lambda x: x[1]['total'])
        best_name, best_r = best
        print()
        print(f'  🏆 EN İYİ: {best_name}')
        print(f'     Toplam: %{best_r["total"]:.1f} | Win rate %{best_r["win_rate"]:.1f}')

        # Compound
        avg_per = 1 + best_r['avg'] / 100
        n = best_r['n']
        position_pct = 0.30
        effective_avg = (1 - position_pct) + position_pct * avg_per
        final_full = 1000 * (avg_per ** n)
        final_sized = 1000 * (effective_avg ** n)
        years = (pd.to_datetime(args.end) - pd.to_datetime(args.start)).days / 365.25

        print(f'\n  💰 COMPOUND ($1000 başlangıç):')
        print(f'    Tam allocation: $1000 → ${final_full:,.0f} (matematik)')
        print(f'    %30 position sizing: $1000 → ${final_sized:,.0f}')
        if final_sized > 1000:
            yearly = (final_sized / 1000) ** (1 / years) - 1
            print(f'    Yıllık eşdeğer: +%{yearly*100:.1f}')

    print()
    print('═' * 90)
    print('  💡 YORUM:')
    print('  • Mean Reversion: counter-trend, dipten alım')
    print('  • Sideways pazarda en iyi (volatilite var ama trend yok)')
    print('  • Trend pazarda risk: dip dipten daha düşer ("falling knife")')
    print('═' * 90)


if __name__ == '__main__':
    main()
