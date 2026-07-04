"""
Donchian — 100 Coin Top Volume Test

Binance'in TOP 100 USDT pair'ini hacme göre seç, hepsinde test.
Daha çok small/mid-cap = daha çok patlama fırsatı.

ÖNEMLİ uyarı:
    Bu test survivorship bias'ı ARTIRIR — listeden çıkan (delist) coinler dahil değil.
    Gerçek hayatta listelenen 100 coin'in hepsi uzun süre yaşamayabilir.
"""
import sys
import os
import argparse
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
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


def get_top_100_usdt_pairs():
    """Binance'den top 100 hacimli USDT pair'i çek."""
    exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
    print('  📊 Binance ticker verisi alınıyor...')
    tickers = exchange.fetch_tickers()
    skip = {'USDC/USDT', 'BUSD/USDT', 'TUSD/USDT', 'FDUSD/USDT', 'DAI/USDT',
            'USDP/USDT', 'EUR/USDT', 'TRY/USDT', 'BRL/USDT', 'GBP/USDT', 'AUD/USDT', 'JPY/USDT'}
    usdt = [(s, t) for s, t in tickers.items()
             if s.endswith('/USDT') and s not in skip
             and t.get('quoteVolume') and t['quoteVolume'] > 0]
    usdt.sort(key=lambda x: x[1]['quoteVolume'], reverse=True)
    return [s for s, _ in usdt[:100]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    print('═' * 90)
    print(f'  🐢 DONCHIAN — 100 COIN TOP VOLUME TEST')
    print(f'  Config: Weekly TF, Entry=6, Exit=2, ATR=4.0')
    print('═' * 90)

    print('\n🔍 Top 100 hacimli USDT pair seçiliyor...')
    coins_100 = get_top_100_usdt_pairs()
    print(f'  ✅ {len(coins_100)} coin seçildi')
    print(f'  Top 5: {coins_100[:5]}')
    print(f'  ...')
    print(f'  Bottom 5: {coins_100[-5:]}')

    collector = DataCollector()
    print(f'\n📥 {len(coins_100)} coin verisi indiriliyor (~10-15 dk)...')
    raw_data = {}
    failed = []
    for i, c in enumerate(coins_100):
        try:
            df = collector.fetch_historical_data(c, '1h', args.start, args.end)
            if not df.empty and len(df) >= 1000:
                raw_data[c] = df
            else:
                failed.append(c)
        except Exception as e:
            failed.append(c)
        if (i + 1) % 25 == 0:
            print(f'  {i + 1}/{len(coins_100)} indirildi, {len(raw_data)} başarılı')
        time.sleep(0.05)

    print(f'\n✅ {len(raw_data)}/{len(coins_100)} coin yüklendi')
    if failed:
        print(f'  ❌ Veri yok ({len(failed)}): {", ".join(failed[:5])}{"..." if len(failed) > 5 else ""}')

    # Weekly resample
    coin_data = {c: resample(df, '1W') for c, df in raw_data.items()}
    coin_data = {c: df for c, df in coin_data.items() if len(df) >= 12}
    print(f'  ✅ {len(coin_data)} coin haftalık veri uygun\n')

    years = (pd.to_datetime(args.end) - pd.to_datetime(args.start)).days / 365.25

    # ── Karşılaştırma ──
    print('  📊 ÖZET KARŞILAŞTIRMA')
    print('  ' + '─' * 80)

    all_trades_per_coin = {}
    for c in coin_data:
        ts = simulate(coin_data[c], c)
        if ts:
            all_trades_per_coin[c] = ts

    flat_trades = [t for ts in all_trades_per_coin.values() for t in ts]
    if flat_trades:
        n = len(flat_trades)
        avg = np.mean(flat_trades)
        wr = sum(1 for p in flat_trades if p > 0) / n * 100
        total = sum(flat_trades)

        # Position sizing scenarios
        for pos_pct in [0.05, 0.10, 0.15]:
            avg_per = 1 + avg / 100
            effective = (1 - pos_pct) + pos_pct * avg_per
            final = effective ** n
            yearly = (final ** (1/years) - 1) * 100 if final > 0 else -100
            print(f'  100 coin (pos %{int(pos_pct*100)}) | İŞL: {n} | WIN: {wr:.1f}% | '
                  f'ORT: +{avg:.2f}% | TOPLAM: +{total:.0f}% | YIL (gerçekçi): +{yearly:.1f}%')

    # ── En Parlak ──
    print()
    print('  🌟 EN PARLAK 20 COIN (toplam P&L)')
    print('  ' + '─' * 70)
    print(f'  {"COIN":<14} {"İŞL":>4} {"WIN %":>7} {"ORT %":>8} {"TOPLAM %":>10}')
    print('  ' + '─' * 50)

    per_coin_stats = []
    for c, trades in all_trades_per_coin.items():
        if not trades or len(trades) < 3:
            continue
        per_coin_stats.append({
            'coin': c,
            'n': len(trades),
            'avg': np.mean(trades),
            'win_rate': sum(1 for p in trades if p > 0) / len(trades) * 100,
            'total': sum(trades),
        })
    per_coin_stats.sort(key=lambda x: x['total'], reverse=True)

    for s in per_coin_stats[:20]:
        print(f'  {s["coin"]:<14} {s["n"]:>4} {s["win_rate"]:>6.1f}% '
              f'{s["avg"]:>+7.2f}% {s["total"]:>+9.1f}%')

    print()
    print('  💀 EN KÖTÜ 10 COIN')
    print('  ' + '─' * 50)
    for s in per_coin_stats[-10:]:
        print(f'  {s["coin"]:<14} {s["n"]:>4} {s["win_rate"]:>6.1f}% '
              f'{s["avg"]:>+7.2f}% {s["total"]:>+9.1f}%')

    print()
    print('═' * 90)
    print('  💡 YORUM:')
    print('  • 100 coin tarama small-cap dahil etti, daha çok patlama fırsatı')
    print('  • Survivorship bias dikkat: delistlenmiş coinler tabloda yok')
    print('  • Gerçekçi position sizing %5-10 ile yıllık getiriyi bul')
    print('═' * 90)


if __name__ == '__main__':
    main()
