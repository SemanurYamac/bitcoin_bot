"""
Standart performans metrikleri — exchange/strateji agnostic.

Tüm botlar (DCA / Grid / Trend) ve walkforward framework'ü buradaki
fonksiyonları kullanır. Tek doğru kaynak (single source of truth) burası.

Girdi:
    equity_curve: pd.Series
        - Index: DateTime (timezone-aware veya naive farketmez)
        - Values: Toplam portföy değeri (USDT veya TL)
        - Sıralı, ardışık, NaN içermemeli
    trades: pd.DataFrame veya list[dict]
        - 'pnl' sütunu net P&L (komisyon dahil) içermelidir
        - 'side' sütunu 'sell' kapalı pozisyonları işaretler (varsa)

Çıktı:
    dict — tüm metrikler tek seferde

Felsefe:
    - Tüm oranlar yıllıklaştırılır (annualization auto-detected)
    - Sıfır sapma / sıfıra bölme korumalı
    - Tek işlem yokken bile NaN değil 0 döner (raporda kolay)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ────────────────────────────────────────────────────────────────────
# Yardımcı: Yıllıklaştırma faktörü
# ────────────────────────────────────────────────────────────────────

def _periods_per_year(index: pd.DatetimeIndex) -> float:
    """
    Index'in median bar süresinden yıllık period sayısını çıkarır.
    15m → 35040, 1h → 8760, 4h → 2190, 1d → 365.

    Yetersiz veri varsa varsayılan: 8760 (saatlik).
    """
    if len(index) < 2:
        return 8760.0
    diffs = pd.Series(index).diff().dropna()
    if diffs.empty:
        return 8760.0
    median_seconds = diffs.median().total_seconds()
    if median_seconds <= 0:
        return 8760.0
    return 365.25 * 24 * 3600 / median_seconds


# ────────────────────────────────────────────────────────────────────
# Risk-adjusted return ölçütleri
# ────────────────────────────────────────────────────────────────────

def total_return(equity: pd.Series) -> float:
    """Toplam getiri (%)."""
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    return (equity.iloc[-1] - equity.iloc[0]) / equity.iloc[0] * 100


def cagr(equity: pd.Series) -> float:
    """Compound Annual Growth Rate (%)."""
    if len(equity) < 2 or equity.iloc[0] <= 0 or equity.iloc[-1] <= 0:
        return 0.0
    days = (equity.index[-1] - equity.index[0]).total_seconds() / 86400
    if days < 1:
        return 0.0
    years = days / 365.25
    if years <= 0:
        return 0.0
    return ((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) * 100


def sharpe_ratio(equity: pd.Series, risk_free_rate: float = 0.0) -> float:
    """
    Yıllıklaştırılmış Sharpe oranı.

    Sharpe = (mean(returns) - rf/N) / std(returns) × sqrt(N)
    """
    if len(equity) < 3:
        return 0.0
    returns = equity.pct_change().dropna()
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    n = _periods_per_year(equity.index)
    excess = returns.mean() - (risk_free_rate / n)
    return float(excess / returns.std() * np.sqrt(n))


def sortino_ratio(equity: pd.Series, risk_free_rate: float = 0.0) -> float:
    """
    Yıllıklaştırılmış Sortino — sadece downside volatility.
    Sharpe'ın yukarı dalgalanmayı cezalandırma sorununu çözer.
    """
    if len(equity) < 3:
        return 0.0
    returns = equity.pct_change().dropna()
    if len(returns) < 2:
        return 0.0
    n = _periods_per_year(equity.index)
    excess = returns - (risk_free_rate / n)
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() == 0:
        # Hiç negatif return yoksa "sonsuz" Sortino → büyük ama sonlu rakam dön
        return 99.0 if returns.mean() > 0 else 0.0
    return float(excess.mean() / downside.std() * np.sqrt(n))


def max_drawdown(equity: pd.Series) -> tuple[float, int]:
    """
    Max drawdown (%, negatif) ve kaç bar sürdüğü.

    Returns:
        (max_dd_pct, duration_bars)
        max_dd_pct: Negatif yüzde (örn -23.5)
    """
    if len(equity) < 2:
        return 0.0, 0
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = dd.min() * 100

    # Duration: peak'ten dip'e kaç bar
    dd_argmin_pos = int(dd.values.argmin())
    if dd_argmin_pos == 0:
        duration = 0
    else:
        peak_value = peak.iloc[dd_argmin_pos]
        peak_pos = int((equity.iloc[:dd_argmin_pos + 1] >= peak_value).values.argmax())
        duration = dd_argmin_pos - peak_pos

    return float(max_dd), duration


def calmar_ratio(equity: pd.Series) -> float:
    """Calmar = CAGR / |Max DD|. Drawdown'a duyarlı en sert oran."""
    cagr_val = cagr(equity)
    dd, _ = max_drawdown(equity)
    if dd == 0:
        return 99.0 if cagr_val > 0 else 0.0
    return float(cagr_val / abs(dd))


