"""
Bot Base Class — tüm botların ortak yüzeyi.

Sözleşme:
    - step(now)       : Tek döngü çalıştırır (dakikalar/saatler arası çağrılır)
    - current_value() : Bot'un USDT cinsinden mevcut değerini döndürür (PM'ye rapor)
    - backtest(df)    : Backtest için equity curve + trades üretir (walkforward'la uyumlu)
    - save_state()    : State'i disk'e yazar
    - load_state()    : State'i disk'ten okur

State persistance:
    Her bot data/bot_state_<name>.json dosyasına kendi durumunu yazar.
    Restart sonrası bot kaldığı yerden devam eder.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

BOT_STATE_DIR = Path(__file__).parent.parent / 'data'


class BotBase(ABC):
    """Her bot bu sınıftan türemeli."""

    name: str = 'base'

    def __init__(self, portfolio_manager=None):
        self.portfolio_manager = portfolio_manager
        self.state_path = BOT_STATE_DIR / f'bot_state_{self.name}.json'
        self.last_error: str | None = None
        self.last_step_at: str | None = None

    # ───────────── Abstract API ─────────────

    @abstractmethod
    def step(self, now: datetime) -> None:
        """
        Tek döngü çalıştır. Sinyal değerlendir, gerekirse emir aç/kapat.
        Live ve paper modda main loop tarafından çağrılır.
        """
        ...

    @abstractmethod
    def current_value(self) -> float:
        """Bot'un USDT cinsinden güncel toplam değeri (cash + pozisyon mark-to-market)."""
        ...

    def backtest(self, df: pd.DataFrame, initial_balance: float = 1000.0) -> dict:
        """
        Backtest entry point — walkforward framework ile uyumlu.
        Default implementation alt sınıf override etmelidir.
        """
        raise NotImplementedError(f"{self.name}: backtest() override edilmeli")

    # ───────────── Helpers ─────────────

    def report_to_portfolio(self) -> None:
        """Bot'un güncel değerini portföy yöneticisine bildirir."""
        if self.portfolio_manager is None:
            return
        try:
            value = self.current_value()
            self.portfolio_manager.report_bot_value(self.name, value)
        except Exception as e:
            logger.error(f"[{self.name}] Portföy raporu başarısız: {e}")

    def is_paused(self) -> bool:
        """Portföy yöneticisi kill-switch tetiklediyse veya bot suspend ise True."""
        if self.portfolio_manager is None:
            return False
        if self.portfolio_manager.check_kill_switch():
            return True
        bot_state = self.portfolio_manager.bots.get(self.name)
        if bot_state and (bot_state.suspended or not bot_state.enabled):
            return True
        return False

    # ───────────── State Persistence ─────────────

    def save_state(self, state: dict) -> None:
        """State'i disk'e atomik olarak yaz."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        state['_saved_at'] = datetime.utcnow().isoformat(timespec='seconds')
        tmp = self.state_path.with_suffix('.tmp')
        with open(tmp, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        tmp.replace(self.state_path)

    def load_state(self) -> dict | None:
        """Disk'ten state oku. Yoksa None."""
        if not self.state_path.exists():
            return None
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[{self.name}] State yüklenemedi: {e}")
            return None
