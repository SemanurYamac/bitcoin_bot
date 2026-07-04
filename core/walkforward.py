"""
Walk-Forward Backtest Framework — 6 dilim üzerinde sıralı test.

Tek bir 4 aylık dilimde "+%9 → +%4 oldu, kötüleşti" demek istatistiksel olarak
anlamsız. Bu modül stratejiyi **6 farklı piyasa rejimine** uygular ve her dilim
için ayrı metrik üretir. Sonra agregat.

Default 6 dilim — kripto piyasa tarihinden seçildi:
    1. 2022 H2  : Sert ayı + Luna/FTX çöküşü
    2. 2023 H1  : Toparlanma + bankacılık krizi
    3. 2023 H2  : Yatay → yükseliş başlangıcı
    4. 2024 H1  : Boğa başlangıcı + ETF onayları
    5. 2024 H2  : Boğa zirvesi + halving sonrası
    6. 2025+2026: Karışık + 2026 Oca-May ayısı

Strateji "iyi" sayılır ancak: en az 4 dilimde profit factor > 1.0,
ortalama Sharpe > 0.3, en kötü dilimde max DD < %35.

Kullanım:
    from core.walkforward import run_walkforward, default_slices

    def my_runner(df_slice, initial_balance):
        # ...kendi stratejini çalıştır...
        return {'equity_curve': pd.Series, 'trades': pd.DataFrame}

    report = run_walkforward(my_runner, df, slices=default_slices())
    print(report['summary'])
"""
from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import pandas as pd

from core.metrics import compute_metrics, format_report, is_strategy_acceptable

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Standart dilimler
# ────────────────────────────────────────────────────────────────────

def default_slices() -> list[tuple[str, str, str]]:
    """
    Returns:
        list[(label, start_date, end_date)]
    """
    return [
        ('2022 H2 — Ayı + Luna/FTX', '2022-07-01', '2022-12-31'),
        ('2023 H1 — Toparlanma',     '2023-01-01', '2023-06-30'),
        ('2023 H2 — Yatay/Yükseliş', '2023-07-01', '2023-12-31'),
        ('2024 H1 — Boğa Başı + ETF','2024-01-01', '2024-06-30'),
        ('2024 H2 — Boğa Zirvesi',   '2024-07-01', '2024-12-31'),
        ('2025+2026 — Karışık',      '2025-01-01', '2026-05-01'),
    ]


def short_slices() -> list[tuple[str, str, str]]:
    """Hızlı geliştirme için kısa 3 dilim."""
    return [
        ('Ayı 2022',   '2022-07-01', '2022-12-31'),
        ('Boğa 2024',  '2024-01-01', '2024-06-30'),
        ('Mixed 2025', '2025-01-01', '2026-05-01'),
    ]


# ────────────────────────────────────────────────────────────────────
# Walk-forward runner
# ────────────────────────────────────────────────────────────────────

StrategyRunner = Callable[[pd.DataFrame, float], dict]


