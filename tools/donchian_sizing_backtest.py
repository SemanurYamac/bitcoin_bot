"""
Donchian Weekly — Ayı Rejimi Sizing Süpürmesi (2026-07-27)

Soru: canlıda ayı rejiminde pozisyon başına serbest USDT'nin %10'u/max 5
kullanılıyor ve sermayenin büyük kısmı boşta kalıyor. Ayıda daha agresif
sizing getiriyi artırır mı, yoksa sadece drawdown mı ekler?

Boğa sizing'i canlıyla aynı sabit (%18/6). Sadece AYI sizing'i süpürülür.
Veri/işleyiş donchian_regime_backtest.py ile birebir aynı (slippage + %0.1
komisyon, sinyaller kapanmış mumlardan, look-ahead yok).

Kullanım (yerel veya container):
  python tools/donchian_sizing_backtest.py --capital 370
"""
import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt

BASE_DIR = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = BASE_DIR / 'data' / 'donchian_universe.json'

ENTRY_P, EXIT_P, ATR_P, ATR_MULT = 6, 2, 14, 4.0
COMMISSION = 0.001
REGIME_EMA = 40
LARGE_CAP = {'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'SOL/USDT'}
MID_CAP = {'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT'}

# Süpürme dışında kalan rejimin sabit ayarı (canlıyla aynı)
FIXED = {'bear': (0.10, 5), 'bull': (0.18, 6)}

# (etiket, pct, max_pos)
BEAR_VARIANTS = [
    ('ayı %10/5  (CANLI)', 0.10, 5),
    ('ayı %12/5', 0.12, 5),
    ('ayı %15/5', 0.15, 5),
    ('ayı %15/6', 0.15, 6),
    ('ayı %18/6', 0.18, 6),
    ('ayı %20/6', 0.20, 6),
    ('ayı %25/6', 0.25, 6),
]
BULL_VARIANTS = [
    ('boğa %18/6 (CANLI)', 0.18, 6),
    ('boğa %20/6', 0.20, 6),
    ('boğa %22/7', 0.22, 7),
    ('boğa %25/7', 0.25, 7),
    ('boğa %25/8', 0.25, 8),
    ('boğa %30/8', 0.30, 8),
    ('boğa %35/8', 0.35, 8),
]


def slippage(sym):
    if sym in LARGE_CAP: return 0.002
    if sym in MID_CAP: return 0.004
    return 0.007


def wilder_atr_series(candles):
    atrs = [0.0] * len(candles)
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i][2], candles[i][3], candles[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(trs) == ATR_P:
            atrs[i] = sum(trs) / ATR_P
        elif len(trs) > ATR_P:
            atrs[i] = (atrs[i - 1] * (ATR_P - 1) + trs[-1]) / ATR_P
    return atrs


def prepare_coin(candles):
    out = {}
    atrs = wilder_atr_series(candles)
    for i in range(max(ENTRY_P, ATR_P + 1), len(candles)):
        out[candles[i][0]] = {
            'high': candles[i][2], 'low': candles[i][3], 'close': candles[i][4],
            'd_high': max(c[2] for c in candles[i - ENTRY_P:i]),
            'd_low': min(c[3] for c in candles[i - EXIT_P:i]),
            'atr': atrs[i],
        }
    return out


def btc_regime_map(btc_candles):
    closes = [c[4] for c in btc_candles]
    k = 2 / (REGIME_EMA + 1)
    ema = closes[0]
    emas = [ema]
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
        emas.append(ema)
    regime = {}
    for i in range(1, len(btc_candles)):
        warm = i - 1 >= REGIME_EMA
        regime[btc_candles[i][0]] = 'bull' if warm and closes[i - 1] > emas[i - 1] else 'bear'
    return regime


def simulate(coin_data, regime_map, cfg, start_ts, initial_cash):
    timeline = sorted({ts for d in coin_data.values() for ts in d} | set(regime_map))
    timeline = [ts for ts in timeline if ts >= start_ts]
    cash, positions, trades = initial_cash, {}, []
    peak, max_dd = initial_cash, 0.0
    last_regime = 'bear'

    for ts in timeline:
        last_regime = regime_map.get(ts, last_regime)
        pct, max_pos = cfg[last_regime]

        for sym in list(positions):
            bar = coin_data.get(sym, {}).get(ts)
            if not bar:
                continue
            pos = positions[sym]
            slip = slippage(sym)
            exit_price = None
            if bar['low'] <= pos['stop']:
                exit_price = pos['stop'] * (1 - slip)
            elif bar['d_low'] > 0 and bar['low'] <= bar['d_low']:
                exit_price = bar['d_low'] * (1 - slip)
            if exit_price:
                revenue = pos['amount'] * exit_price * (1 - COMMISSION)
                cash += revenue
                trades.append(revenue - pos['cost'])
                del positions[sym]
            else:
                new_stop = bar['close'] - bar['atr'] * ATR_MULT
                if new_stop > pos['stop']:
                    pos['stop'] = new_stop

        for sym, data in coin_data.items():
            if sym in positions or len(positions) >= max_pos:
                continue
            bar = data.get(ts)
            if not bar or bar['atr'] <= 0 or bar['d_high'] <= 0:
                continue
            if bar['high'] >= bar['d_high']:
                slip = slippage(sym)
                entry = bar['d_high'] * (1 + slip)
                value = cash * pct
                if value < 5 or value > cash:
                    continue
                cash -= value * (1 + COMMISSION)
                positions[sym] = {
                    'amount': value / entry, 'entry': entry,
                    'stop': entry - bar['atr'] * ATR_MULT,
                    'cost': value * (1 + COMMISSION),
                }

        equity = cash + sum(
            pos['amount'] * coin_data[sym][ts]['close']
            for sym, pos in positions.items() if ts in coin_data.get(sym, {})
        ) + sum(
            pos['amount'] * pos['entry']
            for sym, pos in positions.items() if ts not in coin_data.get(sym, {})
        )
        peak = max(peak, equity)
        max_dd = min(max_dd, (equity - peak) / peak * 100)

    for sym, pos in positions.items():
        last_ts = max(coin_data[sym])
        revenue = pos['amount'] * coin_data[sym][last_ts]['close'] * (1 - COMMISSION)
        cash += revenue
        trades.append(revenue - pos['cost'])

    wins = sum(1 for t in trades if t > 0)
    return {
        'final': cash, 'ret': (cash / initial_cash - 1) * 100,
        'max_dd': max_dd, 'n_trades': len(trades),
        'wr': wins / len(trades) * 100 if trades else 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capital', type=float, default=370.0)
    parser.add_argument('--sweep', choices=['bear', 'bull'], default='bear',
                        help='Hangi rejimin sizing süpürülsün (diğeri canlı sabit)')
    args = parser.parse_args()
    variants = BEAR_VARIANTS if args.sweep == 'bear' else BULL_VARIANTS
    other = 'bull' if args.sweep == 'bear' else 'bear'

    with open(UNIVERSE_PATH) as f:
        universe = json.load(f)['coins']

    ex = ccxt.binance({'enableRateLimit': True})
    ex.load_markets()

    print(f'📥 {len(universe)} coin haftalık veri indiriliyor...')
    raw = {}
    for sym in universe:
        if sym not in ex.markets:
            continue
        try:
            candles = ex.fetch_ohlcv(sym, '1w', limit=500)
            if len(candles) > ATR_P + ENTRY_P + 2:
                raw[sym] = candles
        except Exception as e:
            print(f'  ⚠️ {sym}: {e}')
        time.sleep(0.1)
    print(f'  ✅ {len(raw)} coin yüklendi')

    coin_data = {sym: prepare_coin(c) for sym, c in raw.items()}
    regime_map = btc_regime_map(raw['BTC/USDT'])
    bull_weeks = sum(1 for v in regime_map.values() if v == 'bull')
    fp, fm = FIXED[other]
    print(f'  Rejim: {bull_weeks}/{len(regime_map)} hafta boğa | '
          f'{other} sizing sabit %{fp*100:.0f}/{fm} | süpürülen: {args.sweep}\n')

    now = datetime.now(timezone.utc)
    windows = {'Son 12 ay (ayı ağırlıklı)': 12, 'Son 2 yıl': 24, 'Son 4 yıl': 48}

    for wname, months in windows.items():
        start_ts = int((now - timedelta(days=months * 30)).timestamp() * 1000)
        print(f'═══ {wname} ═══')
        print(f'{"Sizing":22} {"Final":>10} {"Getiri":>9} {"MaxDD":>8} {"İşlem":>6} {"WR":>6}')
        for label, pct, max_pos in variants:
            cfg = dict(FIXED)
            cfg[args.sweep] = (pct, max_pos)
            r = simulate(coin_data, regime_map, cfg, start_ts, args.capital)
            print(f'{label:22} ${r["final"]:>9.2f} {r["ret"]:>+8.2f}% '
                  f'{r["max_dd"]:>7.2f}% {r["n_trades"]:>6} {r["wr"]:>5.1f}%')
        print()


if __name__ == '__main__':
    main()
