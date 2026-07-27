"""
Donchian Weekly 6/2 ATR=4 — Canlı Bot (self-contained)

Strateji (tools/donchian_live_simulation.py backtest'iyle birebir):
  - Evren: data/donchian_universe.json (34 coin)
  - GİRİŞ: fiyat >= son 6 KAPANMIŞ haftalık mumun en yükseği
  - STOP:  giriş - 4 x ATR(14, haftalık, RMA)
  - TRAILING: her kapanmış hafta sonunda stop = max(stop, haftalık kapanış - 4xATR)
  - ÇIKIŞ: fiyat <= stop  VEYA  fiyat <= son 2 kapanmış haftanın en düşüğü
  - Pozisyon boyutu: serbest USDT'nin %10'u, max 5 eşzamanlı pozisyon

Güvenlik:
  - --live bayrağı olmadan EMİR GÖNDERMEZ (sadece loglar) → yerelde kazara canlı yok
  - Her emirde min-notional + precision kontrolü, satışta gerçek bakiye baz alınır
  - State her değişiklikte diske yazılır (restart-safe)
"""
import argparse
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from datetime import timedelta

TR_TZ = timezone(timedelta(hours=3))  # Türkiye saati (UTC+3)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('donchian')

BASE_DIR = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = BASE_DIR / 'data' / 'donchian_universe.json'
STATE_PATH = BASE_DIR / 'data' / 'live_state' / 'donchian_state.json'

ENTRY_P = 6          # haftalık giriş kanalı
EXIT_P = 2           # haftalık çıkış kanalı
ATR_P = 14
ATR_MULT = 4.0
MIN_ORDER_USDT = 10.0   # minNotional $5'in güvenli üstü
CHECK_INTERVAL = 3600   # saniye — haftalık sistem için saatlik tarama fazlasıyla yeterli

# Rejim-bazlı sizing (tools/donchian_regime_backtest.py ile doğrulandı, 2026-07-04):
# rejim = BTC haftalık kapanış vs EMA40(haftalık) ≈ günlük EMA200 trend filtresi
# 4 yıl: rejimli +103% vs sabit %10 +74% | ayıda sabit %10 ile aynı davranır
REGIME_EMA = 40
SIZING = {
    'bear': {'pct': 0.10, 'max_pos': 5},
    'bull': {'pct': 0.25, 'max_pos': 8},  # 2026-07-27: sizing süpürmesi → tam döngüde en iyi (+176% vs +138%)
}


# ---------------------------------------------------------------- telegram
class Telegram:
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        self.enabled = bool(self.token and self.chat_id)

    def send(self, text):
        if not self.enabled:
            return
        try:
            url = f'https://api.telegram.org/bot{self.token}/sendMessage'
            data = urllib.parse.urlencode({'chat_id': self.chat_id, 'text': text}).encode()
            urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
        except Exception as e:
            logger.warning(f'Telegram gönderilemedi: {e}')


# ---------------------------------------------------------------- indicators
def wilder_atr(candles, period=ATR_P):
    """candles: kapanmış haftalık OHLCV listesi [[ts,o,h,l,c,v],...] → RMA ATR"""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h, l = candles[i][2], candles[i][3]
        prev_c = candles[i - 1][4]
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def compute_signals(candles):
    """candles: Binance 1w OHLCV (son eleman kapanmamış mevcut hafta).
    Kapanmış mumlardan donchian_high/low, ATR ve son kapanış döner."""
    closed = candles[:-1]
    if len(closed) < max(ENTRY_P, ATR_P + 1):
        return None
    d_high = max(c[2] for c in closed[-ENTRY_P:])
    d_low = min(c[3] for c in closed[-EXIT_P:])
    atr = wilder_atr(closed)
    return {
        'donchian_high': d_high,
        'donchian_low': d_low,
        'atr': atr,
        'last_closed_ts': closed[-1][0],
        'last_closed_close': closed[-1][4],
    }


