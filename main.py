"""
Bitcoin Trading Bot - Ana Çalıştırma Dosyası
Tüm modülleri birleştirir ve botu çalıştırır.
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
    TRADING_MODE, SYMBOL, TIMEFRAME,
    BACKTEST_START_DATE, BACKTEST_END_DATE, BACKTEST_INITIAL_BALANCE,
    LOG_FILE, LOG_LEVEL
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


def run_backtest(start_date=None, end_date=None, initial_balance=None, verbose=True):
    """
    Backtesting çalıştırır.

    1. Binance'den geçmiş veriyi indirir
    2. Veritabanına kaydeder
    3. Stratejiyi simüle eder
    4. Sonuçları raporlar
    """
    logger = logging.getLogger('backtest')
    logger.info("🔄 Backtesting başlatılıyor...")

    start = start_date or BACKTEST_START_DATE
    end = end_date or BACKTEST_END_DATE
    balance = initial_balance or BACKTEST_INITIAL_BALANCE

    # Veri toplama
    collector = DataCollector()
    storage = DataStorage()

    # Veritabanında veri var mı kontrol et
    try:
        existing_data = storage.load_ohlcv()
        if existing_data.empty or len(existing_data) < 1000:
            logger.info("📥 Geçmiş veri indiriliyor (bu birkaç dakika sürebilir)...")
            df = collector.fetch_historical_data(start_date=start, end_date=end)
            storage.save_ohlcv(df)
        else:
            logger.info(f"📂 Veritabanından {len(existing_data)} mum verisi yüklendi")
            df = existing_data
    except Exception as e:
        logger.info(f"📥 Geçmiş veri indiriliyor: {e}")
        df = collector.fetch_historical_data(start_date=start, end_date=end)
        storage.save_ohlcv(df)

    if df.empty:
        logger.error("❌ Veri indirilemedi!")
        return None

    # Backtesting
    engine = BacktestEngine(initial_balance=balance)
    results = engine.run(df, verbose=verbose)

    return results


def run_live_bot():
    """
    Canlı (veya paper) trading bot çalıştırır.
    Her saat başı çalışır ve sinyal üretir.
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

    risk_manager = RiskManager(usdt_balance)
    executor = TradeExecutor(collector, storage)

    # Telegram bildirimi
    notifier.send_bot_started()

    logger.info(f"⏰ Bot çalışıyor - Her {TIMEFRAME} mum kapanışında kontrol edilecek")

    while True:
        try:
            # Son verileri çek
            df = collector.fetch_ohlcv(limit=300)

            if df.empty:
                logger.warning("⚠️ Veri çekilemedi, 60 saniye bekleniyor...")
                time.sleep(60)
                continue

            # Göstergeleri hesapla
            df = TechnicalIndicators.calculate_all(df)

            # Mevcut fiyatı al
            current_price = df['close'].iloc[-1]
            current_time = datetime.now()

            # Aktif pozisyon kontrolü
            if risk_manager.active_position is not None:
                should_exit, exit_reason = risk_manager.check_exit_conditions(current_price)

                if should_exit:
                    # Pozisyonu kapat
                    pos = risk_manager.active_position
                    sell_result = executor.execute_sell(
                        amount=pos['amount'],
                        price=None  # Market order
                    )

                    close_result = risk_manager.close_position(
                        sell_result.get('price', current_price)
                    )

                    if close_result:
                        notifier.send_position_closed(close_result)
                        logger.info(f"📌 Pozisyon kapatıldı: {exit_reason}")

            else:
                # Sinyal üret
                signal_result = signal_generator.generate_signal(df)

                if signal_result['signal'] == 'BUY':
                    # Bildirim gönder
                    notifier.send_signal(signal_result)

                    # Pozisyon açılabilir mi?
                    balance_info = collector.fetch_balance()
                    current_balance = balance_info.get('USDT', {}).get('free', 0)
                    risk_manager.update_peak_balance(current_balance)

                    can_open, reason = risk_manager.can_open_position(
                        current_balance, signal_result
                    )

                    if can_open:
                        position = risk_manager.calculate_position_size(
                            current_balance, current_price
                        )

                        buy_result = executor.execute_buy(
                            amount=position['btc_amount'],
                            price=None  # Market order
                        )

                        if buy_result:
                            risk_manager.open_position(
                                'buy',
                                buy_result.get('price', current_price),
                                buy_result.get('amount', position['btc_amount'])
                            )
                            notifier.send_trade_notification(buy_result)
                    else:
                        logger.info(f"⚠️ Pozisyon açılamadı: {reason}")

                elif signal_result['signal'] == 'SELL':
                    notifier.send_signal(signal_result)

            # Periyodik bekleme (1 saat = 3600 saniye)
            # Ama her 5 dakikada bir stop-loss kontrol et
            for _ in range(12):  # 12 x 5dk = 60dk = 1 saat
                if risk_manager.active_position:
                    ticker = collector.fetch_ticker()
                    should_exit, reason = risk_manager.check_exit_conditions(ticker['last'])
                    if should_exit:
                        break
                time.sleep(300)  # 5 dakika

        except KeyboardInterrupt:
            logger.info("🛑 Bot kullanıcı tarafından durduruldu")
            notifier.send_message("🛑 Bot durduruldu")
            break
        except Exception as e:
            logger.error(f"❌ Hata: {e}", exc_info=True)
            notifier.send_error(str(e))
            time.sleep(60)


def check_signal_now():
    """Anlık sinyal kontrolü yapar (tek seferlik)."""
    logger = logging.getLogger('signal_check')

    collector = DataCollector()
    df = collector.fetch_ohlcv(limit=300)

    if df.empty:
        logger.error("Veri çekilemedi!")
        return

    df = TechnicalIndicators.calculate_all(df)
    signal_generator = SignalGenerator()
    result = signal_generator.generate_signal(df)

    summary = TechnicalIndicators.get_summary(df)

    print("\n" + "=" * 50)
    print("📊 ANLIK SİNYAL KONTROLÜ")
    print("=" * 50)
    print(f"  Sembol:     {SYMBOL}")
    print(f"  Fiyat:      ${result['price']:,.2f}")
    print(f"  Sinyal:     {result['signal']} (skor: {result['score']})")
    print(f"  RSI:        {summary['rsi']:.1f} ({summary['rsi_signal']})")
    print(f"  MACD:       {summary['macd_signal']}")
    print(f"  Bollinger:  {summary['bollinger_signal']}")
    print(f"  EMA:        {summary['ema_signal']}")
    print(f"  Hacim:      {summary['volume_signal']}")
    print()

    print("  Nedenler:")
    for reason in result['reasons']:
        print(f"    {reason}")
    print("=" * 50)


def main():
    """Ana giriş noktası."""
    parser = argparse.ArgumentParser(description='Bitcoin Trading Bot')
    parser.add_argument('--mode', choices=['backtest', 'paper', 'live', 'signal'],
                       default=None, help='Çalışma modu')
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

    logger.info("=" * 50)
    logger.info("🪙 BITCOIN TRADING BOT")
    logger.info(f"   Mod: {mode.upper()}")
    logger.info(f"   Sembol: {SYMBOL}")
    logger.info(f"   Zaman Dilimi: {TIMEFRAME}")
    logger.info("=" * 50)

    if mode == 'backtest':
        results = run_backtest(
            start_date=args.start,
            end_date=args.end,
            initial_balance=args.balance,
            verbose=args.verbose
        )
        if results:
            print("\n✅ Backtesting tamamlandı! Sonuçlar yukarıda.")

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