def _slice_df(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """DataFrame'i tarih aralığına göre keser."""
    if df.empty:
        return df
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
    return df.loc[start:end].copy()


def run_walkforward(
    runner: StrategyRunner,
    df: pd.DataFrame,
    slices: list[tuple[str, str, str]] | None = None,
    initial_balance: float = 1000.0,
    label: str = 'Strateji',
    verbose: bool = True,
) -> dict:
    """
    Verilen stratejiyi her dilimde ayrı çalıştırır, metrik hesaplar.

    Args:
        runner: (df_slice, initial_balance) → {'equity_curve': pd.Series, 'trades': df}
        df: Tüm dönemi kapsayan OHLCV DataFrame (DatetimeIndex)
        slices: list[(label, start, end)] — None ise default_slices()
        initial_balance: Her dilimde aynı başlangıç bakiyesi
        label: Rapor başlığı

    Returns:
        dict {
            'slices': list[dict] — her dilim için: label, start, end, metrics
            'aggregate': dict — ortalama/dağılım
            'summary': str — yazdırılabilir konsol raporu
            'gate_passed': bool — canlıya alma kriterleri
            'gate_reasons': list[str]
        }
    """
    if slices is None:
        slices = default_slices()

    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)

    slice_results = []
    for slice_label, start, end in slices:
        df_slice = _slice_df(df, start, end)
        if df_slice.empty or len(df_slice) < 200:
            slice_results.append({
                'label': slice_label,
                'start': start,
                'end': end,
                'skipped': True,
                'reason': f'Yetersiz veri ({len(df_slice)} mum)',
                'metrics': None,
            })
            if verbose:
                logger.warning(f"⚠️ {slice_label}: yetersiz veri, atlandı")
            continue

        try:
            result = runner(df_slice, initial_balance)
            equity = result.get('equity_curve')
            trades = result.get('trades')

            if equity is None or len(equity) < 2:
                slice_results.append({
                    'label': slice_label,
                    'start': start,
                    'end': end,
                    'skipped': True,
                    'reason': 'Equity curve oluşturulamadı',
                    'metrics': None,
                })
                continue

            metrics = compute_metrics(equity, trades)
            slice_results.append({
                'label': slice_label,
                'start': start,
                'end': end,
                'skipped': False,
                'metrics': metrics,
            })

            if verbose:
                logger.info(
                    f"  ✓ {slice_label}: ret={metrics['total_return_pct']:+.2f}% "
                    f"sharpe={metrics['sharpe']:.2f} pf={metrics['profit_factor']:.2f} "
                    f"dd={metrics['max_drawdown_pct']:.1f}% "
                    f"trades={metrics['sell_count']}"
                )
        except Exception as e:
            logger.exception(f"❌ {slice_label}: çalıştırma hatası: {e}")
            slice_results.append({
                'label': slice_label,
                'start': start,
                'end': end,
                'skipped': True,
                'reason': f'Hata: {e}',
                'metrics': None,
            })

    aggregate = _aggregate(slice_results)
    gate_passed, gate_reasons = _check_gate(slice_results, aggregate)
    summary = _format_summary(label, slice_results, aggregate, gate_passed, gate_reasons)

    return {
        'slices': slice_results,
        'aggregate': aggregate,
        'summary': summary,
        'gate_passed': gate_passed,
        'gate_reasons': gate_reasons,
    }


def _aggregate(slice_results: list[dict]) -> dict:
    """Dilim sonuçlarını ortalama + dağılım olarak özetler."""
    valid = [s['metrics'] for s in slice_results if s.get('metrics')]
    if not valid:
        return {
            'count': 0,
            'avg_return_pct': 0.0,
            'avg_sharpe': 0.0,
            'avg_profit_factor': 0.0,
            'worst_drawdown_pct': 0.0,
            'positive_slices': 0,
            'profitable_slices': 0,
        }

    returns = [m['total_return_pct'] for m in valid]
    sharpes = [m['sharpe'] for m in valid]
    pfs = [m['profit_factor'] for m in valid]
    dds = [m['max_drawdown_pct'] for m in valid]

    return {
        'count': len(valid),
        'avg_return_pct': round(float(np.mean(returns)), 2),
        'std_return_pct': round(float(np.std(returns)), 2),
        'avg_sharpe': round(float(np.mean(sharpes)), 2),
        'avg_profit_factor': round(float(np.mean(pfs)), 2),
        'worst_drawdown_pct': round(float(min(dds)), 2),
        'best_return_pct': round(float(max(returns)), 2),
        'worst_return_pct': round(float(min(returns)), 2),
        'positive_slices': sum(1 for r in returns if r > 0),
        'profitable_slices': sum(1 for pf in pfs if pf > 1.0),
    }


def _check_gate(slice_results: list[dict], aggregate: dict) -> tuple[bool, list[str]]:
    """
    Plan'daki canlıya çıkma kriteri:
      - En az 4 dilimde profit factor > 1.0
      - Ortalama Sharpe > 0.3
      - En kötü dilimde max DD > -%35
    """
    reasons = []
    if aggregate['count'] < 3:
        reasons.append(f"Yetersiz dilim ({aggregate['count']}/6) — anlamlı değerlendirme yok")
        return False, reasons

    profitable = aggregate.get('profitable_slices', 0)
    if profitable < 4:
        reasons.append(f"Sadece {profitable}/6 dilimde kârlı (min 4 gerekli)")

    if aggregate.get('avg_sharpe', 0) < 0.3:
        reasons.append(f"Ortalama Sharpe düşük: {aggregate.get('avg_sharpe', 0):.2f} < 0.3")

    if aggregate.get('worst_drawdown_pct', 0) < -35:
        reasons.append(f"En kötü dilim DD: {aggregate.get('worst_drawdown_pct', 0):.1f}% < -35% limit")

    return (len(reasons) == 0, reasons)