# ────────────────────────────────────────────────────────────────────
# Trade-level ölçütler
# ────────────────────────────────────────────────────────────────────

def _normalize_trades(trades) -> pd.DataFrame:
    """list[dict] veya DataFrame'i tutarlı DataFrame'e çevirir."""
    if isinstance(trades, pd.DataFrame):
        df = trades
    elif isinstance(trades, list):
        if not trades:
            return pd.DataFrame(columns=['pnl', 'side'])
        df = pd.DataFrame(trades)
    else:
        return pd.DataFrame(columns=['pnl', 'side'])

    if 'pnl' not in df.columns:
        df = df.copy()
        df['pnl'] = 0.0
    return df


def _closed_trades(trades) -> pd.DataFrame:
    """
    Sadece kapatma işlemlerini döndürür ('sell' veya 'partial_sell').
    Bunlar pnl içerir; 'buy' satırlarının pnl'i 0'dır.
    """
    df = _normalize_trades(trades)
    if df.empty:
        return df
    if 'side' in df.columns:
        return df[df['side'].isin(['sell', 'partial_sell'])].copy()
    # side yoksa pnl != 0 olanları al
    return df[df['pnl'] != 0].copy()


def win_rate(trades) -> float:
    """Kazanan kapatma yüzdesi."""
    closed = _closed_trades(trades)
    if closed.empty:
        return 0.0
    wins = (closed['pnl'] > 0).sum()
    return float(wins / len(closed) * 100)


def profit_factor(trades) -> float:
    """
    Profit factor = Σ kazançlar / |Σ kayıplar|

    > 1.0 kârlı strateji
    > 1.5 sağlam
    > 2.0 mükemmel (overfit şüphesi)
    """
    closed = _closed_trades(trades)
    if closed.empty:
        return 0.0
    gross_win = closed.loc[closed['pnl'] > 0, 'pnl'].sum()
    gross_loss = closed.loc[closed['pnl'] < 0, 'pnl'].sum()
    if gross_loss == 0:
        return 99.0 if gross_win > 0 else 0.0
    return float(gross_win / abs(gross_loss))


def expectancy(trades) -> float:
    """
    İşlem başına beklenen değer (USDT).
    Expectancy = win_rate × avg_win − loss_rate × |avg_loss|
    """
    closed = _closed_trades(trades)
    if closed.empty:
        return 0.0
    wins = closed[closed['pnl'] > 0]['pnl']
    losses = closed[closed['pnl'] < 0]['pnl']
    n = len(closed)
    win_pct = len(wins) / n
    loss_pct = len(losses) / n
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.0
    return float(win_pct * avg_win - loss_pct * avg_loss)


def avg_win_loss(trades) -> tuple[float, float]:
    """(avg_win, avg_loss) — avg_loss pozitif değer olarak döner."""
    closed = _closed_trades(trades)
    if closed.empty:
        return 0.0, 0.0
    wins = closed[closed['pnl'] > 0]['pnl']
    losses = closed[closed['pnl'] < 0]['pnl']
    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.0
    return avg_win, avg_loss


def trade_counts(trades) -> dict:
    """Buy / Sell / Partial sayıları."""
    df = _normalize_trades(trades)
    if df.empty or 'side' not in df.columns:
        return {'buy': 0, 'sell': 0, 'partial_sell': 0, 'total': 0}
    return {
        'buy': int((df['side'] == 'buy').sum()),
        'sell': int((df['side'] == 'sell').sum()),
        'partial_sell': int((df['side'] == 'partial_sell').sum()),
        'total': int(len(df)),
    }


# ────────────────────────────────────────────────────────────────────
# Toplu rapor
# ────────────────────────────────────────────────────────────────────

