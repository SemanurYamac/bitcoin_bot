# Canlıya Geçiş Rehberi — Faz 1 (DCA Bot)

## Mevcut Durum (2026-05-07)

**Borsa bakiyesi:**
- USDT: $38.30
- BTC: 0.00063137 (~$40 — Oracle Cloud bot'tan kalan pozisyon)
- Toplam: ~$78

**Hedef sermaye:** $400 (kullanıcı tarafından eklenmiş olmalı)

**Gate sonuçları:**
| Bot | Durum | Açıklama |
|---|---|---|
| DCA | ✅ Canlıya hazır | 4/6 pozitif slice, Sharpe 1.15 |
| Grid | ⚠️ Yarım ramp ile | 3/6 pozitif, sideways'de iyi |
| Trend | ❌ Optimize gerek | Boğa rejimi problemi var |

---

## ADIM 1 — Oracle Cloud Bot'u Durdur (KRİTİK)

Yeni mimari ile çakışmaması için Oracle Cloud'daki eski botu durdurman lazım:

```bash
# Oracle instance'a SSH:
ssh -i ssh-key-2026-04-28.key opc@<your-oracle-ip>

# Bot konteynerini bul ve durdur:
docker ps                          # bitcoin_bot konteynerini bul
docker stop bitcoin_bot
docker rm bitcoin_bot              # otomatik restart önle

# Veya systemd ile çalışıyorsa:
sudo systemctl stop bitcoin-bot
sudo systemctl disable bitcoin-bot

# Doğrula:
docker ps                          # bitcoin_bot olmamalı
```

Mevcut BTC pozisyonu (0.00063 BTC) borsada kalır — istersen elle satabilirsin (~$40 USDT'ye dönüştürür).

---

## ADIM 2 — Sermaye Hazırlığı

DCA Faz 1 için **$40 USDT** gerekli. Borsada zaten $38.30 USDT var. Birkaç yol:

**Yol A (önerilen):** Mevcut $38'ı kullan, $40 yerine — yeterince yakın.

**Yol B:** Mevcut BTC'yi sat ($40 daha USDT olur), toplam $78 USDT olur. Sonra $40'ı DCA için ayır.

**Yol C:** $400 sermayeyi borsaya yatır ve hedef tahsisi yap (DCA $160, Grid $160, Trend $80).

---

## ADIM 3 — DCA Bot'u Canlıya Al ($40 ile)

```bash
cd "/Users/furkandursun/Bitcoin Bot"

# 1. Eski state'i temizle (yeni başlangıç)
rm -f data/portfolio_state.json data/bot_state_*.json

# 2. DCA bot'u $40 ile, sadece DCA, --live-confirm ile başlat
python3 tools/run_portfolio.py \
    --bots dca \
    --total-capital 40 \
    --interval 3600 \
    --live-confirm
```

**Açıklama:**
- `--bots dca`: Sadece DCA çalışsın (Grid/Trend uyusun)
- `--total-capital 40`: $40 sermaye olarak işle
- `--interval 3600`: Her saatte bir step kontrolü (DCA haftalık alım yapacak, saatlik kontrol yeterli)
- `--live-confirm`: TRADING_MODE=live için zorunlu güvenlik kilidi

**Beklenti:** İlk saatte DCA bot ilk haftalık alımı yapar:
- DCA bot otomatik olarak Binance min notional'ı (her coin için $6) koruyor
- $40 sermayede: $6 BTC + $6 ETH = $12/hafta alım yapacak
- Bir sonraki alım 7 gün sonra

> ✅ DCA bot içinde `MIN_NOTIONAL_PER_COIN=6.0` koruması var — küçük sermayelerde
> otomatik olarak alım miktarını yukarı çekiyor. Manuel ayar gerekmiyor.

---

## ADIM 4 — İlk Hafta İzleme

İlk hafta günde 1-2 kez kontrol et:

```bash
# Anlık portföy durumu:
python3 tools/dashboard.py

# Sürekli izleme (60s yenileme):
python3 tools/dashboard.py --watch 60

# Borsa bakiyesi (ham):
python3 -c "from data.collector import DataCollector; \
            print(DataCollector().fetch_balance())"
```

**Bot durdurmak (acil):**
```bash
# Çalışan run_portfolio process'ini bul:
ps aux | grep run_portfolio | grep -v grep

# Durdur:
kill <PID>

# Kill-switch'i manuel tetikle (botu pause):
python3 -c "
from core.portfolio_manager import PortfolioManager, BotConfig, PORTFOLIO_STATE_PATH
pm = PortfolioManager.load_or_create(40, [BotConfig('dca', 1.0)], PORTFOLIO_STATE_PATH)
pm.suspend_bot('dca', 'manual stop')
"
```

---

## ADIM 5 — 1 Hafta Sonra Karar

İlk hafta DCA'da ne görmek istiyoruz:
1. ✅ Alım gerçekleşti mi? (1 alım × $12 = OK)
2. ✅ Bot crash olmadı mı?
3. ✅ Telegram bildirimi geldi mi?
4. ✅ State save oluyor mu? (`data/bot_state_dca.json` güncellenmeli)
5. ✅ Tahsis vs reality match? (cash + holding değeri ≈ $40 ± fiyat hareketi)

Hepsi OK ise → **Hafta 2'de Grid Bot'u $20 ile ekle.**

---

## SİSTEM MİMARİ ÖZETİ

```
$400 sermaye
   │
   ├─→ $40 (Faz 1, Hafta 1) → DCA Bot
   │     └─ haftalık BTC %50 + ETH %50, $12/hafta alım
   │
   ├─→ $20 (Faz 2, Hafta 2) → Grid Bot
   │     └─ BTC/USDT 15-grid sideways oyun
   │
   └─→ Bekle (Faz 3) → Trend Bot
         └─ Önce optimize: boğa rejiminde TP/trailing düzelt
```

**Mevcut state JSON yolları:**
- `data/portfolio_state.json` — PM ana state
- `data/bot_state_dca.json` — DCA bot durumu
- `data/bot_state_grid.json` — Grid bot durumu (Faz 2'de)
- `data/bot_state_trend.json` — Trend bot durumu (Faz 3'te)

**Loglar:** `logs/` dizininde (mevcut konfigürasyon).