# ---------------------------------------------------------------- bot
class DonchianLiveBot:
    def __init__(self, live: bool):
        self.live = live
        self.tg = Telegram()
        self.exchange = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY', ''),
            'secret': os.getenv('BINANCE_API_SECRET', ''),
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        self.exchange.load_markets()

        with open(UNIVERSE_PATH) as f:
            self.universe = json.load(f)['coins']
        # Binance'te spot marketi olmayanları ele
        self.universe = [s for s in self.universe if s in self.exchange.markets
                         and self.exchange.markets[s].get('active', True)]

        self.state = self._load_state()
        logger.info(f'Universe: {len(self.universe)} coin | mod: '
                    f'{"CANLI 🔴" if live else "DRY-RUN (emir yok)"}')

    # ------------------------------------------------ state
    def _load_state(self):
        if STATE_PATH.exists():
            with open(STATE_PATH) as f:
                st = json.load(f)
            logger.info(f'State yüklendi: {len(st.get("positions", {}))} açık pozisyon')
            return st
        return {'positions': {}, 'closed_trades': []}

    def _save_state(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix('.tmp')
        with open(tmp, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)
        tmp.replace(STATE_PATH)

    # ------------------------------------------------ exchange helpers
    def _free(self, currency):
        bal = self.exchange.fetch_balance()
        return float(bal.get(currency, {}).get('free', 0) or 0)

    def _prep_amount(self, symbol, amount, price):
        """Precision + LOT_SIZE + minNotional kontrolü. Geçemezse 0 döner."""
        market = self.exchange.markets[symbol]
        amount = float(self.exchange.amount_to_precision(symbol, amount))
        min_amt = (market['limits'].get('amount') or {}).get('min') or 0
        min_cost = (market['limits'].get('cost') or {}).get('min') or 5.0
        if amount <= 0 or amount < min_amt:
            logger.warning(f'[{symbol}] miktar min lot altında: {amount}')
            return 0.0
        if price <= 0 or amount * price < min_cost:
            logger.warning(f'[{symbol}] notional ${amount * price:.2f} < min ${min_cost}')
            return 0.0
        return amount

    def _ticker_price(self, symbol):
        return float(self.exchange.fetch_ticker(symbol)['last'])

    # ------------------------------------------------ orders
    def _buy(self, symbol, spend_usdt, price):
        amount = self._prep_amount(symbol, spend_usdt / price, price)
        if amount <= 0:
            return None
        if not self.live:
            logger.info(f'[DRY] BUY {symbol} {amount} @ ~${price}')
            return {'amount': amount, 'price': price, 'cost': amount * price}
        order = self.exchange.create_market_buy_order(symbol, amount)
        filled = float(order.get('filled') or amount)
        avg = float(order.get('average') or price)
        cost = float(order.get('cost') or filled * avg)
        return {'amount': filled, 'price': avg, 'cost': cost}

    def _sell(self, symbol, amount, price):
        base = symbol.split('/')[0]
        if self.live:
            free = self._free(base)
            amount = min(amount, free)
        amount = self._prep_amount(symbol, amount, price)
        if amount <= 0:
            return None
        if not self.live:
            logger.info(f'[DRY] SELL {symbol} {amount} @ ~${price}')
            return {'amount': amount, 'price': price, 'revenue': amount * price}
        order = self.exchange.create_market_sell_order(symbol, amount)
        filled = float(order.get('filled') or amount)
        avg = float(order.get('average') or price)
        revenue = float(order.get('cost') or filled * avg)
        return {'amount': filled, 'price': avg, 'revenue': revenue}

    # ------------------------------------------------ regime
    def _detect_regime(self):
        """BTC haftalık kapanış (kapanmış hafta) EMA40 üstünde → bull, altında → bear."""
        candles = self.exchange.fetch_ohlcv('BTC/USDT', '1w', limit=300)
        closes = [c[4] for c in candles[:-1]]  # kapanmamış haftayı atla
        if len(closes) < REGIME_EMA + 10:
            return 'bear'
        k = 2 / (REGIME_EMA + 1)
        ema = closes[0]
        for c in closes[1:]:
            ema = c * k + ema * (1 - k)
        return 'bull' if closes[-1] > ema else 'bear'

    # ------------------------------------------------ core loop
    def scan_once(self):
        positions = self.state['positions']
        free_usdt = self._free('USDT') if self.live else 1000.0

        try:
            regime = self._detect_regime()
        except Exception as e:
            logger.warning(f'Rejim tespiti başarısız, bear varsayılıyor: {e}')
            regime = 'bear'
        pct, max_pos = SIZING[regime]['pct'], SIZING[regime]['max_pos']

        if regime != self.state.get('regime'):
            msg = (f'🌗 Rejim değişti: {self.state.get("regime", "?")} → {regime} '
                   f'| pozisyon %{pct*100:.0f}, max {max_pos}')
            logger.info(msg)
            self.tg.send(msg)
            self.state['regime'] = regime
            self._save_state()

        # 1) ÇIKIŞLAR + trailing
        for symbol in list(positions.keys()):
            try:
                self._check_exit(symbol)
            except Exception as e:
                logger.error(f'[{symbol}] exit check hatası: {e}')

        # 2) GİRİŞLER
        for symbol in self.universe:
            if symbol in positions:
                continue
            if len(positions) >= max_pos:
                break
            try:
                self._check_entry(symbol, free_usdt, pct)
                if symbol in positions:  # girdi olduysa cash güncelle
                    free_usdt = self._free('USDT') if self.live else free_usdt * (1 - pct)
            except Exception as e:
                logger.error(f'[{symbol}] entry check hatası: {e}')
            time.sleep(0.2)  # rate limit nefesi

        logger.info(f'Tarama bitti | rejim: {regime} | açık pozisyon: '
                    f'{len(positions)}/{max_pos} | serbest USDT: ${free_usdt:.2f}')

    def _check_exit(self, symbol):
        pos = self.state['positions'][symbol]
        candles = self.exchange.fetch_ohlcv(symbol, '1w', limit=ATR_P + ENTRY_P + 5)
        sig = compute_signals(candles)
        if sig is None:
            return
        price = self._ticker_price(symbol)

        # Trailing: kapanmış son haftanın kapanışına göre (haftada 1 etkili, idempotent)
        new_stop = sig['last_closed_close'] - sig['atr'] * ATR_MULT
        if new_stop > pos['stop']:
            logger.info(f'[{symbol}] trailing stop {pos["stop"]:.6f} → {new_stop:.6f}')
            pos['stop'] = new_stop
            self._save_state()

        reason = None
        if price <= pos['stop']:
            reason = 'SL/trailing'
        elif sig['donchian_low'] > 0 and price <= sig['donchian_low']:
            reason = 'donchian-low'
        if not reason:
            return

        result = self._sell(symbol, pos['amount'], price)
        if result is None:
            logger.error(f'[{symbol}] SATIŞ GEREKLİ ({reason}) ama emir hazırlanamadı!')
            self.tg.send(f'⚠️ Donchian: {symbol} satılamadı ({reason}) — manuel kontrol et')
            return
        pnl = result['revenue'] * (1 - 0.001) - pos['cost']
        self.state['closed_trades'].append({
            'symbol': symbol, 'entry': pos['entry'], 'exit': result['price'],
            'amount': result['amount'], 'pnl': pnl, 'reason': reason,
            'opened_at': pos['opened_at'], 'closed_at': datetime.now(timezone.utc).isoformat(),
        })
        del self.state['positions'][symbol]
        self._save_state()
        msg = (f'🐢 Donchian SAT {symbol} ({reason})\n'
               f'{pos["entry"]:.6f} → {result["price"]:.6f}\n'
               f'PnL: ${pnl:+.2f}')
        logger.info(msg.replace('\n', ' | '))
        self.tg.send(msg)

    def _check_entry(self, symbol, free_usdt, position_pct):
        candles = self.exchange.fetch_ohlcv(symbol, '1w', limit=ATR_P + ENTRY_P + 5)
        sig = compute_signals(candles)
        if sig is None or sig['atr'] <= 0:
            return
        price = self._ticker_price(symbol)
        if price < sig['donchian_high']:
            return

        spend = free_usdt * position_pct
        if spend < MIN_ORDER_USDT:
            logger.info(f'[{symbol}] sinyal var ama sermaye yetersiz (${spend:.2f})')
            return

        result = self._buy(symbol, spend, price)
        if result is None:
            return
        stop = result['price'] - sig['atr'] * ATR_MULT
        self.state['positions'][symbol] = {
            'entry': result['price'],
            'amount': result['amount'],
            'stop': stop,
            'cost': result['cost'],
            'opened_at': datetime.now(timezone.utc).isoformat(),
        }
        self._save_state()
        msg = (f'🐢 Donchian AL {symbol}\n'
               f'Fiyat: {result["price"]:.6f} | Tutar: ${result["cost"]:.2f}\n'
               f'Stop: {stop:.6f} (-{ATR_MULT}xATR)\n'
               f'6h kanal: {sig["donchian_high"]:.6f}')
        logger.info(msg.replace('\n', ' | '))
        self.tg.send(msg)

    # ------------------------------------------------ daily report
    def _daily_report(self):
        """Her gün ilk taramada (00:00 TR sonrası) bakiye + pozisyon + PnL raporu."""
        free_usdt = self._free('USDT') if self.live else 0.0
        pos_lines, pos_value = [], 0.0
        for sym, pos in self.state['positions'].items():
            try:
                price = self._ticker_price(sym)
            except Exception:
                price = pos['entry']
            val = pos['amount'] * price
            pos_value += val
            pnl_usd = val - pos['cost']
            pnl_pct = (price / pos['entry'] - 1) * 100
            pos_lines.append(
                f'• {sym}: giriş {pos["entry"]:.6f} → şimdi {price:.6f}\n'
                f'  ${val:.2f} ({pnl_usd:+.2f}$ / {pnl_pct:+.1f}%) | stop {pos["stop"]:.6f}'
            )

        equity = free_usdt + pos_value
        baseline = self.state.setdefault('baseline_equity', equity)
        total_usd = equity - baseline
        total_pct = (equity / baseline - 1) * 100 if baseline else 0.0
        closed = self.state['closed_trades']
        realized = sum(t['pnl'] for t in closed)

        msg = (f'📊 Donchian günlük rapor — {datetime.now(TR_TZ).strftime("%d.%m.%Y %H:%M")}\n'
               f'━━━━━━━━━━━━━━━\n'
               f'💰 Toplam değer: ${equity:.2f} ({total_usd:+.2f}$ / {total_pct:+.2f}% başlangıçtan)\n'
               f'💵 Serbest USDT: ${free_usdt:.2f}\n'
               f'🌗 Rejim: {self.state.get("regime", "?")}\n'
               f'📈 Açık pozisyon: {len(self.state["positions"])}\n'
               + ('\n'.join(pos_lines) + '\n' if pos_lines else '')
               + f'✅ Gerçekleşen PnL: ${realized:+.2f} ({len(closed)} kapanmış işlem)')
        self.tg.send(msg)
        logger.info('Günlük rapor gönderildi')

    def _dust_sweep(self):
        """Haftalık: $5 altı kırıntıları BNB'ye çevir (komisyon deposunu doldurur).

        Binance'in "çevrilebilir" listesi $30+ bakiyeleri de içerebiliyor;
        açık pozisyon coinleri ve $5 üstü bakiyeler asla süpürülmez
        (2026-07-13'te PROM+UNI pozisyonları yanlışlıkla süpürüldü).
        """
        held = {sym.split('/')[0] for sym in self.state['positions']}
        btc_usdt = self._ticker_price('BTC/USDT')
        info = self.exchange.sapiPostAssetDustBtc()
        assets = [d['asset'] for d in info.get('details', [])
                  if d['asset'] != 'BNB'
                  and d['asset'] not in held
                  and float(d.get('toBTC', 0)) * btc_usdt < 5.0]
        if not assets:
            return
        result = self.exchange.sapiPostAssetDust({'asset': assets})
        total = result.get('totalTransfered', '?')
        msg = f'🧹 Dust süpürüldü: {", ".join(assets)} → {total} BNB'
        logger.info(msg)
        self.tg.send(msg)

    def run(self):
        mode = 'CANLI 🔴' if self.live else 'DRY-RUN'
        self.tg.send(f'🐢 Donchian Weekly bot başladı ({mode}) — '
                     f'{len(self.universe)} coin, rejim-bazlı sizing '
                     f'(ayı %10/5, boğa %25/8)')
        while True:
            try:
                self.scan_once()
            except Exception as e:
                logger.error(f'Tarama hatası: {e}')
                self.tg.send(f'❌ Donchian tarama hatası: {e}')

            today = datetime.now(TR_TZ).strftime('%Y-%m-%d')
            if self.state.get('last_report_day') != today:
                try:
                    self._daily_report()
                    self.state['last_report_day'] = today
                    self._save_state()
                except Exception as e:
                    logger.error(f'Günlük rapor hatası: {e}')
                # Pazartesi geceleri kırıntı süpürme (canlı modda)
                if self.live and datetime.now(TR_TZ).weekday() == 0:
                    try:
                        self._dust_sweep()
                    except Exception as e:
                        logger.warning(f'Dust sweep başarısız: {e}')

            # Bir sonraki tam saate hizalan → gece yarısı taraması tam 00:00'da olur
            time.sleep(CHECK_INTERVAL - time.time() % CHECK_INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true',
                        help='Gerçek emir gönder (yoksa dry-run)')
    parser.add_argument('--once', action='store_true', help='Tek tarama yap ve çık')
    args = parser.parse_args()

    bot = DonchianLiveBot(live=args.live)
    if args.once:
        bot.scan_once()
    else:
        bot.run()


if __name__ == '__main__':
    main()
