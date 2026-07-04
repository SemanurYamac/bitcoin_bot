"""
Volume Spike Hunter — hacim patlamasıyla momentum yakalama.

Mantık:
    Bir coin'in 24s hacmi son 7 gün ortalamasının N katına çıkarsa, ilgi
    artıyor demektir → fiyat hareket olasılığı yüksek.

Strateji:
    Spike tespit (24h_vol > 7d_avg × multiplier)
    Pozisyon aç → fiyat × hold_hours bar boyunca tut
    TP veya SL veya zaman aşımı → çık

Backtest:
    20 popüler coinde 4 yıllık 1h veri
    Her saatlik bar'da spike kontrol
    Çoklu spike multiplier ve TP/SL kombinasyonu test
"""
import sys
import os
import argparse
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from data.collector import DataCollector


COMMISSION = 0.001  # her işlem


# Test edilecek coin evreni — yüksek hacimli, likit
COINS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT',
    'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT',
    'ATOM/USDT', 'NEAR/USDT', 'ARB/USDT', 'OP/USDT', 'APT/USDT',
    'INJ/USDT', 'SUI/USDT', 'TIA/USDT', 'FTM/USDT', 'ALGO/USDT',
]


def detect_spikes(df: pd.DataFrame, multiplier: float = 3.0,
                   lookback_hours: int = 168) -> pd.Series:
    """
    Hacim spike'larını tespit eder.

    Bir bar spike sayılır:
        son 24 saatin toplam hacmi, son 7 günün günlük ortalamasının N katı
    """
    df = df.copy()
    # Saatlik hacim → günlük hacim approximation
    df['volume_24h'] = df['volume'].rolling(24).sum()
    df['avg_24h_vol'] = df['volume_24h'].rolling(lookback_hours).mean().shift(24)
    df['vol_ratio'] = df['volume_24h'] / df['avg_24h_vol']
    return df['vol_ratio'] >= multiplier


