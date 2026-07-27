"""
Donchian Weekly — Kayıp Azaltma Varyantları Backtest'i (2026-07-14)

Hepsi canlıdaki rejimli sizing (ayı %10/5, boğa %18/6) üzerine kurulu:
  V0 mevcut        : canlıdaki sistem (hafta içi kanal dokunuşunda gir, 4xATR)
  V1 kapanış onayı : haftalık mum kanalın ÜSTÜNDE KAPANMADAN girme (fakeout filtresi)
  V2 coin EMA40    : coin kendi haftalık EMA40'ının üstünde değilse girme
  V3 stop 2.5xATR  : ilk stop + trailing 2.5xATR (4 yerine)
  V4 zaman stopu   : 8 hafta geçti ve pozisyon kârda değilse kapat
  V5 V1+V2 kombo   : kapanış onayı + coin EMA40 birlikte

Veri/işleyiş donchian_regime_backtest.py ile birebir aynı (slippage + %0.1
komisyon, sinyaller kapanmış mumlardan). Amaç getiriden çok isabet oranı ve
MaxDD karşılaştırması.

Kullanım (container içinde):
  python tools/donchian_variant_backtest.py --capital 356
"""
import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt

BASE_DIR = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = BASE_DIR / 'data' / 'donchian_universe.json'

