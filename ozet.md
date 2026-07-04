# Bitcoin Bot — Proje Özeti

Tarih: 2026-07-04
Ana dal: `main`
Toplam kod: ~8,000 satır Python (30+ modül)

## 1. Genel Bakış

**Kripto ticaret bot sistemi** — Binance spot üzerinde, teknik analiz + XGBoost ML tahmini birleştiren, çoklu coin ve çoklu strateji destekli otomatik ticaret altyapısı. Faz 5 (Momentum Rider) → Faz 6 (Optimizasyon) → yeni 3-bot mimarisi (DCA + Grid + Trend) evrimi yaşadı.

**Mevcut kullanım modları:**
- `backtest` — geçmiş veri üzerinde strateji testi (2022–2026)
- `paper`   — Binance testnet ile sanal işlem
- `live`    — gerçek para (Oracle Cloud üzerinde deploy, yerelde `--live-confirm` zorunlu)
- `signal`  — anlık sinyal kontrolü
- `status`  — bakiye + pozisyon paneli

## 2. Mimari

### Klasör Yapısı

| Klasör | Amaç |
|---|---|
| `config/` | Merkezi ayarlar (`settings.py`) — semboller, indikatör periyotları, risk parametreleri, ATR çarpanları |
| `data/` | Binance veri toplayıcı (CCXT), SQLite storage, kayıtlı XGBoost modeli, live state JSON'ları |
| `analysis/` | Teknik indikatörler (RSI, MACD, Bollinger, EMA, ADX, ATR) + `ml_trainer.py` (XGBoost eğitimi) |
| `strategy/` | `signals.py` — Momentum Rider sinyal üretici (ML + kural tabanlı hibrit) |
| `trading/` | `executor.py`, `risk_manager.py`, `state_manager.py`, `exchange_rules.py` |
| `backtest/` | Backtesting motoru, `hyperopt.py`, `optimizer.py`, `fast_test.py` |
| `bots/` | Yeni 3-bot mimarisi: `dca_bot.py`, `grid_bot.py`, `trend_bot.py` |
| `core/` | `portfolio_manager.py`, `bot_base.py`, `exchange.py`, `walkforward.py`, `metrics.py` |
| `notifications/` | Telegram bildirimleri |
| `dashboard/` | Streamlit web arayüzü |
| `tools/` | 20+ analiz/backtest/keşif aracı (Donchian evren seçimi, hacim spike, mean-reversion, portföy sim.) |
| `tests/` | Test iskeleti (henüz boş) |

### Ana Modüller (satır sayısı)

- `main.py` — 996 satır, tüm modları yönetir
- `trading/risk_manager.py` — 532 satır
- `strategy/signals.py` — 454 satır
- `trading/executor.py` — 440 satır
- `backtest/engine.py` — 395 satır
- `core/portfolio_manager.py` — 396 satır
- `analysis/indicators.py` — 389 satır

## 3. Strateji Katmanları

### A) Monolitik Momentum Rider (`main.py` + `strategy/signals.py`)

**4h timeframe**, closed-candle mod, LONG-only.

**Sinyal koşulları (tümü sağlanmalı):**
1. `ADX > 25` (trend gücü — en kritik filtre)
2. `EMA9 > EMA21` (momentum yukarı)
3. `Close > EMA50` (orta vade yön)
4. `RSI 40–65` (momentum zone)
5. MACD bullish
6. Hacim > 1.2× MA (breakout onayı)

**XGBoost bypass:** Model %80+ güvenle BUY diyorsa kurallar ezilir.