def simulate_strategy(df: pd.DataFrame, multiplier: float, hold_hours: int,
                      tp_pct: float, sl_pct: float, capital_per_trade: float = 100) -> dict:
    """Tek coin üzerinde spike-hunter backtest."""
    if df.empty or len(df) < 200:
        return {'trades': [], 'pnl': 0, 'win_rate': 0}

    spikes = detect_spikes(df, multiplier=multiplier)
    trades = []
    last_entry_idx = -1

    for i in range(168, len(df) - hold_hours):
        # Cooldown: son işlemden 24h sonra yenisini ara
        if last_entry_idx >= 0 and (i - last_entry_idx) < 24:
            continue

        if not spikes.iloc[i]:
            continue

        # Pozisyon aç
        entry = float(df.iloc[i]['close'])
        if entry <= 0:
            continue

        tp = entry * (1 + tp_pct / 100)
        sl = entry * (1 - sl_pct / 100)

        # hold_hours bar boyunca takip
        exit_p = float(df.iloc[i + hold_hours - 1]['close'])
        exit_reason = 'time'
        for j in range(i + 1, min(i + hold_hours, len(df))):
            bar = df.iloc[j]
            if bar['low'] <= sl:
                exit_p = sl
                exit_reason = 'SL'
                break
            if bar['high'] >= tp:
                exit_p = tp
                exit_reason = 'TP'
                break

        pnl_pct = (exit_p - entry) / entry * 100 - 2 * COMMISSION * 100
        trades.append({
            'entry_idx': i,
            'entry': entry,
            'exit': exit_p,
            'reason': exit_reason,
            'pnl_pct': pnl_pct,
        })
        last_entry_idx = i

    if not trades:
        return {'trades': [], 'pnl_pct_avg': 0, 'win_rate': 0, 'n_trades': 0}

    pnls = [t['pnl_pct'] for t in trades]
    return {
        'trades': trades,
        'pnl_pct_avg': np.mean(pnls),
        'pnl_pct_total': sum(pnls),
        'win_rate': sum(1 for p in pnls if p > 0) / len(pnls) * 100,
        'best': max(pnls),
        'worst': min(pnls),
        'n_trades': len(trades),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    print('═' * 80)
    print(f'  🎯 VOLUME SPIKE HUNTER — Backtest')
    print(f'  20 coin × 4 yıl × farklı parametre kombinasyonları')
    print('═' * 80)

    collector = DataCollector()

    print('\n📥 20 coin verisi indiriliyor...')
    coin_data = {}
    for c in COINS:
        df = collector.fetch_historical_data(c, '1h', args.start, args.end)
        if not df.empty:
            coin_data[c] = df
            print(f'  ✓ {c}: {len(df):,} mum')
        else:
            print(f'  ✗ {c}: veri yok')
        time.sleep(0.05)

    if not coin_data:
        print('Hiç coin yok')
        return

    print(f'\n✅ {len(coin_data)} coin yüklendi\n')

    # ─── Çoklu parametre testi ───
    configs = [
        # (multiplier, hold_h, tp%, sl%, label)
        (3.0,  72,  15,  8, 'standart'),
        (3.0,  48,  10,  5, 'hızlı_flip'),
        (5.0,  72,  20, 10, 'sıkı_spike'),
        (3.0, 168,  25, 12, 'haftalık_hold'),
        (4.0,  72,  15,  7, 'orta_yol'),
    ]

    print('  PARAMETRE             | Toplam İşl | Win % | Ort P&L% | Best  | Worst | Toplam P&L%')
    print('  ' + '─' * 88)

    all_results = []
    for mul, hh, tp, sl, lab in configs:
        # Tüm coinlerin sonuçlarını birleştir
        total_trades = []
        for c, df in coin_data.items():
            r = simulate_strategy(df, multiplier=mul, hold_hours=hh, tp_pct=tp, sl_pct=sl)
            total_trades.extend(r['trades'])

        if not total_trades:
            print(f'  {lab:<22}| 0 işlem')
            continue

        pnls = [t['pnl_pct'] for t in total_trades]
        win_rate = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        avg = np.mean(pnls)
        total = sum(pnls)
        best = max(pnls)
        worst = min(pnls)

        config_label = f'{lab} ({mul:.1f}x, {hh}h, +{tp}/-{sl})'
        print(f'  {config_label:<22}| {len(total_trades):>10} | {win_rate:>5.1f}% | '
              f'{avg:>+7.2f}% | {best:>+5.1f}% | {worst:>+5.1f}% | {total:>+8.1f}%')

        all_results.append({
            'config': config_label,
            'n_trades': len(total_trades),
            'avg': avg,
            'win_rate': win_rate,
            'total': total,
        })

    print()
    if all_results:
        best_cfg = max(all_results, key=lambda x: x['total'])
        print(f'  🏆 EN İYİ: {best_cfg["config"]}')
        print(f'     Toplam P&L: {best_cfg["total"]:+.1f}% ({best_cfg["n_trades"]} işlem, '
              f'win rate %{best_cfg["win_rate"]:.1f})')

        # Pratik tahmini
        per_trade_usdt = 50
        n = best_cfg['n_trades']
        avg = best_cfg['avg']
        total_pnl_dollar = per_trade_usdt * avg / 100 * n
        years = 4  # backtest dönemi
        print(f'\n  📈 SİZE ÖZEL — {best_cfg["config"]}:')
        print(f'    Her işleme $50 koysan: {n} işlem × ${per_trade_usdt * avg / 100:+.2f} avg = ${total_pnl_dollar:+.0f} ({years} yılda)')
        print(f'    Yıllık ortalama: ${total_pnl_dollar/years:+.0f} | Aylık: ${total_pnl_dollar/years/12:+.2f}')

    print()
    print('═' * 80)


if __name__ == '__main__':
    main()
