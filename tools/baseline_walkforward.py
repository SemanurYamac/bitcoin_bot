"""
Mevcut Trend Bot'unu walk-forward framework'te 6 dilimde test eder.
Yeni mimari öncesi BASELINE ölçüsü alır — gerçekten bu strateji hangi
piyasa rejimlerinde çalışıyor görmek için.

Kullanım:
    python3 tools/baseline_walkforward.py [--symbol BTC/USDT] [--quick]
"""
import sys
import os
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.collector import DataCollector
from core.walkforward import (
    run_walkforward,
    default_slices,
    short_slices,
    existing_engine_runner,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', default='BTC/USDT', help='İşlem çifti (default BTC/USDT)')
    parser.add_argument('--timeframe', default='15m', help='Timeframe (default 15m)')
    parser.add_argument('--balance', type=float, default=1000, help='Başlangıç bakiyesi (default 1000)')
    parser.add_argument('--quick', action='store_true', help='3 kısa dilim (hızlı test)')
    parser.add_argument('--start', default='2022-07-01', help='Veri başlangıcı')
    parser.add_argument('--end', default='2026-05-01', help='Veri sonu')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-7s | %(message)s')

    print(f'\n📥 {args.symbol} {args.timeframe} verisi indiriliyor: {args.start} → {args.end}')
    collector = DataCollector()
    df = collector.fetch_historical_data(args.symbol, args.timeframe, args.start, args.end)
    print(f'✅ {len(df)} mum yüklendi\n')

    slices = short_slices() if args.quick else default_slices()

    report = run_walkforward(
        runner=existing_engine_runner,
        df=df,
        slices=slices,
        initial_balance=args.balance,
        label=f'Mevcut Trend Bot (BASELINE) — {args.symbol}',
    )

    print('\n' + report['summary'])

    if report['gate_passed']:
        print('\n💡 Strateji canlıya alınabilir kriterleri sağlıyor.')
    else:
        print('\n⚠️ Strateji canlıya alınma kriterlerini sağlamıyor — refactor gerekli.')


if __name__ == '__main__':
    main()
