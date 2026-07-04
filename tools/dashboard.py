"""
Portföy Dashboard (CLI + opsiyonel canlı izleme).

Kullanım:
    # Anlık durum:
    python3 tools/dashboard.py

    # 60 saniyede bir yenile:
    python3 tools/dashboard.py --watch 60

Her bot için:
    - Tahsis, güncel değer, P&L, drawdown, durum
Portföy seviyesinde:
    - Toplam değer, peak, drawdown
    - Kill-switch durumu
    - Aylık ekleme geçmişi
"""
import sys
import os
import argparse
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.portfolio_manager import PortfolioManager, BotConfig, PORTFOLIO_STATE_PATH


DEFAULT_BOTS = [
    BotConfig(name='dca',   target_weight=0.40),
    BotConfig(name='grid',  target_weight=0.40),
    BotConfig(name='trend', target_weight=0.20),
]


def load_pm() -> PortfolioManager:
    """Portföy yöneticisini disk'ten yükler. Yoksa default ile oluşturur."""
    return PortfolioManager.load_or_create(
        total_capital=400.0,
        bots=DEFAULT_BOTS,
        state_path=PORTFOLIO_STATE_PATH,
    )


def render_once():
    pm = load_pm()
    report = pm.report()

    # Header
    print('\033[2J\033[H', end='')  # clear screen
    print('═' * 72)
    print(f"  📊 BİTCOİN BOT PORTFÖY DASHBOARD     ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print('═' * 72)

    # Portfolio summary
    print()
    print(pm.format_report())

    # Deposit history (son 5)
    if pm.deposit_history:
        print()
        print('  SON SERMAYE EKLEME GEÇMİŞİ:')
        for d in pm.deposit_history[-5:]:
            ts = d.get('ts', '')[:19]
            note = d.get('note', '')
            amt = d.get('amount', 0)
            print(f"    {ts}  +${amt:>8.2f}  ({note})")

    # Bot durumu uyarıları
    warnings = []
    for name, bot in report['bots'].items():
        if bot.get('drawdown_pct', 0) > 15:
            warnings.append(f"⚠️  {name}: drawdown %{bot['drawdown_pct']:.1f} (10+ → izle, 15+ → askıya alma değerlendir)")
        if bot.get('suspended'):
            warnings.append(f"⏸️  {name}: askıda — {bot.get('suspend_reason', '?')}")

    if report['kill_switch_triggered']:
        warnings.insert(0, f"🚨 PORTFÖY KILL-SWITCH AKTİF — {report.get('kill_switch_reason', '?')}")

    if warnings:
        print()
        print('  UYARILAR:')
        for w in warnings:
            print(f'    {w}')

    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', type=int, default=0,
                        help='Saniyede bir yenile (0 = tek render)')
    args = parser.parse_args()

    if args.watch <= 0:
        render_once()
        return

    try:
        while True:
            render_once()
            time.sleep(args.watch)
    except KeyboardInterrupt:
        print('\nDashboard kapatıldı.')


if __name__ == '__main__':
    main()
