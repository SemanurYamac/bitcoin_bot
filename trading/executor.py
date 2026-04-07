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

                status = order.get('status', 'unknown')
                
                # Gerçekten alınan miktarı borsadan çek
                filled_amount = order.get('filled')
                if filled_amount is None:
                    filled_amount = amount  # CCXT fallback
                    
                actual_price = order.get('average') or order.get('price') or price
                actual_cost = order.get('cost', filled_amount * (actual_price or 0))

                # Kısmi gerçekleşme (Partial Fill) Yönetimi
                if status in ('open', 'partially_filled') and filled_amount < amount:
                    logger.warning(
                        f"⚠️ KISMİ GERÇEKLEŞME (Partial Fill) tespit edildi! "
                        f"İstenen: {amount:.8f}, Alınan: {filled_amount:.8f}"
                    )
                    if filled_amount <= 0:
                        logger.error(f"❌ Alım hiç gerçekleşmedi (Filled: 0). Bekleyen emir iptal ediliyor.")
                        self.cancel_order(order.get('id'), symbol)
                        return None

                result = {
                    'id': order.get('id', ''),
                    'symbol': symbol,
                    'side': 'buy',
                    'price': actual_price,
                    'amount': filled_amount,
                    'cost': actual_cost,
                    'fee': order.get('fee', {}).get('cost', 0) if isinstance(order.get('fee'), dict) else 0,
                    'timestamp': datetime.now(),
                    'status': status,
                    'mode': self.mode,
                    'partial_fill': (filled_amount < amount)
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
                f"{result['amount']:.6f} {symbol} @ ${result['price']:,.2f} | "
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

                status = order.get('status', 'unknown')
                
                # Gerçekten satılan miktarı borsadan çek
                filled_amount = order.get('filled')
                if filled_amount is None:
                    filled_amount = amount
                    
                actual_price = order.get('average') or order.get('price') or price
                actual_cost = order.get('cost', filled_amount * (actual_price or 0))

                if status in ('open', 'partially_filled') and filled_amount < amount:
                    logger.warning(
                        f"⚠️ KISMİ SATIŞ (Partial Fill) tespit edildi! "
                        f"İstenen: {amount:.8f}, Satılan: {filled_amount:.8f}"
                    )
                    if filled_amount <= 0:
                        logger.error(f"❌ Satış hiç gerçekleşmedi (Filled: 0). Bekleyen emir iptal ediliyor.")
                        self.cancel_order(order.get('id'), symbol)
                        return None

                result = {
                    'id': order.get('id', ''),
                    'symbol': symbol,
                    'side': 'sell',
                    'price': actual_price,
                    'amount': filled_amount,
                    'cost': actual_cost,
                    'fee': order.get('fee', {}).get('cost', 0) if isinstance(order.get('fee'), dict) else 0,
                    'timestamp': datetime.now(),
                    'status': status,
                    'mode': self.mode,
                    'partial_fill': (filled_amount < amount)
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
                f"{result['amount']:.6f} {symbol} @ ${result['price']:,.2f} | "
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
