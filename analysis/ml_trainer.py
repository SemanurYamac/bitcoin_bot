"""
Makine Öğrenmesi Model Eğiticisi (XGBoost)
Geçmiş verileri (RSI, MACD, Hacim vb.) kullanarak
fiyatın bir sonraki dönemde kârlı bir yükseliş yapıp yapmayacağını tahmin eder.
"""
import sys
import os
import logging
import pandas as pd
import numpy as np
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, classification_report

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.collector import DataCollector
from analysis.indicators import TechnicalIndicators

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-8s | %(message)s')
logger = logging.getLogger('ml_trainer')

# ML Ayarları
COINS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT', 'ADA/USDT', 'DOT/USDT']
TIMEFRAME = '15m'
START_DATE = '2022-01-01'  # 4 yıllık veri: 2022 ayısı + 2024 boğası dahil
END_DATE = '2026-05-01'

# ─── Hedef Etiket (Label) Ayarları — LIVE SL/TP İLE HİZALI ─────────────────
#
# ÖNEMLİ: Bu etiket fonksiyonu, modelin tahmin etmeye çalıştığı şey ile
# botun gerçek hayatta yapacağı işlem arasında **birebir eşleşme** sağlar.
#
# Eski versiyon: +%0.8 / -%0.5 / 8 mum  →  live SL/TP ile uyumsuz, model
#   yanlış soruyu cevaplamayı öğreniyordu.
#
# Yeni versiyon: ATR-bazlı, live config'ten okuyor.
#   - PROFIT hedefi: giriş + ATR × ATR_TP1_MULT  (= live TP1)
#   - STOP koşulu: giriş − ATR × ATR_SL_MULT     (= live SL)
#   - LOOKAHEAD: 96 mum (24 saat) — trailing'in çalışması için yeterli süre
#
# Etiket kuralı: Sonraki LOOKAHEAD mumda PROFIT hedefine ulaştı VE öncesinde
# STOP'a değmedi → Label = 1 (kazanan trade).
TARGET_LOOKAHEAD = 96     # 24 saat × 4 mum/saat (15m) — trailing için yeterli

MODEL_SAVE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'xgboost_model.joblib')

def prepare_ml_features(df):
    """Teknik indikatörleri + piyasa duygusu verilerini ML feature'larına dönüştürür."""
    features = pd.DataFrame(index=df.index)

    # 1. RSI
    features['rsi'] = df['rsi']

    # 2. MACD
    features['macd_hist'] = df['macd_histogram']

    # 3. Bollinger Bant Konumu
    bb_range = df['bb_upper'] - df['bb_lower']
    features['bb_position'] = np.where(bb_range > 0, (df['close'] - df['bb_lower']) / bb_range, 0.5)

    # 4. Hacim Oranı
    features['volume_ratio'] = df['volume_ratio']

    # 5. EMA200'e uzaklık (trend rejimi göstergesi)
    features['ema_dist'] = (df['close'] - df['ema_long']) / df['ema_long'] * 100

    # 6. EMA50'nin EMA200'e göre konumu (golden/death cross tespiti)
    features['ema_cross'] = (df['ema_slow'] - df['ema_long']) / df['ema_long'] * 100

    # 7. Trend Gücü
    features['adx'] = df['adx']

    # 8. StochRSI (aşırı alım/satım)
    if 'stoch_rsi_k' in df.columns:
        features['stoch_rsi'] = df['stoch_rsi_k'].fillna(50)

    # 9. Funding Rate (piyasa duygusu — varsa)
    if 'funding_rate' in df.columns:
        features['funding_rate'] = df['funding_rate'].fillna(0) * 1000  # Ölçekle (0.0001 → 0.1)
        features['funding_trend'] = df['funding_rate'].rolling(3).mean().fillna(0) * 1000

    # 10. Fiyat momentum (son 4 mumun değişimi)
    features['price_momentum'] = df['close'].pct_change(4).fillna(0) * 100

    features = features.replace([np.inf, -np.inf], np.nan).fillna(0)

    return features

