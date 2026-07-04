"""
New Listing Snipe — Gerçekçi Slippage Modeli ile.

3 senaryo yan yana:
  Optimistic:    Entry = ilk mum open      (mevcut backtest — gerçekçi değil)
  Realistic:     Entry = ilk mum high      (ilk 1h içinde ortalama tepe)
  Pessimistic:   Entry = ilk mum high × 1.05  (high + ekstra spread)

Exit slippage:
  TP'ye vurduğunda kuyrukta beklersin → -%2 daha az al
  SL'e vurduğunda hızlı dış bahis ama -%1 ekstra
"""
import sys
import os
import argparse
import logging
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import pandas as pd
import numpy as np


COMMISSION = 0.001  # %0.1 her işlem


def get_listing_date(exchange, symbol: str, max_lookback_years: int = 5):
    try:
        since = int((datetime.now() - timedelta(days=max_lookback_years * 365)).timestamp() * 1000)
        ohlcv = exchange.fetch_ohlcv(symbol, '1d', since=since, limit=1)
        if not ohlcv:
            return None
        return datetime.fromtimestamp(ohlcv[0][0] / 1000)
    except Exception:
        return None


def fetch_first_week_data(exchange, symbol: str, listing_date: datetime):
    try:
        since = int(listing_date.timestamp() * 1000)
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', since=since, limit=168)
        if not ohlcv:
            return None
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        df.set_index('ts', inplace=True)
        return df.astype(float)
    except Exception:
        return None


