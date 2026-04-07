# 🧠 Uzman Önerilerinin Değerlendirmesi — Bitcoin Bot

## Genel Kanı

Arkadaşının önerileri **büyük ölçüde doğru ve profesyonel**. Bir quant developer'ın bakış açısıyla yazılmış, endüstri standartlarına uygun öneriler. Ancak hepsini aynı anda yapmak projeyi ay(lar) boyunca bloke eder. **Aşamalı (fazlı) bir uygulama planı şart.**

Aşağıda her maddeyi 3 kategoride değerlendirdim:

- ✅ **Kesinlikle katılıyorum** — hemen yapılmalı
- ⚠️ **Katılıyorum ama zamanlama önemli** — sonraki faz
- 🟡 **Kısmen katılıyorum** — overengineering riski var

---

## 1️⃣ VARLIK EVRENİ — ✅ Kesinlikle katılıyorum

> "Önce BTC odaklı yapı kur, sonra genişlet"

**100% doğru.** Bugünkü log'lara bak:
- 50 coinin **22'si hacim filtresine takılıyor** — boşuna taranıyor
- Kalan 28'in çoğu negatif skorda
- En yüksek skor TRX (+3.6) — bu bile BTC değil

**Önerim:**
```
Faz 1: BTC/USDT tek başına (strateji validasyonu)
Faz 2: + ETH, SOL, BNB (top 4 — likit, düşük spread)
Faz 3: Config'den yönetilebilir coin universe (10-15 coin max)
```

50 coin taramak gereksiz complexity. Düşük hacimli coinlerde spread yüzünden %4 stop-loss'un yarısı gürültüye gider.

---

## 2️⃣ SİNYAL ÜRETİM MANTIĞI — ✅ En kritik madde

> "Sadece kapanmış mum üzerinde sinyal üret"

**Bu tek başına en önemli düzeltme.** Şu anda bot her 15 dakikada tarayarak **henüz kapanmamış mumlar üzerinde sinyal üretiyor.** Bu "repaint" riski yaratır — mum kapanana kadar RSI, MACD değerleri değişebilir.

| Şu anki durum | Olması gereken |
|---|---|
| 15dk'da 1 tarama, mumun ortasında sinyal | Mum kapanışını bekle, sonra sinyal üret |
| Aynı saat içinde 4 kez aynı mumu tara | Bir mum = bir karar |
| Cooldown yok | Exit sonrası 2-3 mum cooldown |

**Önerim:** Bu **Faz 1'de** yapılmalı. Sadece bu değişiklik false signal'ları dramatik şekilde azaltır.

---

## 3️⃣ GÖSTERGE MİMARİSİ — ✅ Çok doğru

> "Rejim filtresi ekle: EMA200 üstü ise long sinyaller daha kolay"

Bugünkü verilere bakalım:
- BTC skoru: **-2.7 ile -2.9** arası
- Neden? EMA50 < EMA200 → **death cross / downtrend aktif**
- Ama bot buna rağmen RSI oversold olsa AL sinyali vermeye çalışabilir

Arkadaşının önerisi tam da bunu çözüyor. **EMA200 altında long threshold'u yükselt veya tamamen kapat.**

**Trend-following vs Mean-reversion ayrımı** da doğru:
- Uptrend'de: MACD crossover + EMA golden cross güvenilir
- Downtrend'de: RSI oversold bounce **çoğunlukla başarısız** (dead cat bounce)

**Önerim:** Faz 1'de basit rejim filtresi ekle, Faz 2'de gösterge kategorizasyonu yap.

---

## 4️⃣ RİSK YÖNETİMİ — ✅ Kesinlikle doğru

> "Fixed %20 yerine risk-based position sizing"

Mevcut durumda:
- 5 pozisyon × %20 = **%100 sermaye risk altında**
- Hepsi kripto, hepsi BTC-korelasyonlu
- Bir flash crash'te hepsi aynı anda stop-loss'a düşer

