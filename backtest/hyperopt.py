"""
Bitcoin Trading Bot - Hyperopt (Optimizasyon) Modülü
Geçmiş veriler üzerinde farklı parametre değerlerini (Grid Search) dener
ve en yüksek kârı getiren ayar kombinasyonunu (Best Params) bulur.
"""
import itertools
import logging
import pandas as pd
from datetime import datetime

import config.settings
import analysis.indicators
import strategy.signals
from backtest.engine import BacktestEngine
from data.collector import DataCollector
from analysis.indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


class HyperOptimizer:
    """Belirli bir parametre kümesinde en optimum değerleri arar (Grid Search)."""

    def __init__(self, symbol, start_date, end_date, initial_balance=10000):
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.initial_balance = initial_balance
        self.best_result = None
        self.best_params = {}

    def _patch_params(self, params):
        """Dinamik olarak test edilecek ayarları global config dosyalarına enjekte eder."""
        if 'rsi_oversold' in params:
            config.settings.RSI_OVERSOLD = params['rsi_oversold']
            analysis.indicators.RSI_OVERSOLD = params['rsi_oversold']
        if 'rsi_overbought' in params:
            config.settings.RSI_OVERBOUGHT = params['rsi_overbought']
            analysis.indicators.RSI_OVERBOUGHT = params['rsi_overbought']
        if 'ema_short' in params:
            config.settings.EMA_SHORT = params['ema_short']
            analysis.indicators.EMA_SHORT = params['ema_short']
        if 'ema_long' in params:
            config.settings.EMA_LONG = params['ema_long']
            analysis.indicators.EMA_LONG = params['ema_long']
            strategy.signals.EMA_LONG = params['ema_long']
        if 'buy_threshold' in params:
            config.settings.BUY_THRESHOLD = params['buy_threshold']
            strategy.signals.BUY_THRESHOLD = params['buy_threshold']

    def optimize(self, scenarios):
        """
        Risk bazlı senaryo listesini alıp dener.
        Örnek scenarios: [{'name': 'Safe', 'rsi_oversold': 25...}, {'name': 'Degen', ...}]
        """
        logger.info(f"📥 {self.symbol} için {self.start_date} -> {self.end_date} verisi çekiliyor...")
        collector = DataCollector()
        df_raw = collector.fetch_historical_data(
            symbol=self.symbol,
            start_date=self.start_date,
            end_date=self.end_date
        )

        if df_raw.empty:
            logger.error("❌ Veri çekilemedi, optimizasyon iptal!")
            return None

        logger.info(f"🤖 HyperOpt başlatılıyor... Toplam {len(scenarios)} farklı strateji profili test edilecek.\n")

        results = []
        for index, p in enumerate(scenarios):
            profile_name = p.get('name', f"Senaryo {index+1}")
            self._patch_params(p)

            # İndikatörleri yeni ayarlarla baştan hesapla
            df = TechnicalIndicators.calculate_all(df_raw.copy())

            # Backtest çalıştır
            engine = BacktestEngine(initial_balance=self.initial_balance)
            res = engine.run(df, verbose=False)
            res['params'] = p
            results.append(res)

            logger.info(f"⚙️ [{profile_name}] | Kâr: %{res['total_return_percent']:>+6.2f} | P: {p}")

        # Optimizasyon Bitti - En iyi sonucu filtrele (Hiç işlem açamayanları ele)
        valid_results = [r for r in results if r['total_trades'] > 0]
        if not valid_results:
            logger.warning("⚠️ Hiçbir strateji kombinasyonu işlem fırsatı bulamadı.")
            return None

        # Net dönüş yüzdesine göre sırala ve zirveyi al
        self.best_result = max(valid_results, key=lambda x: x['total_return_percent'])
        self.best_params = self.best_result['params']

        logger.info(f"\n{'='*50}")
        logger.info(f"🏆 EN KÂRLI OPTİMİZASYON SONUCU")
        logger.info(f"{'='*50}")
        logger.info(f"✨ Parametreler : {self.best_params}")
        logger.info(f"💰 Net Getiri   : %{self.best_result['total_return_percent']:+.2f}")
        logger.info(f"🔄 İşlem Sayısı : {self.best_result['total_trades']}")
        logger.info(f"📈 Kazanma Oranı: %{self.best_result['win_rate']:.1f}")
        logger.info(f"📉 Max Drawdown : %{self.best_result['max_drawdown']:.2f}")
        logger.info(f"{'='*50}\n")

        return self.best_result