**Risk yönetimi (ATR-based, Faz 6):**
- SL = giriş − 2.5 × ATR
- TP1 = giriş + 2.5 × ATR (%50 kapat, SL breakeven'e taşı)
- TP2 = giriş + 5.0 × ATR
- Trailing = peak − 2.0 × ATR
- `RISK_PER_TRADE = %2`, max pozisyon %20, portföy exposure %60
- Kill-switch: portföy −%15 → tüm botlar durur

**Semboller:** BTC, ETH, XRP, BNB, ADA, DOT (max 4 eş zamanlı pozisyon)

### B) Yeni 3-Bot Portföy Mimarisi (`bots/` + `core/portfolio_manager.py`)

Walk-forward validated, 40/40/20 sermaye dağılımı.

| Bot | Ağırlık | Strateji | Timeframe |
|---|---|---|---|
| **DCA** | %40 | Haftalık BTC 50 / ETH 50 birikimi, min $6/coin notional | Zaman bazlı |
| **Grid** | %40 | Rolling Bollinger range üzerinde 15 grid, sideways oyunu | 15m |
| **Trend** | %20 | 1h EMA200 rejim filtresi + XGBoost + ATR SL/TP | 15m |

`PortfolioManager` — ortak sermaye, per-bot high-water mark, otomatik sermaye ekleme protokolü, kill-switch, JSON state persistence (`data/portfolio_state.json`, `data/bot_state_*.json`).

## 4. Ticaret Altyapısı

- **Veri:** CCXT üzerinden Binance, exponential backoff retry, SQLite cache
- **ExchangeRules:** Emir öncesi `LOT_SIZE`, `stepSize`, `minNotional` doğrulaması (ghost pozisyon önlemi)
- **State recovery:** Bot çökerse pozisyon `trading/state_manager.py` üzerinden geri yüklenir
- **Fail-safe:** 5 ardışık hatada koruma moduna geçer (300 sn bekler), log spam engellenmiş
- **Telegram:** Sinyal/pozisyon/PnL bildirimleri
- **Partial TP:** 1.5R'de %50 kapat + kalan için SL breakeven

## 5. Backtest & Optimizasyon

- `backtest/engine.py` — cooldown/daily-limit devre dışı, partial TP simülasyonu
- `backtest/hyperopt.py` — parametre optimizasyonu
- `core/walkforward.py` — walk-forward validation (yeni bot'lar için)
- `tools/` altında 20+ keşif betiği:
  - Donchian evren seçimi (50/100 coin)
  - Hacim spike stratejisi analizi
  - Mean reversion, yeni listeleme fırsatı taraması
  - Hibrit portföy simülasyonu
  - Bot karşılaştırma, dashboard

## 6. Deployment

**Oracle Cloud** — canlı bot burada koşuyor (Docker), `ssh-key-2026-04-28.key` ile SSH.
**Yerel:** yalnızca analiz/test. `.env` içinde `TRADING_MODE=live` var → yerelde kazara canlıya gitmemek için `--live-confirm` bayrağı zorunlu (güvenlik kilidi).

`DEPLOYMENT_GUIDE.md`: Faz 1'de DCA bot $40 sermaye ile canlıya alım rehberi (adım adım). Hedef sermaye $400 → 160/160/80 dağıtımı.

## 7. Bağımlılıklar

`ccxt`, `pandas`, `numpy`, `pandas-ta`, `xgboost`, `scikit-learn`, `joblib`, `streamlit`, `plotly`, `python-telegram-bot`, `APScheduler`, `python-dotenv`, `pytest`

## 8. Mevcut Durum (git status snapshot)

- Değişiklikler var: `main.py`, `analysis/indicators.py`, `backtest/engine.py`, `strategy/signals.py`, `trading/executor.py`, `trading/risk_manager.py`, `notifications/notifier.py`, `data/collector.py`, `config/settings.py`, `Dockerfile`, `docker-compose.yml`, `requirements.txt` — henüz commit'lenmemiş
- Yeni dosyalar: `bots/`, `core/`, `tools/`, `analysis/ml_trainer.py`, `backtest/optimizer.py`, `backtest/fast_test.py`, `data/xgboost_model.joblib`, `data/donchian_universe.json`, `DEPLOYMENT_GUIDE.md`

**Son commit:** `48ae743 Update indicators, strategy, trading execution, risk management and notification improvements`

## 9. Proje Fazları (Evrim)

- **Faz 1:** BTC/ETH/SOL, closed candle, rejim filtresi
- **Faz 2:** State recovery, executor pattern, hyperopt, Docker
- **Faz 3:** Multi-risk stratejiler, 3 yıllık backtest altyapısı
- **Faz 4:** Kapsam genişletme, exchange rules validasyonu, Partial TP
- **Faz 5:** Momentum Rider (ADX + EMA hizalama + RSI zone)
- **Faz 6:** Coin evreni + parametre optimizasyonu, 4h timeframe, ATR SL/TP
- **Yeni mimari (2026-05-07):** 3-bot portföy (DCA + Grid + Trend), walk-forward validated

## 10. Öne Çıkan Riskler / Notlar

- Yerelde `.env` = live → tüm live giriş noktaları `--live-confirm` gerektiriyor
- XGBoost modeli (`data/xgboost_model.joblib`) 2022–2026 verisi ile eğitilmiş, live SL/TP ile etiket hizalı
- `tests/` klasörü boş — testler eksik
- Faz 5 monolitik bot (main.py) hâlâ mevcut, yeni bots/ mimarisi paralel olarak eklendi — iki sistem birlikte durur, canlıda Oracle'da eskisi çalışıyordu; deployment guide onu durdurup yeni yapıya geçişi anlatıyor