Risk-based sizing formülü doğru:
```
position_size = (equity × risk_per_trade) / stop_distance
```

Örnek: $10,000 bakiye, %1 risk, %4 stop = $250 risk, $6,250 pozisyon boyutu

**Önerim:** Faz 1'de `RISK_PER_TRADE = 0.01` (%1) ile başla. Bu tek değişiklik hayatta kalma oranını dramatik artırır.

---

## 5️⃣ STOP / TP / TRAILING — ✅ Doğru ama pragmatik ol

> "Exit mantığını sadeleştir ve hiyerarşi belirle"

Şu an karışık: fixed SL + ATR stop + trailing hepsi aynı anda. Doğru yaklaşım:

```
Faz 1: Sadece ATR-based dynamic stop + fixed TP
Faz 2: Trailing stop (1.5R'den sonra aktifleşir)
Faz 3: Partial take profit (%50 @ 1.5R, kalan trailing)
```

**Partial TP** çok iyi bir öneri ama implementation complexity'si yüksek. Faz 3'e bırakılmalı.

---

## 6️⃣ EMİR YÜRÜTME — ⚠️ Doğru ama Faz 2-3

> "exchangeInfo, state reconciliation, partial fill handling"

Bunlar **canlıya geçiş için kritik** ama paper trading aşamasında acil değil.

- `tickSize`, `stepSize`, `minNotional` validasyonu → Faz 2
- State reconciliation → Faz 2
- Partial fill, rejected order state machine → Faz 3 (canlıya geçmeden)

**Şimdi yapılması gereken tek şey:** Bot restart'ta pozisyon recovery.

---

## 7️⃣ VERİ AKIŞI / WEBSOCKET — 🟡 Overengineering riski

> "REST polling yerine WebSocket"

**Bu noktada kısmen katılmıyorum.** Sebebi:

| Kriter | REST (şu anki) | WebSocket |
|---|---|---|
| 1h mum, 15dk tarama | **Yeterli** | Gereksiz complexity |
| Geliştirme süresi | 0 | 1-2 hafta |
| Güvenilirlik | Basit, reconnect kolay | Disconnect handling gerekir |
| Botun amacı | Swing trade (1h) | Scalping/HFT değil |

**1 saatlik mumlarla 15 dakikada bir tarama yapan bir bot için REST mükemmel yeterli.** WebSocket, 1m/5m timeframe'lere inildiğinde veya 100+ coin tarandığında gerekli olur.

**Önerim:** Bu maddeyi Faz 3+'ya ertele. Şu an REST polling ile devam et.

---

## 8️⃣ BACKTEST KALİTESİ — ✅ Doğru ama aşamalı

> "commission, slippage, spread, Sharpe, profit factor..."

Metrik listesi mükemmel. Ama hepsini bir anda eklemek yerine:

```
Faz 1: Commission (%0.1) + basit slippage (%0.05) + temel metrikler
        (total return, max DD, win rate, avg win/loss, trade count)
Faz 2: Profit factor, expectancy, Sharpe, symbol bazlı performans
Faz 3: Walk-forward, regime bazlı performans, overfitting detection
```

---

## 9️⃣ LOGGING / TELEGRAM — ✅ Doğru

> "Explainable trades, score breakdown, structured logging"

Bu Faz 1'de yapılmalı. Özellikle:
- **Her sinyal için hangi gösterge kaç puan verdi** → debug ve strateji geliştirme için kritik
- **JSON structured logging** → analiz için çok değerli
- **Telegram mesajlarında trade açıklaması** → gözlemlenebilirlik

---

## 🔟 GÜVENLİLİK — ✅ Doğru

> "Pre-flight checklist, fail-safe mode"

Fail-safe önerisi çok önemli:
- Veri çekilemiyorsa → trade açma
- Bakiye beklenmedikse → koruma moduna geç
- Max drawdown → sistem kilitle