def create_labels(df, atr_sl_mult=None, atr_tp_mult=None):
    """
    Live trading SL/TP yapısıyla **birebir aynı** etiket oluşturur.

    Kural (her bar için):
      Giriş: bar i'nin close'u
      Stop:  giriş − ATR(i) × atr_sl_mult
      Hedef: giriş + ATR(i) × atr_tp_mult

      Sonraki TARGET_LOOKAHEAD mumda bar BY bar:
        - low ≤ stop ise          → kayıp (Label = 0, lookup biter)
        - high ≥ hedef ise         → kazanç (Label = 1, lookup biter)
        - hiçbiri olmazsa devam et
      Lookahead bittiğinde hâlâ pozisyon açıksa → Label = 0 (kararsız sayılır)

    Bu sıra önemli: live'da SL önce vurursa TP'ye ulaşma şansı yoktur.

    Args:
        df: ATR sütunu içermeli (TechnicalIndicators.calculate_all sonrası)
        atr_sl_mult: Live config'ten ATR_SL_MULT (default 1.0 — fast_test ile)
        atr_tp_mult: Live config'ten ATR_TP1_MULT (default 1.5)
    """
    # NOT: config/settings.py'deki ATR_SL_MULT/ATR_TP1_MULT (2.5/2.5) 4h timeframe için.
    # 15m timeframe'de live ayar 1.0/1.5 (fast_test ve trend_bot ile aynı). Yeni
    # mimari 15m kullandığı için default burada da 1.0/1.5.
    if atr_sl_mult is None:
        atr_sl_mult = 1.0
    if atr_tp_mult is None:
        atr_tp_mult = 1.5

    labels = np.zeros(len(df))
    close_prices = df['close'].values
    high_prices = df['high'].values
    low_prices = df['low'].values
    atr_values = df['atr'].values if 'atr' in df.columns else np.full(len(df), np.nan)

    for i in range(len(df) - TARGET_LOOKAHEAD):
        entry = close_prices[i]
        atr = atr_values[i]
        if np.isnan(atr) or atr <= 0:
            continue

        stop = entry - atr * atr_sl_mult
        target = entry + atr * atr_tp_mult

        # Sıralı bar-by-bar simülasyon
        for j in range(i + 1, i + 1 + TARGET_LOOKAHEAD):
            if low_prices[j] <= stop:
                # SL önce vurdu → kayıp
                break
            if high_prices[j] >= target:
                # TP vurdu → kazanan
                labels[i] = 1
                break

    return labels

def train_model():
    logger.info("Veriler toplanıyor ve Feature Engineering (Özellik Çıkarımı) yapılıyor...")
    collector = DataCollector()
    
    all_features = []
    all_labels = []
    
    for symbol in COINS:
        logger.info(f"{symbol} indiriliyor...")
        df_raw = collector.fetch_historical_data(symbol, TIMEFRAME, START_DATE, END_DATE)
        if df_raw.empty:
            continue

        # İndikatörleri hesapla
        df = TechnicalIndicators.calculate_all(df_raw)

        # Funding Rate ekle (Binance Futures — piyasa duygusu)
        try:
            fr_df = collector.fetch_funding_rates(symbol, START_DATE, END_DATE)
            if not fr_df.empty:
                # 8 saatlik funding rate'i 15m'ye forward-fill ile yay
                df = df.join(fr_df[['funding_rate']], how='left')
                df['funding_rate'] = df['funding_rate'].ffill().fillna(0)
                logger.info(f"  ✅ Funding rate eklendi ({symbol})")
        except Exception as e:
            logger.warning(f"  ⚠️ Funding rate atlandı ({symbol}): {e}")
            df['funding_rate'] = 0.0

        # NaN değerleri temizle
        df = df.dropna(subset=[c for c in df.columns if c != 'funding_rate']).copy()

        # Son 'TARGET_LOOKAHEAD' kadar mumu kes
        df = df.iloc[:-TARGET_LOOKAHEAD].copy()

        # Feature'ları ve Etiketleri oluştur
        features = prepare_ml_features(df)
        labels = create_labels(df)

        all_features.append(features)
        all_labels.append(labels)
        
    # Tüm coin verilerini tek bir devasa veri setinde birleştir
    X = pd.concat(all_features, ignore_index=True)
    y = np.concatenate(all_labels)
    
    logger.info(f"Toplam Veri Sayısı: {len(X)} Mum")
    logger.info(f"Başarılı Fırsat Sayısı (Label=1): {sum(y)} (%{sum(y)/len(y)*100:.1f})")
    
    if sum(y) < 50:
        logger.error("Yeterli başarılı örnek bulunamadı! Kar hedefini düşürün.")
        return
        
    # Veriyi Eğitim (%80) ve Test (%20) olarak ayır
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    logger.info("XGBoost Modeli Eğitiliyor...")
    
    # XGBoost Sınıflandırıcı (Dengesiz veri seti için scale_pos_weight kullanıyoruz)
    positive_ratio = (len(y) - sum(y)) / sum(y)
    
    model = XGBClassifier(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=5,
        scale_pos_weight=positive_ratio,  # Başarılı işlemler nadir olduğu için ağırlıklandır
        random_state=42,
        n_jobs=-1
    )
    
    model.fit(X_train, y_train)
    
    logger.info("Eğitim Tamamlandı. Model Test Ediliyor...")
    y_pred = model.predict(X_test)
    
    # Sonuçları Raporla
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred)
    
    logger.info(f"\nModel Başarısı:")
    logger.info(f"Genel Doğruluk (Accuracy): %{acc*100:.1f}")
    logger.info(f"Nokta Atışı Başarısı (Precision): %{prec*100:.1f} (Bot 'Al' dediğinde ne kadar haklı?)")
    logger.info(f"\nDetaylı Rapor:\n{classification_report(y_test, y_pred)}")
    
    # Modeli diske kaydet
    os.makedirs(os.path.dirname(MODEL_SAVE_PATH), exist_ok=True)
    joblib.dump(model, MODEL_SAVE_PATH)
    logger.info(f"✅ Model başarıyla kaydedildi: {MODEL_SAVE_PATH}")

if __name__ == '__main__':
    train_model()
