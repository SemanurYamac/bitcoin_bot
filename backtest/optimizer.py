"""
Hızlı Parametre Optimizasyonu — 2 Aşamalı Yaklaşım
$1,000 ile son 4 ayda maksimum getiriyi bul.

Hız optimizasyonu:
  - Aşama 1: Her (buy_threshold, adx_threshold) kombinasyonu için sinyalleri
    önceden hesapla. 252 senaryo için sadece 12 farklı sinyal seti var.
  - Aşama 2: Risk/ATR parametrelerini bu önceden hesaplı sinyaller üzerinde
    hızlı simüle et. Sinyal üretimi tekrar edilmez.

Sonuç: ~100 dakika → ~5-10 dakika
"""
import logging
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config.settings as settings
import strategy.signals as signals_mod
import backtest.engine as engine_mod
from data.collector import DataCollector
from analysis.indicators import TechnicalIndicators
from strategy.signals import SignalGenerator
from config.settings import EMA_LONG

logging.basicConfig(level=logging.WARNING, format='%(asctime)s | %(levelname)-8s | %(message)s')
logger = logging.getLogger('optimizer')
logger.setLevel(logging.INFO)

# ─── Sabit Test Parametreleri ─────────────────────────────────────────
TEST_COINS = ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'BNB/USDT', 'ADA/USDT', 'DOT/USDT']
INITIAL_BALANCE = 1000
START_DATE = '2026-01-01'
END_DATE = '2026-05-06'
TIMEFRAME = '15m'

# ─── Parametre Alanı (15m Scalping) ──────────────────────────────────
# Sinyal parametreleri (önceden hesaplama — sadece 12 kombinasyon)
SIGNAL_PARAMS = {
    'buy_threshold': [4.5, 5.0, 5.5, 6.0],
    'adx_threshold': [15, 20, 25],
}

# Risk parametreleri (sinyal üretimini ETKİLEMEZ — hızlı simülasyon)
RISK_PARAMS = {
    'atr_sl_mult':        [0.8, 1.0, 1.5, 2.0],
    'atr_tp2_mult':       [2.0, 3.0, 4.0, 5.0],
    'risk_per_trade':     [0.05, 0.10, 0.15],
    'trailing_activation': [0.008, 0.012, 0.015],
}

FEE_RATE = 0.001  # %0.1 Binance taker fee


def pregenerate_signals(df, buy_threshold, adx_threshold):
    """
    Verilen parametrelerle tüm mumlar için sinyal üretir.
    Returns: list of 'BUY'/'SELL'/'HOLD' strings, start_idx
    """
    settings.BUY_THRESHOLD = buy_threshold
    signals_mod.BUY_THRESHOLD = buy_threshold
    settings.ADX_THRESHOLD = adx_threshold
    signals_mod.ADX_THRESHOLD = adx_threshold

    sg = SignalGenerator()
    start_idx = max(EMA_LONG + 10, 201)
    signals = ['HOLD'] * len(df)

    for i in range(start_idx, len(df)):
        try:
            result = sg.generate_signal(df, index=i)
            signals[i] = result['signal']
        except Exception:
            signals[i] = 'HOLD'

    return signals, start_idx


