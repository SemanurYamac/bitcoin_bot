"""
Bitcoin Trading Bot - Borsa Kural Doğrulama Modülü
Binance'in her sembolle alakalı LOT_SIZE, NOTIONAL, PRICE_FILTER
kural setini çekerek emir öncesi miktar ve fiyat uyumunu sağlar.

NEDEN ÖNEMLİ:
  Binance her sembol için zorunlu kurallar tanımlar:
    - LOT_SIZE   : stepSize (min artış birimi), minQty, maxQty
    - NOTIONAL   : minNotional (min işlem tutarı, USDT cinsinden)
    - PRICE_FILTER: tickSize (fiyat hassasiyeti)
  Bu kurallara uymayan emirler borsa tarafından reddedilir.
  "Ghost pozisyon" riskini (bot alındı sanır ama borsa reddetti) bu modül önler.

KULLANIM:
  rules = ExchangeRules(collector.public_exchange)
  # Emir öncesi doğrula ve yuvarla:
  qty  = rules.round_quantity('ETH/USDT', raw_qty)
  ok, reason = rules.validate_order('ETH/USDT', qty, current_price)
  if not ok:
      logger.error(reason)
"""
import math
import logging
import time
import ccxt

logger = logging.getLogger(__name__)

# Market bilgisi cache geçerlilik süresi (saniye)
# Binance kuralları nadiren değişir; 1 saatlik cache yeterlidir
_CACHE_TTL_SECONDS = 3600


