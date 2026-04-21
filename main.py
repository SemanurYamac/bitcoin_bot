"""
Bitcoin & Altcoin Trading Bot - Ana Çalıştırma Dosyası (Faz 1)
Closed candle sinyal, rejim filtresi, risk-based sizing, fail-safe.
"""
import sys
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Proje kök dizinini path'e ekle
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import (
    TRADING_MODE, SYMBOL, SYMBOLS, TIMEFRAME,
    BACKTEST_START_DATE, BACKTEST_END_DATE, BACKTEST_INITIAL_BALANCE,
    LOG_FILE, LOG_LEVEL, MULTI_COIN_MODE, MIN_VOLUME_24H, MAX_OPEN_POSITIONS,
    SCAN_INTERVAL_MINUTES, POSITION_CHECK_INTERVAL,
    CLOSED_CANDLE_MODE, MAX_CONSECUTIVE_ERRORS, FAILSAFE_WAIT_SECONDS,
    MAX_PORTFOLIO_EXPOSURE
)
from data.collector import DataCollector
from data.storage import DataStorage
from analysis.indicators import TechnicalIndicators
from strategy.signals import SignalGenerator
from trading.risk_manager import RiskManager
from trading.state_manager import StateManager
from trading.executor import TradeExecutor
from backtest.engine import BacktestEngine
from backtest.hyperopt import HyperOptimizer
from notifications.notifier import TelegramNotifier


