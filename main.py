"""
Bitcoin & Altcoin Trading Bot - Ana Çalıştırma Dosyası
Tüm modülleri birleştirir, çoklu coin tarar ve botu çalıştırır.
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
    LOG_FILE, LOG_LEVEL, MULTI_COIN_MODE, MIN_VOLUME_24H, MAX_OPEN_POSITIONS
)
from data.collector import DataCollector
from data.storage import DataStorage
from analysis.indicators import TechnicalIndicators
from strategy.signals import SignalGenerator
from trading.risk_manager import RiskManager
from trading.executor import TradeExecutor
from backtest.engine import BacktestEngine
from notifications.notifier import TelegramNotifier


def setup_logging():
    """Loglama ayarlarını yapılandırır."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )


def run_backtest(symbol=None, start_date=None, end_date=None,
                 initial_balance=None, verbose=True):
    """
    Backtesting çalıştırır (tek coin veya çoklu coin).
    """
    logger = logging.getLogger('backtest')

    start = start_date or BACKTEST_START_DATE
    end = end_date or BACKTEST_END_DATE
    balance = initial_balance or BACKTEST_INITIAL_BALANCE

    collector = DataCollector()
    storage = DataStorage()

    # Çoklu coin modu
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
            # Veri indir
            df = collector.fetch_historical_data(
                symbol=sym, start_date=start, end_date=end
            )

            if df.empty or len(df) < 300:
                logger.warning(f"⚠️ {sym} için yeterli veri yok, atlanıyor...")
                continue

            # Backtesting
            engine = BacktestEngine(initial_balance=balance)
            results = engine.run(df, verbose=verbose)
            results['symbol'] = sym
            all_results[sym] = results

        except Exception as e:
            logger.error(f"❌ {sym} backtesting hatası: {e}")
            continue

    # Çoklu coin sonuç özeti
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
    Çoklu coin modunda tüm coinleri tarar, sinyal bulduğunda işlem yapar.
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

    # Her coin için ayrı risk manager
    risk_managers = {}  # {symbol: RiskManager}
    executor = TradeExecutor(collector, storage)

    # Hangi coinleri tarayacağız
    symbols = SYMBOLS if MULTI_COIN_MODE else [SYMBOL]

    # Telegram bildirimi
    notifier.send_bot_started()
    coin_list = ', '.join([s.split('/')[0] for s in symbols])
    notifier.send_message(
        f"📋 <b>Taranan coinler ({len(symbols)}):</b>\n"
        f"<code>{coin_list}</code>"
    )

    logger.info(f"⏰ Bot çalışıyor - {len(symbols)} coin taranıyor")
    logger.info(f"📋 Coinler: {coin_list}")

    while True:
        try:
            active_positions = sum(
                1 for rm in risk_managers.values()
                if rm.active_position is not None
            )

            for symbol in symbols:
                try:
                    # ─── Veri Çek ───────────────────────────────
                    df = collector.fetch_ohlcv(symbol=symbol, limit=300)

                    if df.empty:
                        continue

                    # Hacim filtresi (düşük hacimli coinleri atla)
                    try:
                        ticker = collector.fetch_ticker(symbol)
                        if ticker.get('volume', 0) * ticker.get('last', 0) < MIN_VOLUME_24H:
                            continue
                    except Exception:
                        pass

                    # ─── Göstergeleri Hesapla ───────────────────
                    df = TechnicalIndicators.calculate_all(df)

                    current_price = df['close'].iloc[-1]

                    # Risk manager oluştur (yoksa)
                    if symbol not in risk_managers:
                        per_coin_balance = usdt_balance / MAX_OPEN_POSITIONS
                        risk_managers[symbol] = RiskManager(per_coin_balance)

                    rm = risk_managers[symbol]

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

                    else:
                        # ─── Sinyal Üret ───────────────────────
                        signal_result = signal_generator.generate_signal(df)

                        if signal_result['signal'] == 'BUY':
                            signal_result['symbol'] = symbol
                            notifier.send_signal(signal_result)

                            # Çok fazla açık pozisyon var mı?
                            if active_positions >= MAX_OPEN_POSITIONS:
                                logger.info(f"⚠️ {symbol} AL sinyali var ama max pozisyon ({MAX_OPEN_POSITIONS}) doldu")
                                continue

                            balance_info = collector.fetch_balance()
                            current_balance = balance_info.get('USDT', {}).get('free', 0)

                            can_open, reason = rm.can_open_position(
                                current_balance, signal_result
                            )

                            if can_open:
                                position = rm.calculate_position_size(
                                    current_balance, current_price
                                )

                                buy_result = executor.execute_buy(
                                    symbol=symbol,
                                    amount=position['btc_amount'],
                                    price=None
                                )

                                if buy_result:
                                    rm.open_position(
                                        'buy',
                                        buy_result.get('price', current_price),
                                        buy_result.get('amount', position['btc_amount'])
                                    )
                                    buy_result['symbol'] = symbol
                                    notifier.send_trade_notification(buy_result)
                                    active_positions += 1

                            else:
                                logger.info(f"⚠️ {symbol} pozisyon açılamadı: {reason}")

                        elif signal_result['signal'] == 'SELL':
                            signal_result['symbol'] = symbol
                            notifier.send_signal(signal_result)

                    # Borsayı spam'lamemek için bekleme
                    time.sleep(2)

                except Exception as e:
                    logger.error(f"❌ {symbol} işleme hatası: {e}")
                    continue

            # ─── Periyodik Bekleme ─────────────────────────────
            # Her 5 dakikada bir açık pozisyonları kontrol et
            for _ in range(12):  # 12 x 5dk = 60dk = 1 saat
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
                time.sleep(300)

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

            print(f"  {signal_emoji} {symbol:<12} | "
                  f"${price:>10,.2f} | "
                  f"RSI: {rsi:5.1f} | "
                  f"Skor: {result['score']:>+6.1f} | "
                  f"{result['signal']}")

            if result['signal'] in ('BUY', 'SELL'):
                signals_found.append({
                    'symbol': symbol,
                    'signal': result['signal'],
                    'score': result['score'],
                    'price': price,
                    'reasons': result['reasons'],
                })

            time.sleep(1)  # Rate limit

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


def main():
    """Ana giriş noktası."""
    parser = argparse.ArgumentParser(description='Bitcoin & Altcoin Trading Bot')
    parser.add_argument('--mode', choices=['backtest', 'paper', 'live', 'signal'],
                       default=None, help='Çalışma modu')
    parser.add_argument('--symbol', type=str, default=None,
                       help='Tek coin backtesting (örn: ETH/USDT)')
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
    logger.info("🪙 CRYPTO TRADING BOT")
    logger.info(f"   Mod: {mode.upper()}")
    logger.info(f"   Çoklu Coin: {'AÇIK' if MULTI_COIN_MODE else 'KAPALI'}")
    logger.info(f"   Coin Sayısı: {len(coins)}")
    logger.info(f"   Zaman Dilimi: {TIMEFRAME}")
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

    elif mode == 'signal':
        check_signal_now()

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
