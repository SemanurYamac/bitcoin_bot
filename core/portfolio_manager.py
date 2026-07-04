"""
Portföy Yöneticisi — 3 botu ortak sermaye altında koordine eder.

Sorumluluklar:
    1. Bot kaydı (registry) — hangi botlar aktif, hedef ağırlıkları ne
    2. Sermaye dağıtımı — hedef ağırlıklara göre $400 → 40/40/20 = 160/160/80
    3. Aylık ekleme protokolü — $200 eklenince hedef ağırlık korunarak dağıtılır
    4. Kill-switch — portföy -%15'i aşarsa tüm botlar pause
    5. Per-bot performans takibi (high-water mark)
    6. State persistence — JSON dosyasına yazar, restart'ta okur

State şeması (data/portfolio_state.json):
    {
      "total_capital": 400.0,
      "deposit_history": [{"ts": ..., "amount": 400.0, "note": "initial"}],
      "kill_switch_triggered": false,
      "kill_switch_reason": null,
      "bots": {
        "dca": {"capital": 160.0, "target_weight": 0.4, "enabled": true,
                "high_water_mark": 160.0, "current_value": 160.0,
                "started_at": "...", "last_update": "..."},
        ...
      }
    }

Kullanım:
    from core.portfolio_manager import PortfolioManager, BotConfig

    pm = PortfolioManager.load_or_create(
        total_capital=400.0,
        bots=[
            BotConfig('dca',   target_weight=0.40, enabled=True),
            BotConfig('grid',  target_weight=0.40, enabled=True),
            BotConfig('trend', target_weight=0.20, enabled=True),
        ],
    )
    capital = pm.get_allocation('dca')   # 160.0
    pm.report_bot_value('dca', 165.30)   # bot her döngüde değerini günceller
    if pm.check_kill_switch():
        # tüm botları durdur
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)


PORTFOLIO_STATE_PATH = Path(__file__).parent.parent / 'data' / 'portfolio_state.json'

# Kill-switch eşiği: peak'ten %15 düşüş tüm botları durdurur
KILL_SWITCH_DD_THRESHOLD = 0.15

# Per-bot suspend eşikleri (rapor amaçlı, pm otomatik suspend etmez —
# bot kendi kararı verir veya operatör görür)
BOT_SUSPEND_DD = 0.30      # %30 düşüş
BOT_SUSPEND_DAYS = 14      # ve 14 gün geçmiş


@dataclass
class BotConfig:
    name: str
    target_weight: float       # 0.0-1.0
    enabled: bool = True


@dataclass
class BotState:
    name: str
    target_weight: float
    capital: float = 0.0           # PM'nin bota tahsis ettiği sermaye (history)
    current_value: float = 0.0     # Bot'un beyan ettiği güncel değer
    high_water_mark: float = 0.0   # En yüksek görülen değer
    enabled: bool = True
    suspended: bool = False        # Operatör veya kural ile durduruldu
    suspend_reason: str | None = None
    started_at: str = ''
    last_update: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


class PortfolioManager:
    """
    Tüm botların ortak sermaye yöneticisi.
    Thread-safe (her bot ayrı thread'de değer raporlayabilir).
    """

    def __init__(self, total_capital: float, bots: list[BotConfig]):
        self._lock = Lock()
        self.total_capital = total_capital
        self.deposit_history: list[dict] = []
        self.kill_switch_triggered = False
        self.kill_switch_reason: str | None = None
        self.peak_total_value = total_capital
        self.bots: dict[str, BotState] = {}

        for cfg in bots:
            allocation = total_capital * cfg.target_weight
            self.bots[cfg.name] = BotState(
                name=cfg.name,
                target_weight=cfg.target_weight,
                capital=allocation,
                current_value=allocation,
                high_water_mark=allocation,
                enabled=cfg.enabled,
                started_at=datetime.utcnow().isoformat(timespec='seconds'),
                last_update=datetime.utcnow().isoformat(timespec='seconds'),
            )

        self.deposit_history.append({
            'ts': datetime.utcnow().isoformat(timespec='seconds'),
            'amount': total_capital,
            'note': 'initial',
        })

    # ───────────── Persistence ─────────────

    @classmethod
    def load_or_create(cls, total_capital: float, bots: list[BotConfig], state_path: Path | None = None) -> 'PortfolioManager':
        """
        Disk'ten state yükler. Yoksa yeni oluşturur.
        Mevcut state'te tanımlı olmayan yeni bot eklenirse PM'ye katılır.
        """
        path = state_path or PORTFOLIO_STATE_PATH
        if path.exists():
            try:
                pm = cls._load(path)
                # Yeni eklenen botları kontrol et
                for cfg in bots:
                    if cfg.name not in pm.bots:
                        allocation = pm.total_capital * cfg.target_weight
                        pm.bots[cfg.name] = BotState(
                            name=cfg.name,
                            target_weight=cfg.target_weight,
                            capital=allocation,
                            current_value=allocation,
                            high_water_mark=allocation,
                            enabled=cfg.enabled,
                            started_at=datetime.utcnow().isoformat(timespec='seconds'),
                            last_update=datetime.utcnow().isoformat(timespec='seconds'),
                        )
                        logger.info(f"➕ Yeni bot eklendi: {cfg.name} (target={cfg.target_weight})")
                pm._state_path = path
                return pm
            except Exception as e:
                logger.error(f"❌ Portföy state yüklenemedi: {e} — yeni state oluşturulacak")

        pm = cls(total_capital=total_capital, bots=bots)
        pm._state_path = path
        pm.save()
        return pm

    @classmethod
    def _load(cls, path: Path) -> 'PortfolioManager':
        with open(path) as f:
            data = json.load(f)

        bot_configs = [
            BotConfig(name=bs['name'], target_weight=bs['target_weight'], enabled=bs.get('enabled', True))
            for bs in data['bots'].values()
        ]
        pm = cls(total_capital=data['total_capital'], bots=bot_configs)
        pm.deposit_history = data.get('deposit_history', [])
        pm.kill_switch_triggered = data.get('kill_switch_triggered', False)
        pm.kill_switch_reason = data.get('kill_switch_reason')
        pm.peak_total_value = data.get('peak_total_value', pm.total_capital)

        # Bot state'lerini yükle
        for name, bs in data['bots'].items():
            pm.bots[name] = BotState(
                name=bs['name'],
                target_weight=bs['target_weight'],
                capital=bs.get('capital', 0.0),
                current_value=bs.get('current_value', 0.0),
                high_water_mark=bs.get('high_water_mark', 0.0),
                enabled=bs.get('enabled', True),
                suspended=bs.get('suspended', False),
                suspend_reason=bs.get('suspend_reason'),
                started_at=bs.get('started_at', ''),
                last_update=bs.get('last_update', ''),
            )

        logger.info(f"📂 Portföy state yüklendi: total={pm.total_capital:.2f}, bots={list(pm.bots.keys())}")
        return pm

    def save(self):
        """State'i disk'e yaz (atomic — temp file + rename)."""
        path = getattr(self, '_state_path', PORTFOLIO_STATE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'total_capital': self.total_capital,
            'deposit_history': self.deposit_history,
            'kill_switch_triggered': self.kill_switch_triggered,
            'kill_switch_reason': self.kill_switch_reason,
            'peak_total_value': self.peak_total_value,
            'bots': {name: bs.to_dict() for name, bs in self.bots.items()},
        }
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)

    # ───────────── Allocation ─────────────

    def get_allocation(self, bot_name: str) -> float:
        """Bot'a tahsis edilmiş sermaye (USDT). Tarihsel — bot bunu hedef alır."""
        with self._lock:
            if bot_name not in self.bots:
                return 0.0
            return self.bots[bot_name].capital

    def report_bot_value(self, bot_name: str, current_value: float) -> None:
        """
        Bot kendi güncel değerini raporlar (her döngüde).
        Kill-switch hesabı için kritik.
        """
        with self._lock:
            if bot_name not in self.bots:
                logger.warning(f"⚠️ Bilinmeyen bot raporu: {bot_name}")
                return
            bs = self.bots[bot_name]
            bs.current_value = current_value
            bs.high_water_mark = max(bs.high_water_mark, current_value)
            bs.last_update = datetime.utcnow().isoformat(timespec='seconds')

            # Portföy peak güncellemesi
            total_value = sum(b.current_value for b in self.bots.values())
            self.peak_total_value = max(self.peak_total_value, total_value)

            self.save()

    def total_value(self) -> float:
        """Tüm botların güncel toplam değeri."""
        with self._lock:
            return sum(b.current_value for b in self.bots.values())

    # ───────────── Kill-Switch ─────────────

    def check_kill_switch(self) -> bool:
        """
        Portföy peak'ten %15+ düştüyse kill-switch tetiklenir.
        Bir kez tetiklendi mi reset edilene kadar True döner.
        """
        with self._lock:
            if self.kill_switch_triggered:
                return True

            current = sum(b.current_value for b in self.bots.values())
            if self.peak_total_value <= 0:
                return False
            dd = (self.peak_total_value - current) / self.peak_total_value
            if dd >= KILL_SWITCH_DD_THRESHOLD:
                self.kill_switch_triggered = True
                self.kill_switch_reason = (
                    f"Portföy DD %{dd*100:.1f} ≥ %{KILL_SWITCH_DD_THRESHOLD*100:.0f} eşiği "
                    f"(peak ${self.peak_total_value:.2f} → şimdi ${current:.2f})"
                )
                logger.critical(f"🚨 KILL-SWITCH TETİKLENDİ: {self.kill_switch_reason}")
                self.save()
                return True
            return False

    def reset_kill_switch(self, operator_note: str = '') -> None:
        """Operatör müdahalesi — kill-switch'i resetler."""
        with self._lock:
            self.kill_switch_triggered = False
            self.kill_switch_reason = None
            self.peak_total_value = sum(b.current_value for b in self.bots.values())
            logger.warning(f"🔓 Kill-switch operatör tarafından resetlendi: {operator_note}")
            self.save()

    # ───────────── Capital Lifecycle ─────────────

    def deposit(self, amount: float, note: str = 'monthly_addition') -> dict:
        """
        Yeni sermaye ekle — hedef ağırlıklara göre dağıt.
        Aylık $200 ekleme buradan geçer.

        Returns:
            dict[bot_name, added_amount]
        """
        with self._lock:
            if amount <= 0:
                return {}

            distribution = {}
            for name, bs in self.bots.items():
                if not bs.enabled or bs.suspended:
                    continue
                added = amount * bs.target_weight
                bs.capital += added
                bs.current_value += added
                bs.high_water_mark += added  # ekleme HWM'i bozmaz
                distribution[name] = round(added, 2)

            self.total_capital += amount
            self.deposit_history.append({
                'ts': datetime.utcnow().isoformat(timespec='seconds'),
                'amount': amount,
                'note': note,
            })
            self.save()
            logger.info(f"💰 Sermaye eklendi: ${amount:.2f} → {distribution}")
            return distribution

    def suspend_bot(self, bot_name: str, reason: str) -> None:
        with self._lock:
            if bot_name not in self.bots:
                return
            self.bots[bot_name].suspended = True
            self.bots[bot_name].suspend_reason = reason
            logger.warning(f"⏸️ Bot askıya alındı: {bot_name} — {reason}")
            self.save()

    def resume_bot(self, bot_name: str) -> None:
        with self._lock:
            if bot_name not in self.bots:
                return
            self.bots[bot_name].suspended = False
            self.bots[bot_name].suspend_reason = None
            logger.info(f"▶️ Bot devam ediyor: {bot_name}")
            self.save()

    # ───────────── Reporting ─────────────

    def report(self) -> dict:
        """Toplu durum raporu."""
        with self._lock:
            current = sum(b.current_value for b in self.bots.values())
            total_pnl = current - self.total_capital
            total_pnl_pct = (total_pnl / self.total_capital * 100) if self.total_capital > 0 else 0
            dd_pct = ((self.peak_total_value - current) / self.peak_total_value * 100) if self.peak_total_value > 0 else 0

            bot_reports = {}
            for name, bs in self.bots.items():
                pnl = bs.current_value - bs.capital
                pnl_pct = (pnl / bs.capital * 100) if bs.capital > 0 else 0
                bot_dd = ((bs.high_water_mark - bs.current_value) / bs.high_water_mark * 100) if bs.high_water_mark > 0 else 0
                bot_reports[name] = {
                    'capital': round(bs.capital, 2),
                    'current_value': round(bs.current_value, 2),
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'high_water_mark': round(bs.high_water_mark, 2),
                    'drawdown_pct': round(bot_dd, 2),
                    'enabled': bs.enabled,
                    'suspended': bs.suspended,
                    'suspend_reason': bs.suspend_reason,
                    'last_update': bs.last_update,
                }

            return {
                'total_capital_deposited': round(self.total_capital, 2),
                'current_value': round(current, 2),
                'total_pnl': round(total_pnl, 2),
                'total_pnl_pct': round(total_pnl_pct, 2),
                'peak_value': round(self.peak_total_value, 2),
                'current_drawdown_pct': round(dd_pct, 2),
                'kill_switch_triggered': self.kill_switch_triggered,
                'kill_switch_reason': self.kill_switch_reason,
                'bots': bot_reports,
            }

    def format_report(self) -> str:
        """Konsol için biçimli rapor."""
        r = self.report()
        lines = []
        lines.append('═' * 65)
        lines.append('  PORTFÖY DURUMU')
        lines.append('═' * 65)
        lines.append(f"  Yatırılan:       ${r['total_capital_deposited']:.2f}")
        lines.append(f"  Güncel Değer:    ${r['current_value']:.2f}")
        lines.append(f"  Toplam P&L:      ${r['total_pnl']:+.2f} ({r['total_pnl_pct']:+.2f}%)")
        lines.append(f"  Peak:            ${r['peak_value']:.2f}")
        lines.append(f"  Şu anki DD:      {r['current_drawdown_pct']:.2f}%")
        if r['kill_switch_triggered']:
            lines.append(f"  🚨 KILL-SWITCH:  {r['kill_switch_reason']}")
        lines.append('  ─' * 32)
        lines.append(f"  {'BOT':<10} {'TAHSİS':>10} {'DEĞER':>10} {'P&L':>10} {'P&L%':>7} {'DD%':>6} {'DURUM':<10}")
        for name, bot in r['bots'].items():
            status = 'SUSPEND' if bot['suspended'] else ('AKTİF' if bot['enabled'] else 'KAPALI')
            lines.append(
                f"  {name:<10} ${bot['capital']:>8.2f} ${bot['current_value']:>8.2f} "
                f"${bot['pnl']:>+8.2f} {bot['pnl_pct']:>+6.2f}% {bot['drawdown_pct']:>5.1f}% {status:<10}"
            )
        lines.append('═' * 65)
        return '\n'.join(lines)
