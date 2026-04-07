"""
Makine Çökmesi ve Yeniden Başlama Durumları İçin State Management (Durum Yönetimi) Modülü
Botun açık işlemlerini diske güvenli şekilde yazar ve çökmelerden sonra geri yükler.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class StateManager:
    """
    Botun çalışma durumunu (açık pozisyonlar, aktif cooldown vs.) 
    diske yazan ve diskten okuyan yönetici sınıf.
    """

    def __init__(self, state_file=None):
        if state_file is None:
            # Proje ana dizinindeki data klasörü içine live_state/bot_state.json oluştur
            base_dir = Path(__file__).resolve().parent.parent
            self.state_dir = base_dir / 'data' / 'live_state'
            self.state_file = self.state_dir / 'bot_state.json'
        else:
            self.state_file = Path(state_file)
            self.state_dir = self.state_file.parent

        # Klasörleri oluştur (ilk defa çalışıyorsa)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Diskten durumu yükle
        self.state = self._load()

    def _load(self):
        """Diskteki `bot_state.json` dosyasını okur."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info("✅ Diskte bulunan önceki bot state verisi başarıyla yüklendi.")
                    return data
            except json.JSONDecodeError:
                logger.error("❌ State dosyası bozulmuş (JSON error). Temiz state başlatılıyor.")
            except Exception as e:
                logger.error(f"❌ State dosyası okunamadı: {e}. Temiz state başlatılıyor.")
        
        return {}

    def _save(self):
        """Mevcut bellek durumunu ('self.state') diske atomic şekilde yazar."""
        temp_file = self.state_file.with_suffix('.tmp')
        try:
            # Atomik yazma işlemi için geçici dosyayı (temp) kullan
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=4, ensure_ascii=False)
            
            # Kayıt başarılıysa asıl dosyanın üzerine yaz (Olası elektrik kesintisini önler)
            temp_file.replace(self.state_file)
        except Exception as e:
            logger.error(f"❌ State diske kaydedilemedi: {e}")

    def save_coin_state(self, symbol, state_data):
        """Belirli bir coinin tüm verilerini (pozisyon, stop riskleri vb.) günceller."""
        self.state[symbol] = state_data
        self._save()

    def get_coin_state(self, symbol):
        """Sadece belirli bir coinin kaydedilmiş son durumunu getirir."""
        return self.state.get(symbol, None)

    def update_coin_position(self, symbol, position_data):
        """Bir coinin state'indeki 'active_position' objesini kısmen günceller (Örn: Trailing stop değişimi)."""
        if symbol not in self.state:
            self.state[symbol] = {}
            
        self.state[symbol]['active_position'] = position_data
        self._save()

    def clear_coin_position(self, symbol):
        """Bir pozisyon kapandığında, pürüz bırakmamak için o coinin pozisyon state'ini temizler."""
        if symbol in self.state and 'active_position' in self.state[symbol]:
            self.state[symbol]['active_position'] = None
            self._save()
