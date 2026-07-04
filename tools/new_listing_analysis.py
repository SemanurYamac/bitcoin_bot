"""
New Listing Snipe Bot — Backtest ve İstatistiksel Analiz.

Mantık:
    1. Binance'in tüm USDT spot çiftlerini al
    2. Her coin için en eski mum tarihini bul = listing date'inin yaklaşık değeri
    3. Son 24 ayda listelenenleri filtrele
    4. Her birinin ilk 24 saat / 1 hafta performansını hesapla
    5. Çeşitli sniping stratejilerini simüle et:
       - Strateji 1: t=0 al, 1 saat sonra sat (hızlı flip)
       - Strateji 2: t=0 al, 4 saat sonra sat
       - Strateji 3: t=0 al, +%30 take-profit veya -%15 stop-loss
       - Strateji 4: t=0 al, 24 saat sonra sat (uzun pozisyon)
    6. İstatistikler: ortalama getiri, win rate, en iyi/en kötü, expectancy

ÖNEMLİ NOT:
    - Bu BACKTEST'tir, gerçek sniping'de slippage çok daha yüksek
    - İlk dakikalarda spread %5-15 olabilir — gerçek getiri burada %20-30 düşük
    - "İlk fiyat" = ilk mum'un open'ı, gerçekte execute edebilen fiyat değil

Kullanım:
    python3 tools/new_listing_analysis.py [--lookback-days 730]
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


COMMISSION = 0.001  # %0.1 her işlem (alış + satış = %0.2 toplam)


def get_listing_date(exchange, symbol: str, max_lookback_years: int = 5) -> datetime | None:
    """
    Bir sembolün ilk işlem tarihini bulur.
    En eski 1d mum'un tarihini listing tarihi olarak kabul eder.
    """
    try:
        # 5 yıl öncesinden başlayarak ilk mumu ara
        since = int((datetime.now() - timedelta(days=max_lookback_years * 365)).timestamp() * 1000)
        ohlcv = exchange.fetch_ohlcv(symbol, '1d', since=since, limit=1)
        if not ohlcv:
            return None
        return datetime.fromtimestamp(ohlcv[0][0] / 1000)
    except Exception:
        return None


def fetch_first_week_data(exchange, symbol: str, listing_date: datetime) -> pd.DataFrame | None:
    """Listing'den itibaren ilk 7 günün 1 saatlik mumlarını çeker (168 mum)."""
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


