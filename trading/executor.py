"""
Bitcoin Trading Bot - Emir Yürütme Modülü
Borsa üzerinde alım-satım emirlerini yürütür.

GÜNCELLEME (Phase 4):
  - ExchangeRules entegrasyonu: her emir öncesi LOT_SIZE / NOTIONAL doğrulaması
  - Miktar otomatik olarak borsa stepSize kuralına göre yuvarlanır
  - minNotional kontrolü: çok küçük emirler gönderilmez (ghost pozisyon riski)
  - Kural yükleme hatası durumunda güvenli fallback davranışı
"""
import logging
from datetime import datetime
from data.collector import DataCollector
from data.storage import DataStorage
from trading.exchange_rules import ExchangeRules
from config.settings import SYMBOL, TRADING_MODE

logger = logging.getLogger(__name__)


class TradeExecutor:
    """Alım-satım emirlerini yürütür."""

    def __init__(self, collector: DataCollector, storage: DataStorage):
        self.collector = collector
        self.storage = storage
        self.mode = TRADING_MODE

        # ExchangeRules: public_exchange üzerinden kuralları çeker (API key gerekmez)
        self.rules = ExchangeRules(collector.public_exchange)

        # Bot başladığında tüm sembollerin kurallarını önceden yükle
        self._preload_rules()

    def _preload_rules(self) -> None:
        """
        Bot başlangıcında borsa kurallarını bir kere çeker.
        Hem başlatma süresini optimize eder hem de ilk emirde gecikmeyi önler.
        """
        try:
            self.rules._ensure_markets(force=True)
            logger.info("✅ Borsa emir kuralları önceden yüklendi.")
        except Exception as e:
            logger.warning(
                f"⚠️ Borsa kuralları önceden yüklenemedi: {e} — "
                f"İlk emir sırasında tekrar denenecek."
            )

    def _prepare_quantity(self, symbol: str, raw_amount: float, current_price: float) -> float:
        """
        Ham miktarı borsa kurallarına göre hazırlar:
          1. LOT_SIZE stepSize'a floor (aşağı yuvarlama)
          2. Emir doğrulama (minQty, maxQty, minNotional)

        Returns:
            Borsa-uyumlu miktar. Kural ihlali varsa 0.0 döner ve log'a yazar.
        """
        try:
            # 1. Miktarı stepSize'a yuvarla
            adjusted = self.rules.round_quantity(symbol, raw_amount)

            if adjusted <= 0:
                logger.error(
                    f"❌ [{symbol}] Miktar yuvarlama sonrası sıfır/negatif: "
                    f"ham={raw_amount:.10f} → {adjusted:.10f}"
                )
                return 0.0

            # 2. Tüm kuralları doğrula
            ok, reason = self.rules.validate_order(symbol, adjusted, current_price)
            if not ok:
                logger.error(f"❌ Emir kural ihlali → {reason}")
                return 0.0

            # Miktar değiştiyse logla
            if abs(adjusted - raw_amount) > 1e-10:
                logger.info(
                    f"⚙️  [{symbol}] Miktar borsa kuralına göre düzeltildi: "
                    f"{raw_amount:.10f} → {adjusted:.10f}"
                )

            return adjusted

        except Exception as e:
            # Kural modülü hata verirse işlemi bloke etme; ham miktarla devam et
            logger.warning(
                f"⚠️ [{symbol}] Borsa kural kontrolü başarısız: {e} — "
                f"Ham miktar kullanılıyor ({raw_amount:.8f}). "
                f"Manuel kontrol önerilir!"
            )
            return raw_amount

    def execute_buy(self, symbol=None, amount=None, price=None):
        """
        Alım emri yürütür.

        Args:
            symbol: İşlem çifti
            amount: Coin miktarı (ham — borsa kurallarına göre otomatik yuvarlanır)
            price:  Limit fiyatı (None ise market order)

        Returns:
            dict: İşlem sonucu veya None (emir gönderilemezse)
        """
        symbol = symbol or SYMBOL

        try:
            # ─── Backtest Modu ───────────────────────────────────────────
            if self.mode == 'backtest':
                result = {
                    'id': f"backtest_{datetime.now().timestamp()}",
                    'symbol': symbol,
                    'side': 'buy',
                    'price': price,
                    'amount': amount,
                    'cost': (price or 0) * (amount or 0),
                    'fee': (price or 0) * (amount or 0) * 0.001,
                    'timestamp': datetime.now(),
                    'status': 'filled',
                    'mode': 'backtest',
                }

            # ─── Paper / Live Modu ───────────────────────────────────────
            elif self.mode in ('paper', 'live'):
                # Güncel fiyatı belirle (kural doğrulama için gerekli)
                effective_price = price
                if effective_price is None:
                    try:
                        ticker = self.collector.public_exchange.fetch_ticker(symbol)
                        effective_price = ticker['last']
                    except Exception as e:
                        logger.warning(f"⚠️ [{symbol}] Ticker alınamadı: {e} — fiyat tahmini kullanılamıyor.")
                        effective_price = 0  # minNotional kontrolü atlanacak

                # Borsa kuralı doğrulama + yuvarlama
                adjusted_amount = self._prepare_quantity(symbol, amount, effective_price)
                if adjusted_amount <= 0:
                    logger.error(
                        f"❌ [{symbol}] ALIM EMRİ GÖNDERİLMEDİ — "
                        f"Borsa kuralları ihlal edildiği için iptal edildi."
                    )
                    return None

                # Limit emirlerde fiyatı da tickSize'a yuvarla
                if price is not None:
                    price = self.rules.round_price(symbol, price)

                # Kurallara uyumu log'a yaz
                self.rules.log_rules(symbol)

                if price:
                    order = self.collector.exchange.create_limit_buy_order(
                        symbol, adjusted_amount, price
                    )
                else:
                    order = self.collector.exchange.create_market_buy_order(
                        symbol, adjusted_amount
                    )

                status = order.get('status', 'unknown')

                filled_amount = order.get('filled')
                if filled_amount is None:
                    filled_amount = adjusted_amount

                actual_price = order.get('average') or order.get('price') or price
                actual_cost = order.get('cost', filled_amount * (actual_price or 0))

                # Kısmi gerçekleşme yönetimi
                if status in ('open', 'partially_filled') and filled_amount < adjusted_amount:
                    logger.warning(
                        f"⚠️ KISMİ GERÇEKLEŞME (Partial Fill) | "
                        f"İstenen: {adjusted_amount:.8f}, Alınan: {filled_amount:.8f}"
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
                    'partial_fill': (filled_amount < adjusted_amount),
                    'requested_amount': amount,
                    'adjusted_amount': adjusted_amount,
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
                f"Komisyon: ${result.get('fee', 0):,.4f}"
            )

            return result

        except Exception as e:
            logger.error(f"❌ Alım emri hatası [{symbol}]: {e}")
            raise

    def execute_sell(self, symbol=None, amount=None, price=None):
        """
        Satım emri yürütür.

        Args:
            symbol: İşlem çifti
            amount: Coin miktarı (ham — borsa kurallarına göre otomatik yuvarlanır)
            price:  Limit fiyatı (None ise market order)

        Returns:
            dict: İşlem sonucu veya None (emir gönderilemezse)
        """
        symbol = symbol or SYMBOL

        try:
            # ─── Backtest Modu ───────────────────────────────────────────
            if self.mode == 'backtest':
                result = {
                    'id': f"backtest_{datetime.now().timestamp()}",
                    'symbol': symbol,
                    'side': 'sell',
                    'price': price,
                    'amount': amount,
                    'cost': (price or 0) * (amount or 0),
                    'fee': (price or 0) * (amount or 0) * 0.001,
                    'timestamp': datetime.now(),
                    'status': 'filled',
                    'mode': 'backtest',
                }

            # ─── Paper / Live Modu ───────────────────────────────────────
            elif self.mode in ('paper', 'live'):
                effective_price = price
                if effective_price is None:
                    try:
                        ticker = self.collector.public_exchange.fetch_ticker(symbol)
                        effective_price = ticker['last']
                    except Exception as e:
                        logger.warning(f"⚠️ [{symbol}] Ticker alınamadı: {e}")
                        effective_price = 0

                # Borsa kuralı doğrulama + yuvarlama
                adjusted_amount = self._prepare_quantity(symbol, amount, effective_price)
                if adjusted_amount <= 0:
                    logger.error(
                        f"❌ [{symbol}] SATIM EMRİ GÖNDERİLMEDİ — "
                        f"Borsa kuralları ihlal edildiği için iptal edildi."
                    )
                    return None

                if price is not None:
                    price = self.rules.round_price(symbol, price)

                if price:
                    order = self.collector.exchange.create_limit_sell_order(
                        symbol, adjusted_amount, price
                    )
                else:
                    order = self.collector.exchange.create_market_sell_order(
                        symbol, adjusted_amount
                    )

                status = order.get('status', 'unknown')

                filled_amount = order.get('filled')
                if filled_amount is None:
                    filled_amount = adjusted_amount

                actual_price = order.get('average') or order.get('price') or price
                actual_cost = order.get('cost', filled_amount * (actual_price or 0))

                if status in ('open', 'partially_filled') and filled_amount < adjusted_amount:
                    logger.warning(
                        f"⚠️ KISMİ SATIŞ (Partial Fill) | "
                        f"İstenen: {adjusted_amount:.8f}, Satılan: {filled_amount:.8f}"
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
                    'partial_fill': (filled_amount < adjusted_amount),
                    'requested_amount': amount,
                    'adjusted_amount': adjusted_amount,
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
                f"Komisyon: ${result.get('fee', 0):,.4f}"
            )

            return result

        except Exception as e:
            error_str = str(e).lower()
            # ─── Yetersiz Bakiye: Gerçek bakiyeyle retry ──────────────────
            if 'insufficient balance' in error_str or 'insufficient funds' in error_str:
                logger.warning(
                    f"⚠️ [{symbol}] Yetersiz bakiye hatası — Binance'teki gerçek "
                    f"bakiye kontrol ediliyor (phantom pozisyon tespiti)..."
                )
                try:
                    base_coin = symbol.split('/')[0]  # 'LINK/USDT' → 'LINK'
                    balance_info = self.collector.exchange.fetch_balance()
                    actual_balance = float(balance_info.get('free', {}).get(base_coin, 0))
                    logger.info(f"📊 [{symbol}] Gerçek {base_coin} bakiyesi: {actual_balance:.8f}")

                    # Bakiye ihmal edilebilir düzeyde → phantom pozisyon
                    min_threshold = 0.001 * amount  # State'deki miktarın %0.1'i
                    if actual_balance < min_threshold:
                        logger.warning(
                            f"🔍 [{symbol}] Phantom pozisyon tespit edildi! "
                            f"State={amount:.8f}, Gerçek bakiye={actual_balance:.8f} "
                            f"(dust seviyesi). Pozisyon otomatik kapatılıyor."
                        )
                        # Pozisyon yöneticisine "dust satış" olarak bildir
                        return {
                            'id': f"phantom_close_{datetime.now().timestamp()}",
                            'symbol': symbol,
                            'side': 'sell',
                            'price': price or 0,
                            'amount': actual_balance,
                            'cost': (price or 0) * actual_balance,
                            'fee': 0,
                            'timestamp': datetime.now(),
                            'status': 'phantom_closed',
                            'mode': self.mode,
                            'phantom': True,
                        }

                    # Yeterli bakiye var → gerçek bakiyeyle yeniden dene
                    logger.info(
                        f"🔄 [{symbol}] Gerçek bakiyeyle yeniden satış deneniyor: "
                        f"{actual_balance:.8f} {base_coin}"
                    )
                    # Notional check için güncel fiyat gerekli (market order'da price=None)
                    retry_price = price
                    if retry_price is None or retry_price <= 0:
                        try:
                            ticker = self.collector.public_exchange.fetch_ticker(symbol)
                            retry_price = ticker['last']
                        except Exception as tick_err:
                            logger.warning(
                                f"⚠️ [{symbol}] Retry için ticker alınamadı: {tick_err}"
                            )
                            retry_price = 0
                    adjusted_actual = self._prepare_quantity(symbol, actual_balance, retry_price)
                    if adjusted_actual > 0:
                        if price:
                            order = self.collector.exchange.create_limit_sell_order(
                                symbol, adjusted_actual, price
                            )
                        else:
                            order = self.collector.exchange.create_market_sell_order(
                                symbol, adjusted_actual
                            )
                        logger.info(f"✅ [{symbol}] Gerçek bakiyeyle satış başarılı: {adjusted_actual:.8f}")
                        filled_amount = order.get('filled') or adjusted_actual
                        actual_price = order.get('average') or order.get('price') or price
                        return {
                            'id': order.get('id', ''),
                            'symbol': symbol,
                            'side': 'sell',
                            'price': actual_price,
                            'amount': filled_amount,
                            'cost': order.get('cost', filled_amount * (actual_price or 0)),
                            'fee': order.get('fee', {}).get('cost', 0) if isinstance(order.get('fee'), dict) else 0,
                            'timestamp': datetime.now(),
                            'status': order.get('status', 'filled'),
                            'mode': self.mode,
                            'balance_corrected': True,
                        }
                except Exception as retry_err:
                    logger.error(f"❌ [{symbol}] Gerçek bakiye kontrolü de başarısız: {retry_err}")

            logger.error(f"❌ Satım emri hatası [{symbol}]: {e}")
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
