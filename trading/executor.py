"""
Bitcoin Trading Bot - Emir Yürütme Modülü
Borsa üzerinde alım-satım emirlerini yürütür.
"""
import logging
from datetime import datetime
from data.collector import DataCollector
from data.storage import DataStorage
from config.settings import SYMBOL, TRADING_MODE

logger = logging.getLogger(__name__)


class TradeExecutor:
    """Alım-satım emirlerini yürütür."""

    def __init__(self, collector: DataCollector, storage: DataStorage):
        self.collector = collector
        self.storage = storage
        self.mode = TRADING_MODE

    def execute_buy(self, symbol=None, amount=None, price=None):
        """
        Alım emri yürütür.

        Args:
            symbol: İşlem çifti
            amount: BTC miktarı
            price: Limit fiyatı (None ise market order)

        Returns:
            dict: İşlem sonucu
        """
        symbol = symbol or SYMBOL

        try:
            if self.mode == 'backtest':
                # Backtest modunda simüle et
                result = {
                    'id': f"backtest_{datetime.now().timestamp()}",
                    'symbol': symbol,
                    'side': 'buy',
                    'price': price,
                    'amount': amount,
                    'cost': price * amount,
                    'fee': price * amount * 0.001,  # %0.1 komisyon
                    'timestamp': datetime.now(),
                    'status': 'filled',
                    'mode': 'backtest',
                }
            elif self.mode in ('paper', 'live'):
                if price:
                    # Limit order
                    order = self.collector.exchange.create_limit_buy_order(
                        symbol, amount, price
                    )
                else:
                    # Market order
                    order = self.collector.exchange.create_market_buy_order(
                        symbol, amount
                    )

                result = {
                    'id': order.get('id', ''),
                    'symbol': symbol,
                    'side': 'buy',
                    'price': order.get('average', order.get('price', price)),
                    'amount': order.get('filled', amount),
                    'cost': order.get('cost', 0),
                    'fee': order.get('fee', {}).get('cost', 0),
                    'timestamp': datetime.now(),
                    'status': order.get('status', 'unknown'),
                    'mode': self.mode,
                }
            else:
                raise ValueError(f"Bilinmeyen mod: {self.mode}")

            # İşlemi kaydet
            self.storage.save_trade({
                **result,
                'strategy': 'multi_indicator',
                'signal_reason': 'Sistem sinyali',
            })

            logger.info(
                f"🟢 ALIM EMRİ YÜRÜTÜLDÜ | "
                f"{amount:.6f} BTC @ ${result['price']:,.2f} | "
                f"Toplam: ${result['cost']:,.2f} | "
                f"Komisyon: ${result.get('fee', 0):,.2f}"
            )

            return result

        except Exception as e:
            logger.error(f"❌ Alım emri hatası: {e}")
            raise

    def execute_sell(self, symbol=None, amount=None, price=None):
        """
        Satım emri yürütür.

        Args:
            symbol: İşlem çifti
            amount: BTC miktarı
            price: Limit fiyatı (None ise market order)

        Returns:
            dict: İşlem sonucu
        """
        symbol = symbol or SYMBOL

        try:
            if self.mode == 'backtest':
                result = {
                    'id': f"backtest_{datetime.now().timestamp()}",
                    'symbol': symbol,
                    'side': 'sell',
                    'price': price,
                    'amount': amount,
                    'cost': price * amount,
                    'fee': price * amount * 0.001,
                    'timestamp': datetime.now(),
                    'status': 'filled',
                    'mode': 'backtest',
                }
            elif self.mode in ('paper', 'live'):
                if price:
                    order = self.collector.exchange.create_limit_sell_order(
                        symbol, amount, price
                    )
                else:
                    order = self.collector.exchange.create_market_sell_order(
                        symbol, amount
                    )

                result = {
                    'id': order.get('id', ''),
                    'symbol': symbol,
                    'side': 'sell',
                    'price': order.get('average', order.get('price', price)),
                    'amount': order.get('filled', amount),
                    'cost': order.get('cost', 0),
                    'fee': order.get('fee', {}).get('cost', 0),
                    'timestamp': datetime.now(),
                    'status': order.get('status', 'unknown'),
                    'mode': self.mode,
                }
            else:
                raise ValueError(f"Bilinmeyen mod: {self.mode}")

            self.storage.save_trade({
                **result,
                'strategy': 'multi_indicator',
                'signal_reason': 'Sistem sinyali',
            })

            logger.info(
                f"🔴 SATIM EMRİ YÜRÜTÜLDÜ | "
                f"{amount:.6f} BTC @ ${result['price']:,.2f} | "
                f"Toplam: ${result['cost']:,.2f} | "
                f"Komisyon: ${result.get('fee', 0):,.2f}"
            )

            return result

        except Exception as e:
            logger.error(f"❌ Satım emri hatası: {e}")
            raise

    def get_open_orders(self, symbol=None):
        """Açık emirleri listeler."""
        symbol = symbol or SYMBOL
        if self.mode == 'backtest':
            return []
        try:
            return self.collector.exchange.fetch_open_orders(symbol)
        except Exception as e:
            logger.error(f"❌ Açık emir sorgulama hatası: {e}")
            return []

    def cancel_order(self, order_id, symbol=None):
        """Bir emri iptal eder."""
        symbol = symbol or SYMBOL
        if self.mode == 'backtest':
            return True
        try:
            self.collector.exchange.cancel_order(order_id, symbol)
            logger.info(f"🚫 Emir iptal edildi: {order_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Emir iptal hatası: {e}")
            return False