def simulate_with_slippage(df: pd.DataFrame, entry_mode: str = 'optimistic') -> dict:
    """
    Slippage modeline göre TP/SL %30/-%15 stratejisini simüle eder.

    entry_mode:
        'optimistic'  → entry = first open
        'realistic'   → entry = first high (ilk saatin tepesi)
        'pessimistic' → entry = first high × 1.05 (high + spread)

    Exit slippage:
        TP exit: -%2 ekstra (kuyrukta beklersin)
        SL exit: -%1 ekstra (hızlı dışarı ama spread)
    """
    if df is None or len(df) < 24:
        return None

    first = df.iloc[0]

    if entry_mode == 'optimistic':
        entry = float(first['open'])
        exit_haircut_tp = 0.0
        exit_haircut_sl = 0.0
    elif entry_mode == 'realistic':
        entry = float(first['high'])
        exit_haircut_tp = 0.02   # TP'ye -%2
        exit_haircut_sl = 0.01   # SL'e -%1
    else:  # pessimistic
        entry = float(first['high']) * 1.05
        exit_haircut_tp = 0.03
        exit_haircut_sl = 0.015

    if entry <= 0:
        return None

    fee = 2 * COMMISSION

    tp = entry * 1.30
    sl = entry * 0.85

    exit_p = float(df.iloc[min(23, len(df) - 1)]['close'])
    exit_reason = '24h_timeout'
    for i in range(min(24, len(df))):
        bar = df.iloc[i]
        if bar['low'] <= sl:
            # SL hit — slippage'la fiyatın altında çık
            exit_p = sl * (1 - exit_haircut_sl)
            exit_reason = 'SL'
            break
        if bar['high'] >= tp:
            # TP hit — kuyrukta bekledikçe %2 daha az al
            exit_p = tp * (1 - exit_haircut_tp)
            exit_reason = 'TP'
            break

    pnl_pct = (exit_p - entry) / entry * 100 - fee * 100

    return {
        'entry': entry,
        'exit': exit_p,
        'exit_reason': exit_reason,
        'pnl_pct': pnl_pct,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lookback-days', type=int, default=730)
    parser.add_argument('--max-coins', type=int, default=40)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    print('═' * 90)
    print(f'  🎯 NEW LISTING SNIPE — Gerçekçi Slippage Modeli (TP +%30 / SL -%15)')
    print(f'  3 senaryo: Optimistic (open), Realistic (high), Pessimistic (high × 1.05)')
    print('═' * 90)

    exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

    print('\n📥 Listing tarihleri taranıyor...')
    markets = exchange.load_markets()
    skip = {'USDC/USDT', 'BUSD/USDT', 'TUSD/USDT', 'FDUSD/USDT', 'DAI/USDT', 'USDP/USDT',
            'EUR/USDT', 'TRY/USDT', 'BRL/USDT', 'GBP/USDT', 'AUD/USDT', 'JPY/USDT'}
    usdt_pairs = sorted([s for s, m in markets.items()
                          if s.endswith('/USDT') and m.get('active') and m.get('spot')
                          and s not in skip])

    cutoff_date = datetime.now() - timedelta(days=args.lookback_days)
    new_listings = []

    for i, sym in enumerate(usdt_pairs):
        listing_date = get_listing_date(exchange, sym)
        if listing_date is None:
            continue
        if listing_date > cutoff_date:
            new_listings.append((sym, listing_date))
        if (i + 1) % 100 == 0:
            print(f'  {i + 1}/{len(usdt_pairs)} taradı, {len(new_listings)} yeni listing')
        time.sleep(0.05)

    print(f'\n✅ {len(new_listings)} yeni listing bulundu')

    new_listings.sort(key=lambda x: x[1], reverse=True)
    selected = new_listings[:args.max_coins]
    print(f'  Test: ilk {len(selected)} en yeni\n')

    print(f'  {"COIN":<14} {"TARIH":<11} {"OPTIMIST":>10} {"REALIST":>10} {"PESSIMIST":>11}')
    print('  ' + '─' * 60)

    results = {'optimistic': [], 'realistic': [], 'pessimistic': []}

    for sym, lst_date in selected:
        df = fetch_first_week_data(exchange, sym, lst_date)
        if df is None or len(df) < 4:
            continue

        opt = simulate_with_slippage(df, 'optimistic')
        real = simulate_with_slippage(df, 'realistic')
        pes = simulate_with_slippage(df, 'pessimistic')

        if not (opt and real and pes):
            continue

        results['optimistic'].append(opt['pnl_pct'])
        results['realistic'].append(real['pnl_pct'])
        results['pessimistic'].append(pes['pnl_pct'])

        print(f'  {sym:<14} {lst_date.strftime("%Y-%m-%d"):<11} '
              f'{opt["pnl_pct"]:>+8.1f}%  {real["pnl_pct"]:>+8.1f}%  {pes["pnl_pct"]:>+9.1f}%')
        time.sleep(0.1)

    print()
    print('═' * 90)
    print('  📊 İSTATİSTİK KARŞILAŞTIRMA — Slippage Etkisi')
    print('═' * 90)
    print(f'\n  {"SENARYO":<14} {"ORT %":>10} {"MEDYAN":>10} {"WIN %":>8} {"EN İYİ":>10} {"EN KÖTÜ":>10} {"EXPECTANCY":>12}')
    print('  ' + '─' * 75)

    for scenario in ['optimistic', 'realistic', 'pessimistic']:
        vals = results[scenario]
        if not vals:
            continue
        avg = np.mean(vals)
        median = np.median(vals)
        wins = sum(1 for v in vals if v > 0)
        win_rate = wins / len(vals) * 100
        best = max(vals)
        worst = min(vals)
        expectancy = avg / 100  # $1 yatırım/listing → $X kazanç

        emoji = {'optimistic': '🟢', 'realistic': '🟡', 'pessimistic': '🔴'}[scenario]
        print(f'  {emoji} {scenario:<11} {avg:>+9.2f}% {median:>+9.2f}% {win_rate:>6.1f}% '
              f'{best:>+9.1f}% {worst:>+9.1f}% ${expectancy:>+10.2f}')

    print()
    print('  💡 PRATIK YORUMLAR:')

    if results['realistic']:
        avg_real = np.mean(results['realistic'])
        avg_opt = np.mean(results['optimistic'])
        avg_pes = np.mean(results['pessimistic'])
        print(f'  • Optimistic backtest: {avg_opt:+.2f}% (gerçekçi değil)')
        print(f'  • Realistic backtest:  {avg_real:+.2f}% (high entry, %2 exit haircut)')
        print(f'  • Pessimistic:         {avg_pes:+.2f}% (high × 1.05 entry, %3 exit haircut)')
        print()

        # Sermaye senaryosu
        per_listing_usdt = 20  # $20/listing
        n_listings = len(results['realistic'])
        avg_dollar = per_listing_usdt * avg_real / 100
        total_dollar = avg_dollar * n_listings
        print(f'  📈 SİZE ÖZEL — Realistic senaryoda:')
        print(f'    Her listing\'e $20 koysan: ${avg_dollar:+.2f}/listing')
        print(f'    {n_listings} listing × $20 → toplam ${total_dollar:+.2f}')

        if avg_real > 0:
            # Aylık tahmini
            monthly_listings = n_listings / (args.lookback_days / 30)
            monthly_pnl = monthly_listings * avg_dollar
            print(f'    Ayda ortalama {monthly_listings:.1f} listing × ${avg_dollar:.2f} = ${monthly_pnl:+.2f}/ay')

    print('═' * 90)


if __name__ == '__main__':
    main()
