"""
Canlı Portföy Orchestrator — 3 botu paralel çalıştırır.

Akış:
    1. PortfolioManager state'i yükle (data/portfolio_state.json)
    2. Kill-switch tetiklenmiş mi kontrol et — evetse SADECE rapor, işlem yok
    3. Her bot için step() çağır
    4. Botlar PM'ye değer raporlar
    5. PM kill-switch kontrolü yapar
    6. Periyodik dashboard yaz, Telegram bildirim gönder

Kullanım:
    # Tek döngü (cron'la çalıştırılabilir):
    python3 tools/run_portfolio.py --once

    # Sürekli (her 5 dakikada bir):
    python3 tools/run_portfolio.py --interval 300

ÖNEMLİ: Live mod'a geçmeden önce TRADING_MODE=live yap (.env veya export).
Default 'backtest' modunda hiçbir gerçek emir gönderilmez.
"""
import sys
import os
import argparse
import logging
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.portfolio_manager import PortfolioManager, BotConfig, PORTFOLIO_STATE_PATH
from bots.dca_bot import DCABot
from bots.grid_bot import GridBot
from bots.trend_bot import TrendBot
from config.settings import TRADING_MODE


logger = logging.getLogger('orchestrator')


# Plan'daki 40/40/20 ağırlıklar
DEFAULT_WEIGHTS = [
    BotConfig(name='dca',   target_weight=0.40),
    BotConfig(name='grid',  target_weight=0.40),
    BotConfig(name='trend', target_weight=0.20),
]


def build_bots(pm: PortfolioManager, only: list[str] | None = None) -> dict[str, object]:
    """
    Tüm botları yarat ve sermayeyi initialize et.

    Args:
        only: Sadece belirtilen bot isimlerini yarat (örn ['dca'])
              None ise hepsi
    """
    all_bots: dict[str, object] = {
        'dca':   DCABot(coins={'BTC/USDT': 0.5, 'ETH/USDT': 0.5}, portfolio_manager=pm),
        'grid':  GridBot(symbol='BTC/USDT', portfolio_manager=pm),
        'trend': TrendBot(symbol='BTC/USDT', portfolio_manager=pm),
    }
    if only:
        bots = {k: v for k, v in all_bots.items() if k in only}
    else:
        bots = all_bots
    for name, bot in bots.items():
        # State'i restore et (varsa)
        if hasattr(bot, 'restore'):
            bot.restore()
        # Sermaye yoksa init et
        if hasattr(bot, 'initialize_capital') and getattr(bot, 'cash', 0) == 0:
            bot.initialize_capital(pm.get_allocation(name))
    return bots


def run_one_cycle(pm: PortfolioManager, bots: dict[str, object]) -> None:
    """Tüm botların bir döngüsünü çalıştır."""
    now = datetime.utcnow()

    # Kill-switch kontrolü
    if pm.check_kill_switch():
        logger.critical(f'🚨 Kill-switch aktif — botlar pasif. Sebep: {pm.kill_switch_reason}')
        return

    # Her bot step
    for name, bot in bots.items():
        try:
            bot.step(now)
        except Exception as e:
            logger.exception(f'[{name}] step hatası: {e}')

    # Tüm botların güncel değerlerini topla
    pm.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Tek döngü çalıştır ve çık')
    parser.add_argument('--interval', type=int, default=300, help='Saniyede bir döngü (default 300=5dk)')
    parser.add_argument('--total-capital', type=float, default=400.0, help='Toplam sermaye (yeni init için)')
    parser.add_argument('--bots', nargs='+', choices=['dca', 'grid', 'trend'],
                        help='Sadece belirtilen botları çalıştır (default: hepsi)')
    parser.add_argument('--live-confirm', action='store_true',
                        help='TRADING_MODE=live ise bu flag olmadan çalışmaz (güvenlik kilidi)')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-7s | %(message)s')

    # ═══ GÜVENLİK KİLİDİ: Canlı moda kazara girme koruması ═══
    if TRADING_MODE == 'live' and not args.live_confirm:
        logger.critical('🛑 TRADING_MODE=live AMA --live-confirm flag\'i yok!')
        logger.critical('   Yerel testlerde .env içinde TRADING_MODE=backtest yap,')
        logger.critical('   veya canlıya gerçekten geçmek istiyorsan --live-confirm ekle.')
        logger.critical('   Bu kilit kazara canlıya gitmeyi engellemek için.')
        sys.exit(2)

    if TRADING_MODE == 'live' and args.live_confirm:
        logger.warning('⚠️ CANLI MOD ONAYLANDI — gerçek emirler gönderilebilir!')

    logger.info(f'🤖 Portföy Orchestrator — TRADING_MODE={TRADING_MODE}')

    pm = PortfolioManager.load_or_create(
        total_capital=args.total_capital,
        bots=DEFAULT_WEIGHTS,
        state_path=PORTFOLIO_STATE_PATH,
    )

    bots = build_bots(pm, only=args.bots)
    logger.info(f'✅ {len(bots)} bot hazır: {list(bots.keys())}')
    logger.info(pm.format_report())

    if args.once:
        run_one_cycle(pm, bots)
        logger.info('Tek döngü tamamlandı.')
        return

    while True:
        try:
            run_one_cycle(pm, bots)
            logger.info(f'⏱️  {args.interval}s bekleniyor...')
            time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info('Orchestrator kapatıldı.')
            break


if __name__ == '__main__':
    main()
