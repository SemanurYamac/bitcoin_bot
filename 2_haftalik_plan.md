# 🗓️ Bitcoin Bot — 2 Haftalık Hızlandırılmış Plan

## Neden 2 Hafta Çalışır?

| Faktör | Normal Süre | Bizim Süre | Neden |
|---|---|---|---|
| Kodlama | Günler | Saatler | AI pair programming |
| Test yazma | Günler | Saatler | Aynı sebep |
| Gözlem süresi | 1-2 hafta | 3-5 gün | Paper trading, risk yok |
| Config tuning | Günler | Gerçek zamanlı | Veri geldikçe ayarlarız |

> [!IMPORTANT]
> **Risk artmaz mı?** Paper trading'de gerçek para yok → kodlama hızının riski sıfır.
> Tek risk: **gözlem süresinin kısa olması.** Bunu "canlıya geçmeden 1 hafta daha gözle" şartıyla kapatırız.

---

## 📅 PLAN

### ⚡ FAZ 1 — Güvenli Temel (Gün 1-2, yani BUGÜN + YARIN)

**Kodlama: ~3-4 saat | Gözlem: hemen başlar**

| # | Değişiklik | Etki | Süre |
|---|---|---|---|
| 1 | BTC + ETH + SOL odaklı yapıya geç (50 → 3 coin) | Gürültüyü %90 azaltır | 15dk |
| 2 | Closed candle sinyal (mum kapanışını bekle) | False signal'ı yok eder | 1 saat |
| 3 | Rejim filtresi (EMA200 altında long threshold 2x) | Downtrend alımını engeller | 30dk |
| 4 | Risk-based position sizing (%1 risk/trade) | Sermaye koruması | 45dk |
| 5 | Cooldown (exit sonrası 2 mum bekle) | Overtrading'i engeller | 30dk |
| 6 | Duplicate sinyal engeli (aynı mumda tekrar yok) | Spam'i önler | 20dk |
| 7 | Fail-safe (veri yoksa trade açma) | Güvenlik | 30dk |
| 8 | Score breakdown (Telegram + log'da detay) | Gözlemlenebilirlik | 45dk |

**Faz 1 biter bitmez bot yeniden başlar → gözlem süresi Gün 2'den itibaren akar.**

---

### 🔧 FAZ 2 — Profesyonelleştirme (Gün 3-7)

**Kodlama: ~4-5 saat | Gözlem: Faz 1 için devam eder**

| # | Değişiklik | Etki |
|---|---|---|
| 9 | Config refactor (market / signal / risk / exec ayrımı) | Temiz yapı |
| 10 | ATR-based dynamic stop modu | Volatiliteye uyumlu exit |
| 11 | Backtest metrik genişletme (Sharpe, PF, expectancy) | Strateji ölçülebilirliği |
| 12 | Bot restart'ta state recovery | Güvenilirlik |
| 13 | JSON structured logging | Analiz kolaylığı |
| 14 | Telegram mesaj iyileştirme (trade açıklama, stop bilgisi) | Profesyonellik |

---

### 🚀 FAZ 3 — Canlıya Hazırlık (Gün 8-14)

**Kodlama: ~4-5 saat | Gözlem: tüm sistem birlikte test edilir**

| # | Değişiklik | Etki |
|---|---|---|
| 15 | exchangeInfo symbol filter validasyonu | Order rejection'ı önler |
| 16 | Partial take profit (%50 @ 1.5R) | Kâr optimizasyonu |
| 17 | Pre-flight checklist (live moda geçmeden kontrol) | Güvenlik |
| 18 | Korelasyon bazlı risk limiti | Portföy koruması |
| 19 | Max drawdown → protection mode | Otomatik koruma |
| 20 | Walk-forward test yapısı (basit versiyon) | Overfitting kontrolü |

---

## ⏰ Günlük Akış

```
Gün 1  [BUGÜN]  : Faz 1 kodlama (1-8 arası) + bot yeniden başlatma
Gün 2           : Faz 1 gözlem + küçük düzeltmeler
Gün 3-4         : Faz 2 kodlama (9-14)
Gün 5-7         : Faz 2 gözlem + Faz 1 verileri analiz
Gün 8-10        : Faz 3 kodlama (15-20)
Gün 11-14       : Tam sistem gözlem + fine-tuning
─────────────────────────────────────────────────
Gün 15+         : Canlıya geçiş kararı (yeterli veri varsa)
```

---

## ⚠️ Ertelenen Maddeler (2 Haftaya Sığmayanlar)

Bu maddeler paper trading'i etkilemez, canlı öncesi yapılır:

| Madde | Neden ertelendi |
|---|---|
| WebSocket veri akışı | 1h timeframe için gereksiz |
| Order state machine (partial fill vb.) | Paper trading'de gerekmiyor |
| Overfitting detection (gelişmiş) | Yeterli backtest verisi lazım |
| Pydantic/dataclass config | Nice-to-have, fonksiyonu değiştirmez |

---

## 🎯 Başarı Kriteri (14. Gün Sonunda)

- [ ] Closed candle sinyalle en az 50+ mum gözlemlenmiş
- [ ] Rejim filtresi bearish piyasada boş alımı engellemiş
- [ ] En az 2-3 gerçek BUY sinyali görülmüş (veya neden gelmediği açıklanmış)
- [ ] Risk-based sizing ile hiçbir trade'de >%1 kayıp olmamış
- [ ] Score breakdown her trade için görülebilir
- [ ] Bot restart sonrası state korunmuş
- [ ] Backtest metrikleri strateji performansını göstermiş
- [ ] Fail-safe en az 1 kez test edilmiş