def setup_logging():
    """Loglama ayarlarını yapılandırır."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Windows'ta UTF-8 encoding zorla (emoji desteği için)
    import io
    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(utf8_stdout)
        ]
    )


def run_backtest(symbol=None, start_date=None, end_date=None,
                 initial_balance=None, verbose=True):
    """Backtesting çalıştırır (tek coin veya çoklu coin)."""
    logger = logging.getLogger('backtest')

    start = start_date or BACKTEST_START_DATE
    end = end_date or BACKTEST_END_DATE
    balance = initial_balance or BACKTEST_INITIAL_BALANCE

    collector = DataCollector()
    storage = DataStorage()

    if MULTI_COIN_MODE and symbol is None:
        symbols_to_test = SYMBOLS
    else:
        symbols_to_test = [symbol or SYMBOL]

    all_results = {}

    for sym in symbols_to_test:
        logger.info(f"\n{'='*60}")
        logger.info(f"📊 {sym} Backtesting başlatılıyor...")
        logger.info(f"{'='*60}")

        try:
            df = collector.fetch_historical_data(
                symbol=sym, start_date=start, end_date=end
            )

            if df.empty or len(df) < 300:
                logger.warning(f"⚠️ {sym} için yeterli veri yok, atlanıyor...")
                continue

            engine = BacktestEngine(initial_balance=balance)
            results = engine.run(df, verbose=verbose)
            results['symbol'] = sym
            all_results[sym] = results

        except Exception as e:
            logger.error(f"❌ {sym} backtesting hatası: {e}")
            continue

    if len(all_results) > 1:
        print("\n" + "=" * 70)
        print("📊 ÇOKLU COİN BACKTESTING ÖZET SONUÇLARI")
        print("=" * 70)
        print(f"{'Coin':<12} {'Getiri':>10} {'B&H':>10} {'İşlem':>8} {'Win%':>8} {'MaxDD':>8}")
        print("-" * 70)

        for sym, res in sorted(all_results.items(),
                               key=lambda x: x[1]['total_return_percent'],
                               reverse=True):
            print(f"{sym:<12} {res['total_return_percent']:>+9.2f}% "
                  f"{res['buy_and_hold_return']:>+9.2f}% "
                  f"{res['total_trades']:>8} "
                  f"{res['win_rate']:>7.1f}% "
                  f"{res['max_drawdown']:>7.2f}%")

        print("=" * 70)

    return all_results


def run_live_bot():
    """
    Canlı (veya paper) trading bot çalıştırır.
    Faz 1: Closed candle sinyal, rejim filtresi, risk-based sizing, fail-safe.
    """
    logger = logging.getLogger('live_bot')

    mode = TRADING_MODE
    if mode == 'backtest':
        logger.error("❌ Bu fonksiyon backtest modunda çalıştırılamaz!")
        return

    logger.info(f"🤖 Bot başlatılıyor... (Mod: {mode.upper()})")

    use_testnet = (mode == 'paper')
    collector = DataCollector(use_testnet=use_testnet)
    storage = DataStorage()
    signal_generator = SignalGenerator()
    notifier = TelegramNotifier()

    # Bağlantı testi
    if not collector.check_connection():
        logger.error("❌ Borsa bağlantısı kurulamadı!")
        notifier.send_error("Borsa bağlantısı kurulamadı!")
        return

    # Bakiye kontrolü
    balance_info = collector.fetch_balance()
    usdt_balance = balance_info.get('USDT', {}).get('free', 0)
    logger.info(f"💰 Mevcut bakiye: {usdt_balance:.2f} USDT")

    # Hangi coinleri tarayacağız
    symbols = SYMBOLS if MULTI_COIN_MODE else [SYMBOL]

    # Modüller ve State kurulumu
    executor = TradeExecutor(collector, storage)
    state_manager = StateManager()
    
    # Her coin için Risk Manager oluştur ve önceki durumları geri yükle
    risk_managers = {}
    for symbol in symbols:
        per_coin_balance = usdt_balance / MAX_OPEN_POSITIONS
        risk_managers[symbol] = RiskManager(symbol, per_coin_balance, state_manager)

    # Closed candle: her sembol için son işlenen mum timestamp'i
    last_processed_candle = {}  # {symbol: timestamp}

    # Fail-safe: ardışık hata sayacı
    consecutive_errors = 0

    # Telegram bildirimi
    notifier.send_bot_started()
    coin_list = ', '.join([s.split('/')[0] for s in symbols])
    notifier.send_message(
        f"📋 <b>Taranan coinler ({len(symbols)}):</b>\n"
        f"<code>{coin_list}</code>\n"
        f"🔧 Closed candle: {'AÇIK' if CLOSED_CANDLE_MODE else 'KAPALI'}\n"
        f"📊 Rejim filtresi: AÇIK"
    )

    logger.info(f"⏰ Bot çalışıyor - {len(symbols)} coin taranıyor")
    logger.info(f"📋 Coinler: {coin_list}")
    logger.info(f"🔧 Closed candle mode: {CLOSED_CANDLE_MODE}")

    scan_count = 0

    while True:
        try:
            scan_count += 1
            scan_results = []

            active_positions = sum(
                1 for rm in risk_managers.values()
                if rm.active_position is not None
            )

            # Toplam portföy maruziyeti hesapla
            total_exposure = sum(
                rm.active_position['entry_price'] * rm.active_position['amount']
                for rm in risk_managers.values()
                if rm.active_position is not None
            )

            logger.info(f"\n{'─'*50}")
            logger.info(f"🔄 TARAMA #{scan_count} başlıyor ({len(symbols)} coin)...")
            logger.info(f"📌 Aktif pozisyon: {active_positions}/{MAX_OPEN_POSITIONS}")
            logger.info(f"💼 Portföy maruziyeti: ${total_exposure:,.2f}")
            logger.info(f"{'─'*50}")

            new_candle_detected = False

            for symbol in symbols:
                try:
                    # ─── Veri Çek ───────────────────────────────
                    df = collector.fetch_ohlcv(symbol=symbol, limit=300)

                    if df.empty:
                        logger.warning(f"⚠️ {symbol} boş veri döndü")
                        scan_results.append({
                            'symbol': symbol, 'signal': 'SKIP',
                            'score': 0, 'price': 0
                        })
                        continue

                    # ─── Closed Candle Modu ─────────────────────
                    if CLOSED_CANDLE_MODE:
                        # Son mum (incomplete) hariç, bir önceki (closed) mumu kullan
                        last_candle_ts = df.index[-2]  # Son kapanmış mum
                        current_candle_ts = df.index[-1]  # Şu an açık mum

                        prev_ts = last_processed_candle.get(symbol)

                        if prev_ts is not None and last_candle_ts <= prev_ts:
                            # Aynı mum zaten işlendi — tekrar sinyal üretme
                            scan_results.append({
                                'symbol': symbol, 'signal': 'SKIP',
                                'score': 0, 'price': float(df['close'].iloc[-1]),
                                'reason': 'Aynı mum (bekleniyor)'
                            })
                            continue

                        # Yeni mum kapanmış! İşaretle
                        last_processed_candle[symbol] = last_candle_ts
                        new_candle_detected = True
                        logger.info(f"🕐 {symbol} yeni mum kapandı: {last_candle_ts}")

                        # Son satırı (incomplete candle) çıkar
                        df = df.iloc[:-1]

                    # Hacim filtresi
                    try:
                        ticker = collector.fetch_ticker(symbol)
                        volume_usd = ticker.get('volume', 0) * ticker.get('last', 0)
                        if volume_usd < MIN_VOLUME_24H:
                            logger.info(f"⏭ {symbol} düşük hacim (${volume_usd:,.0f} < ${MIN_VOLUME_24H:,.0f}), atlanıyor")
                            scan_results.append({
                                'symbol': symbol, 'signal': 'SKIP',
                                'score': 0, 'price': ticker.get('last', 0)
                            })
                            continue
                    except Exception:
                        pass

                    # ─── Göstergeleri Hesapla ───────────────────
                    df = TechnicalIndicators.calculate_all(df)
                    current_price = df['close'].iloc[-1]

                    if len(df) < 200:
                        logger.warning(f"⚠️ {symbol} yetersiz veri: {len(df)} mum (min 200)")
                        scan_results.append({
                            'symbol': symbol, 'signal': 'SKIP',
                            'score': 0, 'price': current_price
                        })
                        continue

                    # Risk manager
                    rm = risk_managers[symbol]

                    # Yeni mum kapandığında cooldown azalt
                    if CLOSED_CANDLE_MODE and new_candle_detected:
                        rm.decrement_cooldown()

                    # ─── Aktif Pozisyon Kontrolü ────────────────
                    if rm.active_position is not None:
                        should_exit, exit_reason = rm.check_exit_conditions(current_price)

                        if should_exit:
                            pos = rm.active_position
                            sell_result = executor.execute_sell(
                                symbol=symbol,
                                amount=pos['amount'],
                                price=None
                            )

                            close_result = rm.close_position(
                                sell_result.get('price', current_price)
                            )

                            if close_result:
                                close_result['symbol'] = symbol
                                notifier.send_position_closed(close_result)
                                logger.info(f"📌 {symbol} pozisyon kapatıldı: {exit_reason}")

                        scan_results.append({
                            'symbol': symbol, 'signal': 'POSITION',
                            'score': 0, 'price': current_price
                        })

                    else:
                        # ─── Sinyal Üret ───────────────────────
                        signal_result = signal_generator.generate_signal(df)

                        coin_name = symbol.split('/')[0]
                        regime = signal_result.get('score_breakdown', {}).get('Regime', '')
                        regime_short = '🐻' if 'BEARISH' in regime else '🐂'

                        logger.info(
                            f"📊 {coin_name:>5} | ${current_price:>10,.2f} | "
                            f"Skor: {signal_result['score']:>+6.1f} | "
                            f"{signal_result['signal']} {regime_short}"
                        )

                        scan_results.append({
                            'symbol': symbol,
                            'signal': signal_result['signal'],
                            'score': signal_result['score'],
                            'price': current_price,
                            'regime': regime_short,
                        })

                        if signal_result['signal'] == 'BUY':
                            signal_result['symbol'] = symbol
                            notifier.send_signal(signal_result)

                            if active_positions >= MAX_OPEN_POSITIONS:
                                logger.info(f"⚠️ {symbol} AL sinyali var ama max pozisyon ({MAX_OPEN_POSITIONS}) doldu")
                                continue

                            balance_info = collector.fetch_balance()
                            current_balance = balance_info.get('USDT', {}).get('free', 0)

                            can_open, reason = rm.can_open_position(
                                current_balance, signal_result, total_exposure
                            )

                            if can_open:
                                # ATR varsa dinamik, yoksa sabit stop
                                atr_val = df['atr'].iloc[-1] if 'atr' in df.columns else None

                                position = rm.calculate_position_size(
                                    current_balance, current_price, atr=atr_val
                                )

                                if position['coin_amount'] > 0:
                                    buy_result = executor.execute_buy(
                                        symbol=symbol,
                                        amount=position['coin_amount'],
                                        price=None
                                    )

                                    if buy_result:
                                        rm.open_position(
                                            'buy',
                                            buy_result.get('price', current_price),
                                            buy_result.get('amount', position['coin_amount']),
                                            atr=atr_val,
                                            stop_loss_price=position['stop_loss_price']
                                        )
                                        buy_result['symbol'] = symbol
                                        buy_result['stop_loss'] = position['stop_loss_price']
                                        buy_result['take_profit'] = rm.active_position['take_profit']
                                        notifier.send_trade_notification(buy_result)
                                        active_positions += 1
                            else:
                                logger.info(f"⚠️ {symbol} pozisyon açılamadı: {reason}")

                        elif signal_result['signal'] == 'SELL':
                            signal_result['symbol'] = symbol
                            notifier.send_signal(signal_result)

                    time.sleep(1)
                    consecutive_errors = 0  # Başarılı işlem, hata sayacı sıfırla

                except Exception as e:
                    logger.error(f"❌ {symbol} işleme hatası: {e}")
                    consecutive_errors += 1
                    scan_results.append({
                        'symbol': symbol, 'signal': 'SKIP',
                        'score': 0, 'price': 0
                    })

                    # ─── Fail-Safe ─────────────────────────────
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        # Ayni fail-safe mesajini tekrar tekrar loga yazma (spam engeli)
                        if not hasattr(run_live_bot, '_last_fs') or run_live_bot._last_fs != consecutive_errors:
                            logger.error(
                                f"FAIL-SAFE: {consecutive_errors} ardisik hata! "
                                f"{FAILSAFE_WAIT_SECONDS}s bekleniyor."
                            )
                            notifier.send_error(
                                f"Fail-safe aktif: {consecutive_errors} ardisik hata.\n"
                                f"{FAILSAFE_WAIT_SECONDS}s bekleniyor."
                            )
                            run_live_bot._last_fs = consecutive_errors
                        time.sleep(FAILSAFE_WAIT_SECONDS)
                        consecutive_errors = 0
                    continue

            # ─── Tarama Özeti Gönder ──────────────────────────
            logger.info(f"\n{'─'*50}")
            logger.info(f"✅ TARAMA #{scan_count} tamamlandı - {len(scan_results)} coin tarandı")

            buy_count = sum(1 for r in scan_results if r['signal'] == 'BUY')
            sell_count = sum(1 for r in scan_results if r['signal'] == 'SELL')
            hold_count = sum(1 for r in scan_results if r['signal'] == 'HOLD')
            skip_count = sum(1 for r in scan_results if r['signal'] == 'SKIP')

            logger.info(f"   🟢 AL: {buy_count} | 🔴 SAT: {sell_count} | "
                        f"⚪ BEKLE: {hold_count} | ⏭ ATLA: {skip_count}")
            logger.info(f"{'─'*50}\n")

            # Sadece yeni mum kapandığında Telegram özeti gönder (spam önleme)
            if not CLOSED_CANDLE_MODE or new_candle_detected:
                notifier.send_scan_summary(scan_results, active_positions)

            # ─── Periyodik Bekleme ─────────────────────────────
            wait_cycles = max(1, SCAN_INTERVAL_MINUTES // 5)
            logger.info(f"⏳ {SCAN_INTERVAL_MINUTES} dakika bekleniyor (sonraki tarama: ~{SCAN_INTERVAL_MINUTES}dk)")

            for cycle in range(wait_cycles):
                for sym, rm in list(risk_managers.items()):
                    if rm.active_position:
                        try:
                            ticker = collector.fetch_ticker(sym)
                            current_price = ticker['last']
                            should_exit, exit_reason = rm.check_exit_conditions(current_price)

                            if should_exit:
                                pos = rm.active_position
                                sell_result = executor.execute_sell(
                                    symbol=sym,
                                    amount=pos['amount'],
                                    price=None
                                )

                                close_result = rm.close_position(
                                    sell_result.get('price', current_price)
                                )

                                if close_result:
                                    close_result['symbol'] = sym
                                    notifier.send_position_closed(close_result)
                                    logger.info(f"📌 {sym} periyodik kontrol - pozisyon kapatıldı: {exit_reason}")

                        except Exception as e:
                            logger.error(f"❌ {sym} periyodik kontrol hatası: {e}")
                time.sleep(POSITION_CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("🛑 Bot kullanıcı tarafından durduruldu")
            notifier.send_message("🛑 Bot durduruldu")
            break
        except Exception as e:
            logger.error(f"❌ Hata: {e}", exc_info=True)
            notifier.send_error(str(e))
            time.sleep(60)


def check_signal_now():
    """Tüm coinler için anlık sinyal kontrolü yapar."""
    logger = logging.getLogger('signal_check')

    collector = DataCollector()
    signal_generator = SignalGenerator()

    symbols = SYMBOLS if MULTI_COIN_MODE else [SYMBOL]

    print("\n" + "=" * 70)
    print(f"📊 ANLIK SİNYAL TARAMASI ({len(symbols)} coin)")
    print("=" * 70)

    signals_found = []

    for symbol in symbols:
        try:
            df = collector.fetch_ohlcv(symbol=symbol, limit=300)

            if df.empty or len(df) < 210:
                continue

            df = TechnicalIndicators.calculate_all(df)
            result = signal_generator.generate_signal(df)
            summary = TechnicalIndicators.get_summary(df)

            if summary is None:
                continue

            signal_emoji = '🟢' if result['signal'] == 'BUY' else (
                '🔴' if result['signal'] == 'SELL' else '⚪')

            price = result['price']
            rsi = summary['rsi']
            regime = result.get('score_breakdown', {}).get('Regime', '')

            print(f"  {signal_emoji} {symbol:<12} | "
                  f"${price:>10,.2f} | "
                  f"RSI: {rsi:5.1f} | "
                  f"Skor: {result['score']:>+6.1f} | "
                  f"{result['signal']}")

            # Score breakdown göster
            for key, val in result.get('score_breakdown', {}).items():
                print(f"       {key}: {val}")

            if result['signal'] in ('BUY', 'SELL'):
                signals_found.append({
                    'symbol': symbol,
                    'signal': result['signal'],
                    'score': result['score'],
                    'price': price,
                    'reasons': result['reasons'],
                })

            time.sleep(1)

        except Exception as e:
            print(f"  ❌ {symbol:<12} | Hata: {e}")
            continue

    print("=" * 70)

    if signals_found:
        print(f"\n🔔 {len(signals_found)} AKTİF SİNYAL BULUNDU:")
        for s in signals_found:
            emoji = '🟢 AL' if s['signal'] == 'BUY' else '🔴 SAT'
            print(f"\n  {emoji} {s['symbol']} @ ${s['price']:,.2f} (skor: {s['score']})")
            for reason in s['reasons'][1:]:
                print(f"    • {reason}")
    else:
        print("\n⚪ Şu an aktif sinyal yok, piyasa izleniyor...")

    print("=" * 70)


def check_status():
    """
    Anlık portföy durumunu terminale yazar.
    Bakiye, açık pozisyonlar ve gerçek zamanlı PnL tablosu.
    Kullanım: python main.py --mode status
    """
    from datetime import datetime
    from trading.state_manager import StateManager

    # Windows konsolunda UTF-8 zorla (emoji + unicode karakterler icin)
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print()
    print("═" * 62)
    print("  💼  CANLI PORTFÖY DURUM PANELİ")
    print(f"  🕐  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 62)

    # ─── Bakiye ──────────────────────────────────────────────────
    try:
        collector = DataCollector(use_testnet=True)
        balance_raw = collector.fetch_balance()

        usdt_free  = balance_raw.get('USDT', {}).get('free',  0.0)
        usdt_used  = balance_raw.get('USDT', {}).get('used',  0.0)
        usdt_total = balance_raw.get('USDT', {}).get('total', 0.0)

        print()
        print("  💰  BAKİYE (Testnet USDT)")
        print(f"      Kullanılabilir : ${usdt_free:>12,.2f}")
        print(f"      Pozisyonda     : ${usdt_used:>12,.2f}")
        print(f"      TOPLAM         : ${usdt_total:>12,.2f}")
    except Exception as e:
        print(f"  ❌  Bakiye alınamadı: {e}")
        usdt_total = 0.0

    # ─── Açık Pozisyonlar (State Manager'dan) ───────────────────
    print()
    print("  📌  AÇIK POZİSYONLAR")
    print("  " + "─" * 58)

    state_manager = StateManager()
    symbols = SYMBOLS if MULTI_COIN_MODE else [SYMBOL]
    total_open_positions = 0
    total_unrealized_pnl = 0.0

    for sym in symbols:
        coin_state = state_manager.get_coin_state(sym)
        if not coin_state:
            continue
        pos = coin_state.get('active_position')
        if not pos:
            continue

        total_open_positions += 1
        entry  = pos.get('entry_price', 0)
        amount = pos.get('amount', 0)
        sl     = pos.get('stop_loss', 0)
        tp     = pos.get('take_profit', 0)
        opened = pos.get('open_time', 'Bilinmiyor')

        # Anlık fiyat çek
        try:
            ticker = collector.fetch_ticker(sym)
            current = ticker['last']
        except Exception:
            current = entry  # hata olursa giriş fiyatını kullan

        # Gerçek zamanlı kâr/zarar
        pnl_usd = (current - entry) * amount
        pnl_pct = (current - entry) / entry * 100 if entry else 0
        total_unrealized_pnl += pnl_usd

        pnl_arrow = "📈" if pnl_usd >= 0 else "📉"
        print()
        print(f"  🪙  {sym}")
        print(f"      Giriş          : ${entry:>10,.2f}")
        print(f"      Anlık Fiyat    : ${current:>10,.2f}")
        print(f"      Miktar         : {amount:.8f}")
        print(f"      Stop-Loss      : ${sl:>10,.2f}")
        print(f"      Take-Profit    : ${tp:>10,.2f}")
        print(f"      Açılış         : {opened[:19]}")
        print(f"      Gerçek. PnL    : {pnl_arrow} ${pnl_usd:>+,.2f}  ({pnl_pct:+.2f}%)")

    if total_open_positions == 0:
        print("  ⚪  Şu an açık pozisyon yok.")

    # ─── Özet ─────────────────────────────────────────────────────
    print()
    print("  " + "─" * 58)
    print()
    net_total = usdt_total + total_unrealized_pnl
    pnl_emoji = "🟢" if total_unrealized_pnl >= 0 else "🔴"
    print(f"  {pnl_emoji}  Gerçekleşmemiş PnL  : ${total_unrealized_pnl:>+,.2f}")
    print(f"      Net Portföy Değeri  : ${net_total:>12,.2f} USDT")
    print()
    print("═" * 62)
    print()


def main():
    """Ana giriş noktası."""
    parser = argparse.ArgumentParser(description='Bitcoin & Altcoin Trading Bot')
    parser.add_argument('--mode', choices=['backtest', 'paper', 'live', 'signal', 'hyperopt', 'status'],
                       default=None, help='Çalışma modu')
    parser.add_argument('--symbol', type=str, default=None,
                       help='Tek coin backtesting/hyperopt (örn: BTC/USDT)')
    parser.add_argument('--start', type=str, default=None,
                       help='Backtest başlangıç tarihi (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default=None,
                       help='Backtest bitiş tarihi (YYYY-MM-DD)')
    parser.add_argument('--balance', type=float, default=None,
                       help='Başlangıç bakiyesi (USDT)')
    parser.add_argument('--verbose', action='store_true',
                       help='Detaylı log çıktısı')

    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger('main')

    mode = args.mode or TRADING_MODE
    coins = SYMBOLS if MULTI_COIN_MODE else [SYMBOL]

    logger.info("=" * 50)
    logger.info("🪙 CRYPTO TRADING BOT (Faz 1)")
    logger.info(f"   Mod: {mode.upper()}")
    logger.info(f"   Çoklu Coin: {'AÇIK' if MULTI_COIN_MODE else 'KAPALI'}")
    logger.info(f"   Coin Sayısı: {len(coins)}")
    logger.info(f"   Zaman Dilimi: {TIMEFRAME}")
    logger.info(f"   Closed Candle: {CLOSED_CANDLE_MODE}")
    logger.info(f"   Rejim Filtresi: AÇIK")
    logger.info(f"   Risk/Trade: 1%")
    logger.info("=" * 50)

    if mode == 'backtest':
        results = run_backtest(
            symbol=args.symbol,
            start_date=args.start,
            end_date=args.end,
            initial_balance=args.balance,
            verbose=args.verbose
        )
        if results:
            print("\n✅ Backtesting tamamlandı!")

    elif mode == 'hyperopt':
        print("\n" + "=" * 70)
        print("🔍 🚀 MULTI-COIN HYPEROPT BAŞLATILIYOR (3 YILLIK)")
        print("Farklı Risk Profillerine Göre Optimizasyon Yapılıyor...")
        print("=" * 70)
        
        # Faz 3: Hata Paylarını Kademeli Artıran Risk Senaryoları
        scenarios = [
            {'name': 'Safe (Muhafazakar)', 'rsi_oversold': 25, 'ema_long': 200, 'buy_threshold': 4.0},
            {'name': 'Moderate (Dengeli)', 'rsi_oversold': 30, 'ema_long': 100, 'buy_threshold': 3.0},
            {'name': 'Risky (Agresif)',    'rsi_oversold': 35, 'ema_long': 50,  'buy_threshold': 2.0},
            {'name': 'Degen (Maksimum)',   'rsi_oversold': 40, 'ema_long': 20,  'buy_threshold': 1.0}
        ]

        symbols_to_test = SYMBOLS if MULTI_COIN_MODE else [SYMBOL]
        if args.symbol:
            symbols_to_test = [args.symbol]

        for sym in symbols_to_test:
            print(f"\n" + "-" * 50)
            print(f"🪙 {sym} İÇİN TARAMA BAŞLIYOR...")
            print("-" * 50)

            hyper = HyperOptimizer(
                symbol=sym,
                start_date=args.start or '2023-04-01',  # 3 Yıl öncesi
                end_date=args.end or BACKTEST_END_DATE,
                initial_balance=args.balance or BACKTEST_INITIAL_BALANCE
            )
            hyper.optimize(scenarios)

    elif mode == 'signal':
        check_signal_now()

    elif mode == 'status':
        check_status()

    elif mode in ('paper', 'live'):
        if mode == 'live':
            print("\n⚠️  DİKKAT: CANLI MOD!")
            print("    Gerçek para ile işlem yapılacaktır!")
            confirm = input("    Devam etmek istiyor musunuz? (evet/hayır): ")
            if confirm.lower() not in ('evet', 'e', 'yes', 'y'):
                print("İptal edildi.")
                return

        run_live_bot()

    else:
        logger.error(f"Bilinmeyen mod: {mode}")


if __name__ == '__main__':
    main()