ENTRY_P, EXIT_P, ATR_P = 6, 2, 14
COMMISSION = 0.001
REGIME_EMA = 40
COIN_EMA = 40
TIME_STOP_WEEKS = 8
LARGE_CAP = {'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'SOL/USDT'}
MID_CAP = {'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT'}

REGIME_CFG = {'bear': (0.10, 5), 'bull': (0.18, 6)}

VARIANTS = {
    'V0 mevcut (4xATR)': {},
    'V1 kapanış onayı': {'close_confirm': True},
    'V2 coin EMA40': {'coin_ema': True},
    'V3 stop 2.5xATR': {'atr_mult': 2.5},
    'V4 zaman stopu 8h': {'time_stop': True},
    'V5 V1+V2 kombo': {'close_confirm': True, 'coin_ema': True},
}


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


def ema_series(closes, period):
    k = 2 / (period + 1)
    ema = closes[0]
    out = [ema]
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
        out.append(ema)
    return out


def prepare_coin(candles):
    """Bar i sinyalleri — hepsi ÖNCEKİ barlardan (shift 1, look-ahead yok):
       d_high/d_low: i-ENTRY_P..i-1 | prev_break: bar i-1 kanal üstünde KAPANDI mı
       ema_ok: kapanış[i-1] > EMA40[i-1]"""
    out = {}
    atrs = wilder_atr_series(candles)
    closes = [c[4] for c in candles]
    emas = ema_series(closes, COIN_EMA)
    start = max(ENTRY_P + 1, ATR_P + 1)
    for i in range(start, len(candles)):
        prev_channel = max(c[2] for c in candles[i - 1 - ENTRY_P:i - 1])
        out[candles[i][0]] = {
            'open': candles[i][1], 'high': candles[i][2],
            'low': candles[i][3], 'close': candles[i][4],
            'd_high': max(c[2] for c in candles[i - ENTRY_P:i]),
            'd_low': min(c[3] for c in candles[i - EXIT_P:i]),
            'atr': atrs[i],
            'prev_break': closes[i - 1] >= prev_channel,
            'ema_ok': i - 1 >= COIN_EMA and closes[i - 1] > emas[i - 1],
        }
    return out


def btc_regime_map(btc_candles):
    closes = [c[4] for c in btc_candles]
    emas = ema_series(closes, REGIME_EMA)
    regime = {}
    for i in range(1, len(btc_candles)):
        warm = i - 1 >= REGIME_EMA
        regime[btc_candles[i][0]] = 'bull' if warm and closes[i - 1] > emas[i - 1] else 'bear'
    return regime


def simulate(coin_data, regime_map, variant, start_ts, initial_cash):
    atr_mult = variant.get('atr_mult', 4.0)
    close_confirm = variant.get('close_confirm', False)
    coin_ema = variant.get('coin_ema', False)
    time_stop = variant.get('time_stop', False)

    timeline = sorted({ts for d in coin_data.values() for ts in d} | set(regime_map))
    timeline = [ts for ts in timeline if ts >= start_ts]
    cash, positions, trades = initial_cash, {}, []
    peak, max_dd = initial_cash, 0.0
    last_regime = 'bear'

    for ts in timeline:
        last_regime = regime_map.get(ts, last_regime)
        pct, max_pos = REGIME_CFG[last_regime]

        # çıkışlar
        for sym in list(positions):
            bar = coin_data.get(sym, {}).get(ts)
            if not bar:
                continue
            pos = positions[sym]
            pos['bars'] += 1
            slip = slippage(sym)
            exit_price = None
            if bar['low'] <= pos['stop']:
                exit_price = pos['stop'] * (1 - slip)
            elif bar['d_low'] > 0 and bar['low'] <= bar['d_low']:
                exit_price = bar['d_low'] * (1 - slip)
            elif time_stop and pos['bars'] >= TIME_STOP_WEEKS and bar['close'] <= pos['entry']:
                exit_price = bar['close'] * (1 - slip)
            if exit_price:
                revenue = pos['amount'] * exit_price * (1 - COMMISSION)
                cash += revenue
                trades.append(revenue - pos['cost'])
                del positions[sym]
            else:
                new_stop = bar['close'] - bar['atr'] * atr_mult
                if new_stop > pos['stop']:
                    pos['stop'] = new_stop

        # girişler
        for sym, data in coin_data.items():
            if sym in positions or len(positions) >= max_pos:
                continue
            bar = data.get(ts)
            if not bar or bar['atr'] <= 0 or bar['d_high'] <= 0:
                continue
            if coin_ema and not bar['ema_ok']:
                continue
            slip = slippage(sym)
            if close_confirm:
                # önceki hafta kanal üstünde kapandıysa bu haftanın açılışından gir
                if not bar['prev_break']:
                    continue
                entry = bar['open'] * (1 + slip)
            else:
                # canlı davranış: hafta içi kanala dokununca gir
                if bar['high'] < bar['d_high']:
                    continue
                entry = bar['d_high'] * (1 + slip)
            value = cash * pct
            if value < 5 or value > cash:
                continue
            cash -= value * (1 + COMMISSION)
            positions[sym] = {
                'amount': value / entry, 'entry': entry,
                'stop': entry - bar['atr'] * atr_mult,
                'cost': value * (1 + COMMISSION), 'bars': 0,
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

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    return {
        'final': cash, 'ret': (cash / initial_cash - 1) * 100,
        'max_dd': max_dd, 'n_trades': len(trades),
        'wr': len(wins) / len(trades) * 100 if trades else 0,
        'avg_win': sum(wins) / len(wins) if wins else 0,
        'avg_loss': sum(losses) / len(losses) if losses else 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capital', type=float, default=356.0)
    args = parser.parse_args()

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
    print(f'  Rejim haritası: {bull_weeks}/{len(regime_map)} hafta boğa\n')

    now = datetime.now(timezone.utc)
    windows = {'Son 12 ay': 12, 'Son 2 yıl': 24, 'Son 4 yıl': 48}

    for wname, months in windows.items():
        start_ts = int((now - timedelta(days=months * 30)).timestamp() * 1000)
        print(f'═══ {wname} ═══')
        print(f'{"Varyant":20} {"Getiri":>9} {"MaxDD":>8} {"İşlem":>6} {"WR":>6} '
              f'{"OrtK":>8} {"OrtZ":>8}')
        for vname, variant in VARIANTS.items():
            r = simulate(coin_data, regime_map, variant, start_ts, args.capital)
            print(f'{vname:20} {r["ret"]:>+8.2f}% {r["max_dd"]:>7.2f}% '
                  f'{r["n_trades"]:>6} {r["wr"]:>5.1f}% '
                  f'${r["avg_win"]:>+7.2f} ${r["avg_loss"]:>+7.2f}')
        print()


if __name__ == '__main__':
    main()