def compute_metrics(equity: pd.Series, trades=None) -> dict:
    """
    Bir equity curve + trade listesinden tam metrik raporu üretir.
    Walkforward, backtest, canlı reporting hepsi bunu çağırır.
    """
    if not isinstance(equity, pd.Series):
        equity = pd.Series(equity)
    if not isinstance(equity.index, pd.DatetimeIndex):
        equity.index = pd.to_datetime(equity.index)

    dd, dd_duration = max_drawdown(equity)
    avg_w, avg_l = avg_win_loss(trades) if trades is not None else (0.0, 0.0)
    counts = trade_counts(trades) if trades is not None else {'buy': 0, 'sell': 0, 'partial_sell': 0, 'total': 0}

    return {
        # Equity ölçütleri
        'total_return_pct': round(total_return(equity), 2),
        'cagr_pct': round(cagr(equity), 2),
        'sharpe': round(sharpe_ratio(equity), 2),
        'sortino': round(sortino_ratio(equity), 2),
        'calmar': round(calmar_ratio(equity), 2),
        'max_drawdown_pct': round(dd, 2),
        'max_drawdown_bars': dd_duration,
        # Trade ölçütleri
        'win_rate_pct': round(win_rate(trades), 2) if trades is not None else 0.0,
        'profit_factor': round(profit_factor(trades), 2) if trades is not None else 0.0,
        'expectancy': round(expectancy(trades), 2) if trades is not None else 0.0,
        'avg_win': round(avg_w, 2),
        'avg_loss': round(avg_l, 2),
        'rr_ratio': round(avg_w / avg_l, 2) if avg_l > 0 else 0.0,
        # Counts
        'buy_count': counts['buy'],
        'sell_count': counts['sell'],
        'partial_count': counts['partial_sell'],
        # Time
        'start_date': str(equity.index[0]),
        'end_date': str(equity.index[-1]),
        'days': round((equity.index[-1] - equity.index[0]).total_seconds() / 86400, 1),
    }


def format_report(metrics: dict, title: str = '') -> str:
    """Metrikleri konsol raporu olarak biçimlendirir."""
    lines = []
    if title:
        lines.append('═' * 60)
        lines.append(f'  {title}')
        lines.append('═' * 60)
    lines.append(f"  Dönem:           {metrics.get('start_date', '?')[:10]} → {metrics.get('end_date', '?')[:10]} ({metrics.get('days', 0):.0f} gün)")
    lines.append(f"  Toplam Getiri:   {metrics.get('total_return_pct', 0):+.2f}%")
    lines.append(f"  CAGR:            {metrics.get('cagr_pct', 0):+.2f}%")
    lines.append(f"  Sharpe:          {metrics.get('sharpe', 0):.2f}")
    lines.append(f"  Sortino:         {metrics.get('sortino', 0):.2f}")
    lines.append(f"  Calmar:          {metrics.get('calmar', 0):.2f}")
    lines.append(f"  Max DD:          {metrics.get('max_drawdown_pct', 0):.2f}% ({metrics.get('max_drawdown_bars', 0)} bar)")
    lines.append('  ─' * 30)
    lines.append(f"  Win Rate:        {metrics.get('win_rate_pct', 0):.1f}%")
    lines.append(f"  Profit Factor:   {metrics.get('profit_factor', 0):.2f}")
    lines.append(f"  Expectancy:      ${metrics.get('expectancy', 0):+.2f} / işlem")
    lines.append(f"  Avg Win/Loss:    ${metrics.get('avg_win', 0):.2f} / ${metrics.get('avg_loss', 0):.2f} (R:R {metrics.get('rr_ratio', 0):.2f})")
    lines.append(f"  İşlem Sayısı:    {metrics.get('buy_count', 0)} alış / {metrics.get('sell_count', 0)} satış")
    return '\n'.join(lines)


# ────────────────────────────────────────────────────────────────────
# Hızlı sağlık kontrolü
# ────────────────────────────────────────────────────────────────────

def is_strategy_acceptable(metrics: dict, strict: bool = False) -> tuple[bool, list[str]]:
    """
    Bir stratejinin canlıya çıkma kriterlerini sağlayıp sağlamadığını kontrol eder.
    Plan'daki gate kriterleri:
      - Profit factor > 1.0 (strict: > 1.2)
      - Max drawdown > -%35
      - Sharpe > 0.3 (strict: > 0.5)
      - Win rate > %35

    Returns:
        (acceptable: bool, reasons: list[str])
    """
    pf_min = 1.2 if strict else 1.0
    sharpe_min = 0.5 if strict else 0.3

    reasons = []
    if metrics.get('profit_factor', 0) < pf_min:
        reasons.append(f"Profit factor düşük: {metrics.get('profit_factor', 0):.2f} < {pf_min}")
    if metrics.get('max_drawdown_pct', 0) < -35:
        reasons.append(f"Max DD çok yüksek: {metrics.get('max_drawdown_pct', 0):.1f}% (min: -35%)")
    if metrics.get('sharpe', 0) < sharpe_min:
        reasons.append(f"Sharpe düşük: {metrics.get('sharpe', 0):.2f} < {sharpe_min}")
    if metrics.get('win_rate_pct', 0) < 35:
        reasons.append(f"Win rate düşük: {metrics.get('win_rate_pct', 0):.1f}% < 35%")

    return (len(reasons) == 0, reasons)
