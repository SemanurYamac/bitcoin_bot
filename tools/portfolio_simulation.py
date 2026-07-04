"""
Portföy Seviyesi Backtest — $X başlangıç, 40/40/20 ağırlıkla 3 bot paralel.

Kullanım:
    # Sade: $1000 başlangıç, 4 yıl tek backtest
    python3 tools/portfolio_simulation.py --capital 1000

    # Aylık ekleme ile (gerçek senaryo):
    python3 tools/portfolio_simulation.py --capital 400 --monthly-add 200

    # Sadece BTC veya çoklu coin
    python3 tools/portfolio_simulation.py --capital 1000 --symbols BTC/USDT,ETH/USDT
"""
import sys
import os
import argparse
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from data.collector import DataCollector
from bots.dca_bot import DCABot
from bots.grid_bot import GridBot
from bots.trend_bot import TrendBot

logger = logging.getLogger('portfolio_sim')


def simulate(df: pd.DataFrame, total_capital: float, weights: dict,
             monthly_add: float = 0.0, symbol: str = 'BTC/USDT') -> dict:
    """
    df üzerinde tek bir tam backtest çalıştırır.
    monthly_add > 0 ise her ay başında sermaye eklenir.

    Şimdilik basitleştirme: monthly_add tüm botlara hedef ağırlıkla dağılır AMA
    botlar bağımsız çalıştığı için ekleme her botun başlangıç sermayesine ek
    olarak verilmiş gibi simüle edilir (ortalama bir yaklaşım).
    """
    # Ağırlıkları normalize et (kullanıcı 0 verirse o bot devre dışı)
    total_w = sum(weights.values())
    if total_w <= 0:
        raise ValueError("Toplam ağırlık 0 olamaz")
    weights = {k: v / total_w for k, v in weights.items()}

    dca_cap = total_capital * weights.get('dca', 0)
    grid_cap = total_capital * weights.get('grid', 0)
    trend_cap = total_capital * weights.get('trend', 0)

    parts = []
    if dca_cap > 0:   parts.append(f'DCA ${dca_cap:.2f}')
    if grid_cap > 0:  parts.append(f'Grid ${grid_cap:.2f}')
    if trend_cap > 0: parts.append(f'Trend ${trend_cap:.2f}')
    print(f'  💰 Başlangıç tahsisi: {" | ".join(parts)}')

    # Aylık eklemeyi ek başlangıç sermayesine ekle (yaklaşım — gerçekte zamana yayılır)
    months = (df.index[-1] - df.index[0]).days / 30.44
    total_added = monthly_add * months
    if monthly_add > 0:
        # Her bota ağırlıkça payını ekle (sanki ay başı eklenmiş gibi ortalama)
        avg_added_dca = total_added * weights['dca'] / 2  # zamana yayıldığı için /2
        avg_added_grid = total_added * weights['grid'] / 2
        avg_added_trend = total_added * weights['trend'] / 2
        dca_cap_eff = dca_cap + avg_added_dca
        grid_cap_eff = grid_cap + avg_added_grid
        trend_cap_eff = trend_cap + avg_added_trend
        print(f'  📈 Aylık ekleme: ${monthly_add:.2f} × {months:.1f} ay = ${total_added:.2f} toplam ek')
    else:
        dca_cap_eff = dca_cap
        grid_cap_eff = grid_cap
        trend_cap_eff = trend_cap

    # Bot çalıştır (sadece pozitif allocation olanlar)
    print(f'  🤖 Botlar çalışıyor...')
    dca_final = dca_cap_eff
    grid_final = grid_cap_eff
    trend_final = trend_cap_eff

    if dca_cap_eff > 0:
        dca = DCABot(coins={symbol: 1.0}, interval_hours=168, buy_pct_of_capital=0.05)
        dca_out = dca.backtest(df, initial_balance=dca_cap_eff)
        if not dca_out['equity_curve'].empty:
            dca_final = float(dca_out['equity_curve'].iloc[-1])

    if grid_cap_eff > 0:
        grid = GridBot(symbol=symbol, n_grids=15, range_lookback=480)
        grid_out = grid.backtest(df, initial_balance=grid_cap_eff)
        if not grid_out['equity_curve'].empty:
            grid_final = float(grid_out['equity_curve'].iloc[-1])

    if trend_cap_eff > 0:
        trend = TrendBot(symbol=symbol, risk_per_trade=0.05)
        trend_out = trend.backtest(df, initial_balance=trend_cap_eff)
        if not trend_out['equity_curve'].empty:
            trend_final = float(trend_out['equity_curve'].iloc[-1])

    total_final = dca_final + grid_final + trend_final
    total_input = total_capital + total_added
    profit = total_final - total_input
    profit_pct = (profit / total_input * 100) if total_input > 0 else 0

    return {
        'total_input': total_input,
        'total_capital_initial': total_capital,
        'monthly_added_total': total_added,
        'dca_initial': dca_cap_eff,
        'dca_final': dca_final,
        'dca_pnl_pct': (dca_final - dca_cap_eff) / dca_cap_eff * 100 if dca_cap_eff > 0 else 0,
        'grid_initial': grid_cap_eff,
        'grid_final': grid_final,
        'grid_pnl_pct': (grid_final - grid_cap_eff) / grid_cap_eff * 100 if grid_cap_eff > 0 else 0,
        'trend_initial': trend_cap_eff,
        'trend_final': trend_final,
        'trend_pnl_pct': (trend_final - trend_cap_eff) / trend_cap_eff * 100 if trend_cap_eff > 0 else 0,
        'total_final': total_final,
        'profit': profit,
        'profit_pct': profit_pct,
        'months': months,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capital', type=float, default=1000.0, help='Başlangıç sermayesi USDT')
    parser.add_argument('--monthly-add', type=float, default=0.0, help='Aylık ekleme USDT')
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    parser.add_argument('--symbol', default='BTC/USDT')
    parser.add_argument('--dca', type=float, default=0.40, help='DCA ağırlığı (0-1)')
    parser.add_argument('--grid', type=float, default=0.40, help='Grid ağırlığı (0-1)')
    parser.add_argument('--trend', type=float, default=0.20, help='Trend ağırlığı (0-1)')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    weights = {'dca': args.dca, 'grid': args.grid, 'trend': args.trend}

    print('═' * 70)
    print(f'  🧪 PORTFÖY BACKTEST — ${args.capital:.0f} başlangıç + ${args.monthly_add:.0f}/ay ekleme')
    print(f'  Dönem: {args.start} → {args.end}')
    print(f'  Ağırlık: DCA {weights["dca"]:.0%} / Grid {weights["grid"]:.0%} / Trend {weights["trend"]:.0%}')
    print('═' * 70)

    print()
    print(f'📥 {args.symbol} verisi indiriliyor...')
    collector = DataCollector()
    df = collector.fetch_historical_data(args.symbol, '15m', args.start, args.end)
    print(f'✅ {len(df):,} mum')
    print()

    result = simulate(df, args.capital, weights, args.monthly_add, symbol=args.symbol)

    print()
    print('═' * 70)
    print('  📊 SONUÇ')
    print('═' * 70)
    print()
    print(f'  Toplam Yatırım:    ${result["total_input"]:>10.2f}')
    print(f'    Başlangıç:       ${result["total_capital_initial"]:>10.2f}')
    if result['monthly_added_total'] > 0:
        print(f'    Aylık ekleme:    ${result["monthly_added_total"]:>10.2f}  ({result["months"]:.1f} ay × ${args.monthly_add:.0f})')
    print(f'  Final Değer:       ${result["total_final"]:>10.2f}')
    print(f'  ─────────────────────────────────────')
    print(f'  KAR / ZARAR:       ${result["profit"]:>+10.2f}  ({result["profit_pct"]:+.2f}%)')
    print()
    print('  BOT BAŞINA:')
    print(f'    {"BOT":<7} {"BAŞLANGIÇ":>12} {"FINAL":>12} {"P&L":>10} {"P&L%":>8}')
    print(f'    {"DCA":<7} ${result["dca_initial"]:>10.2f} ${result["dca_final"]:>10.2f} ${result["dca_final"]-result["dca_initial"]:>+8.2f} {result["dca_pnl_pct"]:>+7.2f}%')
    print(f'    {"Grid":<7} ${result["grid_initial"]:>10.2f} ${result["grid_final"]:>10.2f} ${result["grid_final"]-result["grid_initial"]:>+8.2f} {result["grid_pnl_pct"]:>+7.2f}%')
    print(f'    {"Trend":<7} ${result["trend_initial"]:>10.2f} ${result["trend_final"]:>10.2f} ${result["trend_final"]-result["trend_initial"]:>+8.2f} {result["trend_pnl_pct"]:>+7.2f}%')
    print()

    # Aylık denklik
    monthly_avg_pct = result['profit_pct'] / result['months'] if result['months'] > 0 else 0
    monthly_avg_dollar = result['profit'] / result['months'] if result['months'] > 0 else 0
    print(f'  AYLIK ORT.:        ${monthly_avg_dollar:>+10.2f}  ({monthly_avg_pct:+.2f}% / ay)')

    # Buy & hold karşılaştırma
    if not df.empty:
        bnh_return = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0]
        bnh_final = args.capital * (1 + bnh_return)
        print()
        print(f'  📊 KARŞILAŞTIRMA — Saf Buy & Hold (sadece BTC):')
        print(f'    ${args.capital:.0f} → ${bnh_final:.2f}  ({bnh_return*100:+.2f}%)')

    print('═' * 70)


if __name__ == '__main__':
    main()