def fast_simulate(df, signals, start_idx, params):
    """
    Önceden hesaplanmış sinyaller kullanarak hızlı pozisyon simülasyonu.
    Sinyal üretimi yok — sadece giriş/çıkış mantığı.
    """
    atr_sl   = params['atr_sl_mult']
    atr_tp2  = params['atr_tp2_mult']
    atr_tp1  = atr_tp2 * 0.5   # TP1 = TP2'nin yarısı
    risk     = params['risk_per_trade']
    trail_act = params['trailing_activation']
    atr_trail = 1.0  # Sabit trailing mesafe çarpanı

    # Partial TP ayarları
    partial_tp_pct  = 0.50   # %50 kapat
    move_sl_to_be   = True
    max_pos_pct     = 0.99

    closes = df['close'].values
    highs  = df['high'].values
    lows   = df['low'].values
    atrs   = df['atr'].values if 'atr' in df.columns else np.full(len(df), np.nan)

    balance      = float(INITIAL_BALANCE)
    coin_holding = 0.0
    active_pos   = None
    trades       = []
    wins = losses = 0

    for i in range(start_idx, len(df)):
        price = closes[i]
        atr   = atrs[i] if not np.isnan(atrs[i]) else None

        if active_pos is not None:
            # Trailing stop güncelle
            if price > active_pos['highest']:
                active_pos['highest'] = price
                if atr and atr > 0:
                    mult = atr_trail * (0.75 if active_pos['partial_done'] else 1.0)
                    new_trail = price - atr * mult
                else:
                    new_trail = price * 0.985
                if active_pos['trail'] is None or new_trail > active_pos['trail']:
                    active_pos['trail'] = new_trail
                if active_pos['trail'] and active_pos['trail'] > active_pos['sl']:
                    active_pos['sl'] = active_pos['trail']

            # Partial TP
            if not active_pos['partial_done'] and price >= active_pos['partial_tp']:
                close_amt = active_pos['amt'] * partial_tp_pct
                fee = (active_pos['entry'] * close_amt + price * close_amt) * FEE_RATE
                pnl = (price - active_pos['entry']) * close_amt - fee
                balance += price * close_amt - fee
                coin_holding -= close_amt
                active_pos['amt'] -= close_amt
                active_pos['partial_done'] = True
                if move_sl_to_be:
                    active_pos['sl'] = active_pos['entry']
                trades.append(pnl)

            # Çıkış kontrolü
            exit_price = None
            if price <= active_pos['sl']:
                exit_price = active_pos['sl']
            elif price >= active_pos['tp']:
                exit_price = active_pos['tp']
            elif (active_pos['trail'] is not None
                  and price <= active_pos['trail']
                  and active_pos['highest'] >= active_pos['entry'] * (1 + trail_act)):
                exit_price = active_pos['trail']

            if exit_price is not None:
                amt = active_pos['amt']
                fee = (active_pos['entry'] * amt + exit_price * amt) * FEE_RATE
                pnl = (exit_price - active_pos['entry']) * amt - fee
                balance += exit_price * amt - fee
                coin_holding = max(coin_holding - amt, 0.0)
                trades.append(pnl)
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                active_pos = None
            continue

        # Sinyal kontrolü
        if signals[i] == 'BUY' and balance > 5 and atr and atr > 0:
            sl_dist   = atr * atr_sl
            tp2_dist  = atr * atr_tp2
            tp1_dist  = atr * atr_tp1
            stop_pct  = min(sl_dist / price, 0.10)
            stop_pct  = max(stop_pct, 0.005)

            risk_amt  = balance * risk
            pos_val   = min(risk_amt / stop_pct, balance * max_pos_pct)
            pos_val   = max(pos_val, 5.0)
            if pos_val > balance:
                pos_val = balance * max_pos_pct

            amt  = pos_val / price
            fee  = pos_val * FEE_RATE
            if balance < pos_val + fee:
                continue

            balance      -= (pos_val + fee)
            coin_holding += amt

            active_pos = {
                'entry':        price,
                'amt':          amt,
                'sl':           price - sl_dist,
                'tp':           price + tp2_dist,
                'partial_tp':   price + tp1_dist,
                'partial_done': False,
                'highest':      price,
                'trail':        None,
            }

    # Açık pozisyonu kapat
    if active_pos is not None:
        price = closes[-1]
        amt   = active_pos['amt']
        fee   = (active_pos['entry'] * amt + price * amt) * FEE_RATE
        pnl   = (price - active_pos['entry']) * amt - fee
        balance += price * amt - fee
        trades.append(pnl)
        if pnl > 0:
            wins += 1
        else:
            losses += 1

    total_trades = wins + losses
    win_rate     = wins / total_trades * 100 if total_trades > 0 else 0
    total_return = (balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100

    return {
        'final_balance':   round(balance, 2),
        'total_return':    round(total_return, 2),
        'total_trades':    total_trades,
        'win_rate':        round(win_rate, 1),
    }


def main():
    print("=" * 70)
    print("⚡ HIZLI PARAMETRE OPTİMİZASYONU (2 Aşamalı)")
    print(f"📅 Dönem: {START_DATE} → {END_DATE} (Son 4 Ay)")
    print(f"💰 Başlangıç: ${INITIAL_BALANCE:,}")
    print(f"⏱  Timeframe: {TIMEFRAME}")
    print(f"🪙 Coinler: {len(TEST_COINS)}")
    print("=" * 70)

    # ── 1. Veri çek + indikatörleri hesapla ──────────────────────────
    print("\n📥 Veriler çekiliyor ve indikatörler hesaplanıyor...")
    collector = DataCollector()
    coin_data = {}

    for symbol in TEST_COINS:
        try:
            df_raw = collector.fetch_historical_data(symbol, TIMEFRAME, START_DATE, END_DATE)
            if not df_raw.empty and len(df_raw) > 200:
                df = TechnicalIndicators.calculate_all(df_raw)
                coin_data[symbol] = df
                print(f"  ✅ {symbol}: {len(df)} mum")
            else:
                print(f"  ⚠️ {symbol}: Yetersiz veri")
        except Exception as e:
            print(f"  ❌ {symbol}: {e}")

    if not coin_data:
        print("Veri alınamadı!")
        return

    # ── 2. Sinyal kombinasyonlarını önceden hesapla ───────────────────
    signal_combos = [
        (bt, adx)
        for bt  in SIGNAL_PARAMS['buy_threshold']
        for adx in SIGNAL_PARAMS['adx_threshold']
    ]
    total_risk_combos = (
        len(RISK_PARAMS['atr_sl_mult'])
        * len(RISK_PARAMS['atr_tp2_mult'])
        * len(RISK_PARAMS['risk_per_trade'])
        * len(RISK_PARAMS['trailing_activation'])
    )
    total_scenarios = len(signal_combos) * total_risk_combos
    print(f"\n🧠 Sinyal kombinasyonu: {len(signal_combos)} (önceden hesaplanıyor)")
    print(f"⚙️  Risk kombinasyonu: {total_risk_combos}")
    print(f"🧪 Toplam senaryo: {total_scenarios:,}")
    print()

    # Sinyal önbelleği: {(symbol, buy_th, adx): signals_list}
    print("⏳ Sinyaller önceden hesaplanıyor...")
    signal_cache = {}
    start_idx_cache = {}

    for symbol, df in coin_data.items():
        for buy_th, adx in signal_combos:
            key = (symbol, buy_th, adx)
            sigs, sidx = pregenerate_signals(df, buy_th, adx)
            signal_cache[key]    = sigs
            start_idx_cache[key] = sidx

    # Threshold'ları geri al (son değerler kalmasın)
    settings.BUY_THRESHOLD = 7.0
    signals_mod.BUY_THRESHOLD = 7.0
    settings.ADX_THRESHOLD = 25
    signals_mod.ADX_THRESHOLD = 25

    print(f"  ✅ {len(signal_cache)} sinyal seti hazır.\n")

    # ── 3. Risk parametre grid'i üzerinde hızlı simülasyon ───────────
    print("🚀 Risk parametre simülasyonu başlıyor...")
    results = []
    t0 = time.time()
    done = 0

    for bt in SIGNAL_PARAMS['buy_threshold']:
        for adx in SIGNAL_PARAMS['adx_threshold']:
            for sl in RISK_PARAMS['atr_sl_mult']:
                for tp2 in RISK_PARAMS['atr_tp2_mult']:
                    if tp2 / sl < 2.0:
                        continue
                    for risk in RISK_PARAMS['risk_per_trade']:
                        for trail in RISK_PARAMS['trailing_activation']:
                            params = {
                                'buy_threshold':     bt,
                                'adx_threshold':     adx,
                                'atr_sl_mult':       sl,
                                'atr_tp2_mult':      tp2,
                                'risk_per_trade':    risk,
                                'trailing_activation': trail,
                            }

                            total_ret = 0
                            total_trades = 0
                            total_wins = 0
                            coin_rets = {}
                            valid = 0

                            for symbol, df in coin_data.items():
                                key = (symbol, bt, adx)
                                sigs  = signal_cache[key]
                                sidx  = start_idx_cache[key]
                                res   = fast_simulate(df, sigs, sidx, params)
                                coin_rets[symbol] = res['total_return']
                                total_ret    += res['total_return']
                                total_trades += res['total_trades']
                                total_wins   += int(res['win_rate'] * res['total_trades'] / 100)
                                valid += 1

                            if valid == 0:
                                continue

                            avg_ret  = total_ret / valid
                            tot_loss = total_trades - total_wins
                            wr       = total_wins / total_trades * 100 if total_trades > 0 else 0

                            results.append({
                                'avg_return':   round(avg_ret, 2),
                                'total_trades': total_trades,
                                'win_rate':     round(wr, 1),
                                'coin_results': coin_rets,
                                'params':       params,
                            })
                            done += 1

    elapsed = time.time() - t0
    print(f"✅ {done} senaryo test edildi — {elapsed:.1f} saniyede\n")

    # ── 4. Sonuçları sırala ve göster ────────────────────────────────
    results.sort(key=lambda x: x['avg_return'], reverse=True)

    print("=" * 70)
    print("🏆 EN İYİ 15 PARAMETRE KOMBİNASYONU")
    print("=" * 70)

    for rank, r in enumerate(results[:15], 1):
        p = r['params']
        final = INITIAL_BALANCE * (1 + r['avg_return'] / 100)
        print(f"\n{'─' * 60}")
        print(
            f"#{rank} | Ort.Getiri: {r['avg_return']:+.2f}% | "
            f"$1,000 → ${final:,.0f} | "
            f"Win: {r['win_rate']:.0f}% | "
            f"İşlem: {r['total_trades']}"
        )
        print(
            f"   BUY≥{p['buy_threshold']} | ADX≥{p['adx_threshold']} | "
            f"SL={p['atr_sl_mult']}× | TP={p['atr_tp2_mult']}× | "
            f"Risk={int(p['risk_per_trade']*100)}% | Trail={p['trailing_activation']}"
        )
        sorted_coins = sorted(r['coin_results'].items(), key=lambda x: x[1], reverse=True)
        pos = [f"{s.split('/')[0]}:{v:+.1f}%" for s, v in sorted_coins if v > 0]
        neg = [f"{s.split('/')[0]}:{v:+.1f}%" for s, v in sorted_coins if v <= 0]
        if pos:
            print(f"   ✅ {', '.join(pos)}")
        if neg:
            print(f"   ❌ {', '.join(neg)}")

    # ── 5. En iyi sonucu özetle ───────────────────────────────────────
    if results:
        best = results[0]
        final = INITIAL_BALANCE * (1 + best['avg_return'] / 100)
        print(f"\n{'=' * 70}")
        print("🥇 EN İYİ SONUÇ")
        print(f"{'=' * 70}")
        print(f"  💰 $1,000 → ${final:,.0f}  ({best['avg_return']:+.2f}%)")
        print(f"  📊 {best['total_trades']} işlem | Win Rate: {best['win_rate']:.0f}%")
        print(f"  ⚙️  Parametreler:")
        for k, v in best['params'].items():
            print(f"     {k}: {v}")

        if best['avg_return'] >= 50:
            print(f"\n🎉 GÜÇLÜ SONUÇ! $1,000 → ${final:,.0f}")
        elif best['avg_return'] > 0:
            print(f"\n✅ Pozitif getiri: {best['avg_return']:+.2f}%")
        else:
            print(f"\n⚠️  Tüm senaryolar negatif — strateji revizyonu gerekebilir.")
        print(f"{'=' * 70}")

    return results


if __name__ == '__main__':
    main()