def simulate_strategies(df: pd.DataFrame) -> dict:
    """
    Bir coin'in listing sonrası 1 haftalık verisinden 4 stratejinin sonucunu hesaplar.
    """
    if df is None or len(df) < 24:
        return None

    entry_price = float(df.iloc[0]['open'])  # İlk mumun open'ı (listing açılış)
    if entry_price <= 0:
        return None

    fee_total = 2 * COMMISSION  # Buy + sell

    results = {}

    # Strateji 1: 1 saat tut
    if len(df) > 1:
        exit_p = float(df.iloc[1]['close'])
        results['1h_flip'] = (exit_p - entry_price) / entry_price * 100 - fee_total * 100

    # Strateji 2: 4 saat tut
    if len(df) > 4:
        exit_p = float(df.iloc[4]['close'])
        results['4h_hold'] = (exit_p - entry_price) / entry_price * 100 - fee_total * 100

    # Strateji 3: +%30 TP veya -%15 SL (24 saat içinde)
    tp = entry_price * 1.30
    sl = entry_price * 0.85
    exit_reason = '24h_timeout'
    exit_p = float(df.iloc[min(23, len(df) - 1)]['close'])
    for i in range(min(24, len(df))):
        bar = df.iloc[i]
        if bar['low'] <= sl:
            exit_p = sl
            exit_reason = 'SL'
            break
        if bar['high'] >= tp:
            exit_p = tp
            exit_reason = 'TP'
            break
    results['tp_sl'] = (exit_p - entry_price) / entry_price * 100 - fee_total * 100
    results['tp_sl_reason'] = exit_reason

    # Strateji 4: 24 saat tut
    if len(df) > 24:
        exit_p = float(df.iloc[23]['close'])
        results['24h_hold'] = (exit_p - entry_price) / entry_price * 100 - fee_total * 100

    # Bonus istatistikler
    first_24h = df.iloc[:24] if len(df) >= 24 else df
    results['max_gain_24h'] = (first_24h['high'].max() - entry_price) / entry_price * 100
    results['max_drawdown_24h'] = (first_24h['low'].min() - entry_price) / entry_price * 100
    if len(df) >= 168:
        results['after_1week'] = (df.iloc[167]['close'] - entry_price) / entry_price * 100
    else:
        last_close = float(df.iloc[-1]['close'])
        results['after_1week'] = (last_close - entry_price) / entry_price * 100

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lookback-days', type=int, default=730, help='Son kaç gün (default 2 yıl)')
    parser.add_argument('--max-coins', type=int, default=50, help='Max coin sayısı (zaman tasarrufu)')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    print('═' * 78)
    print(f'  🎯 NEW LISTING SNIPE — Backtest Analizi')
    print(f'  Hedef: Son {args.lookback_days} gün ({args.lookback_days/365:.1f} yıl) içinde listelenen coinler')
    print('═' * 78)

    exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

    print('\n📥 Binance USDT pair listesi alınıyor...')
    markets = exchange.load_markets()
    usdt_pairs = sorted([s for s, m in markets.items()
                          if s.endswith('/USDT') and m.get('active') and m.get('spot')])
    print(f'  ✅ {len(usdt_pairs)} aktif USDT pair')

    # Stablecoin / non-coin'leri çıkar
    skip = {'USDC/USDT', 'BUSD/USDT', 'TUSD/USDT', 'FDUSD/USDT', 'DAI/USDT', 'USDP/USDT', 'EUR/USDT', 'TRY/USDT', 'BRL/USDT', 'GBP/USDT', 'AUD/USDT', 'JPY/USDT'}
    usdt_pairs = [s for s in usdt_pairs if s not in skip]

    print(f'\n🔍 Listing tarihleri taranıyor (~{len(usdt_pairs)} coin)... uzun sürer')

    cutoff_date = datetime.now() - timedelta(days=args.lookback_days)
    new_listings = []

    for i, sym in enumerate(usdt_pairs):
        listing_date = get_listing_date(exchange, sym)
        if listing_date is None:
            continue
        if listing_date > cutoff_date:
            new_listings.append((sym, listing_date))
        if (i + 1) % 50 == 0:
            print(f'    {i + 1}/{len(usdt_pairs)} tarandı, şu ana kadar {len(new_listings)} yeni listing')
        time.sleep(0.05)  # rate limit safety

    print(f'\n✅ {len(new_listings)} yeni listing tespit edildi (son {args.lookback_days} gün)')

    if not new_listings:
        print('  ⚠️ Yeni listing bulunamadı.')
        return

    # En son listelenenleri öne al, max_coins kadar test et
    new_listings.sort(key=lambda x: x[1], reverse=True)
    selected = new_listings[:args.max_coins]
    print(f'  Test edilecek: ilk {len(selected)} en yeni listing\n')

    print('  Listing | Tarih       | 1h flip | 4h hold | TP/SL  | 24h hold | Max kazanç | Max düşüş | 1 hafta sonra')
    print('  ' + '─' * 95)

    all_results = []
    for sym, lst_date in selected:
        df = fetch_first_week_data(exchange, sym, lst_date)
        if df is None or len(df) < 4:
            continue
        r = simulate_strategies(df)
        if r is None:
            continue
        r['symbol'] = sym
        r['listing_date'] = lst_date
        all_results.append(r)

        print(f'  {sym:<14} {lst_date.strftime("%Y-%m-%d"):<12} '
              f'{r.get("1h_flip", 0):>+6.1f}% '
              f'{r.get("4h_hold", 0):>+6.1f}% '
              f'{r.get("tp_sl", 0):>+6.1f}% '
              f'{r.get("24h_hold", 0):>+6.1f}% '
              f'{r["max_gain_24h"]:>+8.1f}% '
              f'{r["max_drawdown_24h"]:>+8.1f}% '
              f'{r["after_1week"]:>+8.1f}%')
        time.sleep(0.1)

    if not all_results:
        print('  ⚠️ Yeterli veri çekilemedi.')
        return

    # ─── Strateji Bazında İstatistikler ───
    print('\n' + '═' * 78)
    print('  📊 STRATEJİ BAZINDA İSTATİSTİKLER')
    print('═' * 78)

    strategies = ['1h_flip', '4h_hold', 'tp_sl', '24h_hold', 'after_1week']
    print(f'\n  {"STRATEJİ":<15} {"ORT %":>9} {"MEDYAN":>9} {"WIN %":>9} {"EN İYİ":>9} {"EN KÖTÜ":>9} {"EXPECTANCY":>11}')
    print('  ' + '─' * 75)

    for st in strategies:
        values = [r[st] for r in all_results if st in r and not pd.isna(r[st])]
        if not values:
            continue
        wins = sum(1 for v in values if v > 0)
        avg = np.mean(values)
        median = np.median(values)
        win_rate = wins / len(values) * 100
        best = max(values)
        worst = min(values)
        # Expectancy: ortalama × 1 = $X / işlem $1 yatırımda
        expectancy = avg / 100  # %30 ortalama → $0.30 kazanç/dolar

        print(f'  {st:<15} {avg:>+8.2f}% {median:>+8.2f}% {win_rate:>7.1f}% {best:>+8.1f}% {worst:>+8.1f}% ${expectancy:>+9.2f}')

    print()
    print('  📊 ÖZET:')
    n = len(all_results)
    avg_max_gain = np.mean([r['max_gain_24h'] for r in all_results])
    avg_max_dd = np.mean([r['max_drawdown_24h'] for r in all_results])
    print(f'  Test edilen listing: {n}')
    print(f'  Ortalama max kazanç (ilk 24s):   {avg_max_gain:+.2f}%')
    print(f'  Ortalama max düşüş (ilk 24s):    {avg_max_dd:+.2f}%')

    # ─── Pratik Tavsiyeler ───
    print()
    print('  💡 SİMÜLASYON ÇIKARIMLARI:')
    best_strategy = max(strategies, key=lambda s: np.mean([r[s] for r in all_results if s in r]))
    best_avg = np.mean([r[best_strategy] for r in all_results if best_strategy in r])
    print(f'  En kârlı strateji: {best_strategy} (ort {best_avg:+.2f}%)')

    # Eğer 1h_flip pozitifse ve TP/SL pozitifse → strateji çalışıyor
    avg_1h = np.mean([r['1h_flip'] for r in all_results if '1h_flip' in r])
    if avg_1h > 5:
        print(f'  ✅ 1h flip pozitif ({avg_1h:+.2f}%) — hızlı snipe çalışabilir')
    elif avg_1h < -2:
        print(f'  ❌ 1h flip negatif ({avg_1h:+.2f}%) — ilk saatte çoğunlukla düşüş')
    else:
        print(f'  ⚠️ 1h flip belirsiz ({avg_1h:+.2f}%) — yüksek varyans')

    print()
    print('  ⚠️ KAYNAKLAR (Backtest sınırları):')
    print('  • İlk fiyat = ilk mumun open\'ı (gerçekte +%5-15 spread olur)')
    print('  • Slippage ve order book derinliği hesaplanmadı')
    print('  • Frontrunning ve kurumsal botlar dahil değil')
    print('  • Gerçek getiri burada gösterilenden %20-30 daha düşük olur')
    print('═' * 78)


if __name__ == '__main__':
    main()