class ExchangeRules:
    """
    Binance borsa kurallarını (filter setleri) yönetir ve uygular.

    Her örnek kendi market cache'ini tutar.
    Bot başladığında veya cache süresi dolduğunda otomatik yeniler.
    """

    def __init__(self, exchange: ccxt.Exchange):
        """
        Args:
            exchange: Zaten yapılandırılmış ccxt.binance örneği
                      (public_exchange — API key gerektirmez)
        """
        self.exchange = exchange
        self._markets: dict = {}        # {symbol: market_info}
        self._loaded_at: float = 0.0    # Son yükleme unix timestamp

    # ──────────────────────────────────────────────────────────────
    # Dahili: Market Yükleme & Cache
    # ──────────────────────────────────────────────────────────────

    def _ensure_markets(self, force: bool = False) -> None:
        """
        Market bilgisini gerektiğinde yükler veya tazeler.
        Cache süresi dolmadıysa ağa gitmez.
        """
        now = time.time()
        if force or not self._markets or (now - self._loaded_at) > _CACHE_TTL_SECONDS:
            try:
                logger.info("📡 Binance market bilgisi yükleniyor (borsa kuralları)...")
                self._markets = self.exchange.load_markets(reload=True)
                self._loaded_at = now
                logger.info(f"✅ {len(self._markets)} sembol için borsa kuralları yüklendi.")
            except Exception as e:
                logger.error(f"❌ Market bilgisi yüklenemedi: {e}")
                # İlk yükleme başarısız olduysa ve elimizde eski veri yoksa yeniden dene
                if not self._markets:
                    raise

    def _get_filter(self, symbol: str, filter_type: str) -> dict:
        """
        Belirli bir sembol için istenen filter'ı döndürür.
        Yoksa boş dict döner (güvenli fallback).
        """
        self._ensure_markets()
        market = self._markets.get(symbol, {})
        info = market.get('info', {})
        filters = info.get('filters', [])
        for f in filters:
            if f.get('filterType') == filter_type:
                return f
        return {}

    # ──────────────────────────────────────────────────────────────
    # Kural Okuma Yardımcıları
    # ──────────────────────────────────────────────────────────────

    def get_step_size(self, symbol: str) -> float:
        """
        LOT_SIZE stepSize: miktarın en küçük artış birimi.
        Örnek: BTC/USDT → 0.00001, DOGE/USDT → 1.0
        """
        f = self._get_filter(symbol, 'LOT_SIZE')
        step = float(f.get('stepSize', '0.00000001'))
        return step if step > 0 else 1e-8

    def get_min_qty(self, symbol: str) -> float:
        """LOT_SIZE minQty: minimum miktar."""
        f = self._get_filter(symbol, 'LOT_SIZE')
        return float(f.get('minQty', '0.00000001'))

    def get_max_qty(self, symbol: str) -> float:
        """LOT_SIZE maxQty: maksimum miktar."""
        f = self._get_filter(symbol, 'LOT_SIZE')
        return float(f.get('maxQty', '9000000'))

    def get_min_notional(self, symbol: str) -> float:
        """
        MIN_NOTIONAL veya NOTIONAL filtresi: minimum işlem tutarı (USDT).
        Spot için çoğunlukla $5 ile $10 arasındadır.
        """
        # Binance 2023 sonrasında 'NOTIONAL' kullandı, önceki 'MIN_NOTIONAL'
        for filter_type in ('NOTIONAL', 'MIN_NOTIONAL'):
            f = self._get_filter(symbol, filter_type)
            val = f.get('minNotional') or f.get('minNotional')
            if val:
                return float(val)
        return 5.0   # Binance default güvenli fallback

    def get_tick_size(self, symbol: str) -> float:
        """PRICE_FILTER tickSize: fiyatın en küçük artış birimi."""
        f = self._get_filter(symbol, 'PRICE_FILTER')
        tick = float(f.get('tickSize', '0.01'))
        return tick if tick > 0 else 0.01

    # ──────────────────────────────────────────────────────────────
    # Yuvarlama Fonksiyonları
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _floor_to_step(value: float, step: float) -> float:
        """
        Değeri stepSize'a göre aşağı yuvarlar (floor).
        Borsa her zaman aşağı yuvarlama bekler; yukarı yuvarlama
        maxQty ihlali riskine yol açabilir.

        Örnek: value=0.12345, step=0.001 → 0.123
        """
        if step <= 0:
            return value
        # Floating point hatasını önlemek için Decimal benzeri yaklaşım
        precision = max(0, round(-math.log10(step)))
        floored = math.floor(value / step) * step
        return round(floored, precision)

    def round_quantity(self, symbol: str, quantity: float) -> float:
        """
        Miktarı Binance LOT_SIZE kuralına göre yuvarlar.
        Ayrıca minQty ve maxQty sınırlarını loglar (hata değil uyarı).

        Returns:
            Borsa-uyumlu miktar (float). Çok küçükse 0.0 döner.
        """
        step = self.get_step_size(symbol)
        min_qty = self.get_min_qty(symbol)
        max_qty = self.get_max_qty(symbol)

        rounded = self._floor_to_step(quantity, step)

        if rounded < min_qty:
            logger.warning(
                f"⚠️  [{symbol}] Hesaplanan miktar ({rounded:.10f}) "
                f"minQty ({min_qty}) altında → 0 döndürülüyor."
            )
            return 0.0

        if rounded > max_qty:
            logger.warning(
                f"⚠️  [{symbol}] Hesaplanan miktar ({rounded:.10f}) "
                f"maxQty ({max_qty}) üzerinde → maxQty'e kırpılıyor."
            )
            rounded = self._floor_to_step(max_qty, step)

        return rounded

    def round_price(self, symbol: str, price: float) -> float:
        """
        Fiyatı Binance PRICE_FILTER tickSize kuralına göre yuvarlar.
        Limit emirlerde kullanılır.
        """
        tick = self.get_tick_size(symbol)
        precision = max(0, round(-math.log10(tick)))
        rounded = math.floor(price / tick) * tick
        return round(rounded, precision)

    # ──────────────────────────────────────────────────────────────
    # Emir Öncesi Doğrulama
    # ──────────────────────────────────────────────────────────────

    def validate_order(
        self,
        symbol: str,
        quantity: float,
        price: float,
    ) -> tuple[bool, str]:
        """
        Emir göndermeden önce tüm kurallara uyumu kontrol eder.

        Kontroller:
          1. minQty / maxQty (LOT_SIZE)
          2. minNotional = qty * price >= minNotional (NOTIONAL)
          3. Miktar > 0

        Args:
            symbol:   İşlem çifti ('BTC/USDT')
            quantity: Borsa'ya gönderilecek nihai miktar (zaten yuvarlanmış)
            price:    İşlem fiyatı (market order için güncel ticker fiyatı)

        Returns:
            (True, 'OK')  veya  (False, hata_mesajı)
        """
        if quantity <= 0:
            return False, f"[{symbol}] Geçersiz miktar: {quantity}"

        # LOT_SIZE kontrolleri
        min_qty = self.get_min_qty(symbol)
        max_qty = self.get_max_qty(symbol)
        step    = self.get_step_size(symbol)

        if quantity < min_qty:
            return False, (
                f"[{symbol}] Miktar ({quantity:.10f}) < minQty ({min_qty:.10f})"
            )

        if quantity > max_qty:
            return False, (
                f"[{symbol}] Miktar ({quantity:.10f}) > maxQty ({max_qty:.10f})"
            )

        # Min notional: qty * price >= minNotional
        notional = quantity * price
        min_notional = self.get_min_notional(symbol)
        if notional < min_notional:
            return False, (
                f"[{symbol}] İşlem tutarı (${notional:.2f}) < "
                f"minNotional (${min_notional:.2f}). "
                f"Pozisyon boyutunu artırın."
            )

        return True, "OK"

    def log_rules(self, symbol: str) -> None:
        """
        Sembol için tüm borsa kurallarını INFO seviyesinde loglar.
        Debug ve izleme amaçlıdır.
        """
        step         = self.get_step_size(symbol)
        min_qty      = self.get_min_qty(symbol)
        max_qty      = self.get_max_qty(symbol)
        min_notional = self.get_min_notional(symbol)
        tick_size    = self.get_tick_size(symbol)

        logger.info(
            f"📋 Borsa Kuralları [{symbol}]: "
            f"stepSize={step}, minQty={min_qty}, maxQty={max_qty:.0f}, "
            f"minNotional=${min_notional:.2f}, tickSize={tick_size}"
        )