Bu Faz 1'in bir parçası olmalı.

---

## 1️⃣1️⃣ KONFİGÜRASYON — ✅ Doğru ama aşamalı

> "Domain bazlı config ayrımı, type hints, dataclass"

Doğru yönde ama **Faz 2**. Şu an `settings.py` tek dosyada yönetilebilir boyutta.

---

## 📊 Genel Skor Tablosu

| Madde | Doğruluk | Aciliyet | Faz |
|---|---|---|---|
| 1. Varlık evreni (BTC odak) | ✅ %100 | 🔴 Yüksek | **Faz 1** |
| 2. Closed candle sinyal | ✅ %100 | 🔴 Yüksek | **Faz 1** |
| 3. Rejim filtresi | ✅ %95 | 🔴 Yüksek | **Faz 1** |
| 4. Risk-based sizing | ✅ %100 | 🔴 Yüksek | **Faz 1** |
| 5. Stop/TP hiyerarşisi | ✅ %90 | 🟡 Orta | **Faz 1-2** |
| 6. Emir yürütme | ✅ %90 | 🟡 Orta | **Faz 2** |
| 7. WebSocket | 🟡 %60 | 🟢 Düşük | **Faz 3+** |
| 8. Backtest kalitesi | ✅ %95 | 🟡 Orta | **Faz 2** |
| 9. Logging/Telegram | ✅ %100 | 🟡 Orta | **Faz 1-2** |
| 10. Güvenlilik | ✅ %100 | 🔴 Yüksek | **Faz 1** |
| 11. Kod kalitesi | ✅ %85 | 🟢 Düşük | **Faz 2** |

---

## 🎯 Önerilen Uygulama Planı

### ⚡ FAZ 1 — "Güvenli Temel" (1-2 hafta)
> Amacı: Stratejinin doğru çalıştığını doğrulayabileceğimiz güvenilir bir sistem

1. **BTC/USDT + ETH/USDT + SOL/USDT odaklı** yapıya geç (50 → 3 coin)
2. **Closed candle sinyal** — sadece mum kapanışında sinyal üret
3. **Rejim filtresi** — EMA200 altında long threshold'u 2x yükselt
4. **Risk-based position sizing** — %1 risk per trade
5. **Cooldown** — exit sonrası 2 mum bekle
6. **Fail-safe** — veri yoksa trade açma
7. **Score breakdown** Telegram'da ve log'da göster
8. **Duplicate sinyal engeli** — aynı mumda tekrar sinyal üretme

### 🔧 FAZ 2 — "Profesyonelleştirme" (2-3 hafta)
- Domain bazlı config ayrımı
- ATR-based dynamic stop modu
- exchangeInfo symbol filter validasyonu
- Backtest metrik genişletme (Sharpe, profit factor vb.)
- Bot restart'ta state recovery
- JSON structured logging

### 🚀 FAZ 3 — "Canlıya Hazırlık" (3-4 hafta)
- Partial take profit
- Pre-flight checklist
- Order state machine (partial fill, rejection vb.)
- Walk-forward test yapısı
- Korelasyon bazlı risk limiti
- WebSocket (isteğe bağlı)

---

## 💡 Son Söz

Arkadaşının önerileri **%90+ doğru** bir quant perspektifi sunuyor. Tek risk: **hepsini aynı anda yapmaya çalışmak.** Bu projeyi aylarca bloke eder.

**Doğru strateji:** Faz 1'deki 8 değişikliği uygula → 2 hafta çalıştır → verilere bak → Faz 2'ye geç.

> [!IMPORTANT]
> **En kritik 3 değişiklik** (bunlar tek başına sistemi %50+ iyileştirir):
> 1. Closed candle sinyal üretimi (repaint'i önler)
> 2. Rejim filtresi (downtrend'de boş yere alım yapmayı engeller)
> 3. Risk-based position sizing (sermaye koruması)
