"""
3 Bot Karşılaştırma — DCA / Grid / Trend hepsi 6 dilimde walk-forward.

Kullanım:
    python3 tools/compare_bots.py [--symbol BTC/USDT]

Çıktı: Tek tabloda her bot her dilim için ret%, sharpe, pf, dd.
Hangi bot hangi rejimde iyi açıkça görünür.
"""
import sys
import os
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.collector import DataCollector
from core.walkforward import default_slices, _slice_df
from core.metrics import compute_metrics

from bots.dca_bot import DCABot
from bots.grid_bot import GridBot
from bots.trend_bot import TrendBot


def runner_for(bot_factory):
    def runner(df, balance):
        return bot_factory().backtest(df, initial_balance=balance)
    return runner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', default='BTC/USDT')
    parser.add_argument('--timeframe', default='15m')
    parser.add_argument('--balance', type=float, default=1000)
    parser.add_argument('--start', default='2022-07-01')
    parser.add_argument('--end', default='2026-05-01')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    print(f'\n📥 {args.symbol} {args.timeframe} verisi indiriliyor: {args.start} → {args.end}')
    collector = DataCollector()
    df = collector.fetch_historical_data(args.symbol, args.timeframe, args.start, args.end)
    print(f'✅ {len(df)} mum')
    print()

    bots = {
        'DCA':   lambda: DCABot(coins={args.symbol: 1.0}, interval_hours=168, buy_pct_of_capital=0.10),
        'Grid':  lambda: GridBot(symbol=args.symbol, n_grids=15, range_lookback=480),
        'Trend': lambda: TrendBot(symbol=args.symbol, risk_per_trade=0.05),
    }

    slices = default_slices()

    # results[slice_label][bot_name] = metrics
    results = {s[0]: {} for s in slices}

    for bot_name, factory in bots.items():
        for slice_label, start, end in slices:
            df_slice = _slice_df(df, start, end)
            if df_slice.empty or len(df_slice) < 200:
                results[slice_label][bot_name] = None
                continue
            try:
                out = factory().backtest(df_slice, initial_balance=args.balance)
                m = compute_metrics(out['equity_curve'], out['trades'])
                results[slice_label][bot_name] = m
            except Exception as e:
                results[slice_label][bot_name] = {'error': str(e)}

    # Toplu rapor
    print('═' * 86)
    print(f'  3 BOT KARŞILAŞTIRMA — {args.symbol}')
    print('═' * 86)
    print()
    header = f'  {"DİLİM":<28} | '
    for bot_name in bots:
        header += f'{bot_name + " RET%":>8} {bot_name + " PF":>6} {bot_name + " DD%":>7}  '
    print(header)
    print('  ' + '─' * 84)

    for slice_label, _, _ in slices:
        line = f'  {slice_label[:28]:<28} | '
        for bot_name in bots:
            m = results[slice_label].get(bot_name)
            if m is None:
                line += f'{"SKIP":>8} {"-":>6} {"-":>7}  '
            elif 'error' in m:
                line += f'{"ERR":>8} {"-":>6} {"-":>7}  '
            else:
                line += f'{m["total_return_pct"]:>+8.2f} {m["profit_factor"]:>6.2f} {m["max_drawdown_pct"]:>+7.2f}  '
        print(line)

    print('  ' + '─' * 84)

    # Bot başına ortalama
    print()
    print('  BOT BAŞINA AGREGAT:')
    for bot_name in bots:
        valid = [results[s[0]][bot_name] for s in slices if results[s[0]].get(bot_name) and 'error' not in (results[s[0]].get(bot_name) or {})]
        if not valid:
            continue
        avg_ret = sum(m['total_return_pct'] for m in valid) / len(valid)
        avg_sharpe = sum(m['sharpe'] for m in valid) / len(valid)
        worst_dd = min(m['max_drawdown_pct'] for m in valid)
        positive = sum(1 for m in valid if m['total_return_pct'] > 0)
        print(f'    {bot_name:<6}: ort={avg_ret:+6.2f}%  sharpe={avg_sharpe:+5.2f}  enKötüDD={worst_dd:+6.2f}%  pozitif={positive}/{len(valid)}')

    print('═' * 86)
    print()
    print('  YORUM ÖZETİ:')
    print('    • DCA: Boğa\'da büyük kazanç, ayı\'da büyük DD — uzun vade akümülasyon')
    print('    • Grid: Yatay piyasada en iyi, trend\'li dönemde range escape kayıpları')
    print('    • Trend: ML modeli yeniden eğitilince düzelmesi bekleniyor (etiket fix sonrası)')
    print('  Üçü birlikte → farklı rejimleri kapsayan portföy')


if __name__ == '__main__':
    main()