def _format_summary(label, slice_results, aggregate, gate_passed, gate_reasons) -> str:
    """Konsol raporu."""
    lines = []
    lines.append('═' * 70)
    lines.append(f'  WALK-FORWARD RAPORU: {label}')
    lines.append('═' * 70)
    lines.append('')
    lines.append(f'  {"DİLİM":<32} {"RET%":>7} {"SHARPE":>7} {"PF":>5} {"DD%":>7} {"TRD":>4}')
    lines.append('  ' + '─' * 66)

    for s in slice_results:
        if s.get('skipped'):
            lines.append(f'  {s["label"][:32]:<32} {"SKIP":>7} {"-":>7} {"-":>5} {"-":>7} {"-":>4}  ({s.get("reason", "")})')
            continue
        m = s['metrics']
        lines.append(
            f'  {s["label"][:32]:<32} '
            f'{m["total_return_pct"]:>+7.2f} '
            f'{m["sharpe"]:>7.2f} '
            f'{m["profit_factor"]:>5.2f} '
            f'{m["max_drawdown_pct"]:>7.2f} '
            f'{m["sell_count"]:>4}'
        )

    lines.append('  ' + '─' * 66)
    lines.append('')
    lines.append('  AGREGAT:')
    lines.append(f'    Geçerli dilim:        {aggregate["count"]}/6')
    lines.append(f'    Ortalama getiri:      {aggregate.get("avg_return_pct", 0):+.2f}% (±{aggregate.get("std_return_pct", 0):.2f}%)')
    lines.append(f'    En iyi / En kötü:     {aggregate.get("best_return_pct", 0):+.2f}% / {aggregate.get("worst_return_pct", 0):+.2f}%')
    lines.append(f'    Ortalama Sharpe:      {aggregate.get("avg_sharpe", 0):.2f}')
    lines.append(f'    Ortalama PF:          {aggregate.get("avg_profit_factor", 0):.2f}')
    lines.append(f'    En kötü Max DD:       {aggregate.get("worst_drawdown_pct", 0):.2f}%')
    lines.append(f'    Kârlı dilim:          {aggregate.get("profitable_slices", 0)}/{aggregate["count"]} (PF > 1.0)')
    lines.append(f'    Pozitif getiri:       {aggregate.get("positive_slices", 0)}/{aggregate["count"]}')
    lines.append('')
    lines.append('  GATE KONTROLÜ:')
    if gate_passed:
        lines.append('    ✅ Canlıya alma kriterleri SAĞLANDI')
    else:
        lines.append('    ❌ Canlıya alma kriterleri SAĞLANMADI:')
        for r in gate_reasons:
            lines.append(f'      • {r}')
    lines.append('═' * 70)
    return '\n'.join(lines)


# ────────────────────────────────────────────────────────────────────
# Mevcut BacktestEngine'i wrap eden yardımcı
# ────────────────────────────────────────────────────────────────────

def existing_engine_runner(df_slice: pd.DataFrame, initial_balance: float) -> dict:
    """
    Mevcut backtest/engine.py'i walkforward'a uyumlu hale getirir.
    Trend bot'un baseline ölçümü için kullanılır.
    """
    from backtest.engine import BacktestEngine
    engine = BacktestEngine(initial_balance=initial_balance)
    result = engine.run(df_slice, verbose=False)

    portfolio_df = result.get('portfolio_history', pd.DataFrame())
    if portfolio_df.empty:
        # Hiç bar işlenmediyse boş equity döndür
        return {'equity_curve': pd.Series(dtype=float), 'trades': pd.DataFrame()}

    if 'timestamp' in portfolio_df.columns:
        portfolio_df = portfolio_df.set_index('timestamp')
    equity = portfolio_df['total_value']

    return {
        'equity_curve': equity,
        'trades': result.get('trades', pd.DataFrame()),
    }
