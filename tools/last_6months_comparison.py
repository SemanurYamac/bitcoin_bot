"""
Son 6 Ay Karşılaştırma — Aynı dönemde 4 strateji.

Donchian son 6 ayda -%13 yaptı. Diğerleri ne yaparmış?
  1. Pure DCA BTC
  2. Pure DCA XRP
  3. Buy & Hold BTC
  4. Buy & Hold XRP
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.collector import DataCollector
from bots.dca_bot import DCABot


CAPITAL = 1000.0
MONTHS = 6


def main():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=MONTHS * 30)
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')

    print('═' * 80)
    print(f'  📊 SON 6 AY KARŞILAŞTIRMA — ${CAPITAL:.0f} sermaye')
    print(f'  Dönem: {start_str} → {end_str}')
    print('═' * 80)

    collector = DataCollector()

    print('\n📥 Veriler indiriliyor...')
    btc_df = collector.fetch_historical_data('BTC/USDT', '15m', start_str, end_str)
    xrp_df = collector.fetch_historical_data('XRP/USDT', '15m', start_str, end_str)
    print(f'  ✓ BTC: {len(btc_df):,} mum')
    print(f'  ✓ XRP: {len(xrp_df):,} mum\n')

    results = []

    # 1. Pure DCA BTC
    dca = DCABot(coins={'BTC/USDT': 1.0}, interval_hours=168, buy_pct_of_capital=0.05)
    out = dca.backtest(btc_df, initial_balance=CAPITAL)
    final_btc_dca = float(out['equity_curve'].iloc[-1]) if not out['equity_curve'].empty else CAPITAL
    pnl_pct = (final_btc_dca - CAPITAL) / CAPITAL * 100
    results.append(('Pure DCA BTC', final_btc_dca, pnl_pct))

    # 2. Pure DCA XRP
    dca = DCABot(coins={'XRP/USDT': 1.0}, interval_hours=168, buy_pct_of_capital=0.05)
    out = dca.backtest(xrp_df, initial_balance=CAPITAL)
    final_xrp_dca = float(out['equity_curve'].iloc[-1]) if not out['equity_curve'].empty else CAPITAL
    pnl_pct = (final_xrp_dca - CAPITAL) / CAPITAL * 100
    results.append(('Pure DCA XRP', final_xrp_dca, pnl_pct))

    # 3. Buy & Hold BTC (tek alım, tut)
    if not btc_df.empty:
        bnh_return = (btc_df['close'].iloc[-1] - btc_df['close'].iloc[0]) / btc_df['close'].iloc[0]
        bnh_btc = CAPITAL * (1 + bnh_return)
        results.append(('Buy & Hold BTC', bnh_btc, bnh_return * 100))

    # 4. Buy & Hold XRP
    if not xrp_df.empty:
        bnh_return = (xrp_df['close'].iloc[-1] - xrp_df['close'].iloc[0]) / xrp_df['close'].iloc[0]
        bnh_xrp = CAPITAL * (1 + bnh_return)
        results.append(('Buy & Hold XRP', bnh_xrp, bnh_return * 100))

    # 5. Donchian (önceden hesapladık)
    results.append(('Donchian Weekly (universe)', 932.57, -6.74))

    # Tablo
    print('═' * 80)
    print('  📊 SON 6 AY SONUÇLARI ($1000 başlangıç)')
    print('═' * 80)
    print(f'  {"STRATEJİ":<28} {"FINAL":>12} {"P&L":>10} {"P&L %":>8}')
    print('  ' + '─' * 65)

    results.sort(key=lambda x: x[1], reverse=True)
    for name, final, pnl_pct in results:
        emoji = '🏆' if final > 1100 else ('✅' if final > CAPITAL else ('⚠️' if final > 900 else '❌'))
        print(f'  {emoji} {name:<26} ${final:>10.2f} ${final - CAPITAL:>+8.2f} {pnl_pct:>+6.2f}%')

    print()
    print('═' * 80)
    print('  💡 YORUM:')
    best = results[0]
    worst = results[-1]
    print(f'  🏆 En iyi: {best[0]} ({best[2]:+.2f}%)')
    print(f'  💀 En kötü: {worst[0]} ({worst[2]:+.2f}%)')
    print(f'  Fark: {best[2] - worst[2]:.2f}% (aynı dönemde aynı sermaye)')
    print('═' * 80)


if __name__ == '__main__':
    main()
