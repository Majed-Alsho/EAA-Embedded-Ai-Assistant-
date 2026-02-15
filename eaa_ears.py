import os
from faster_whisper import WhisperModel

# ==========================================
#   EAA AUDITORY CORTEX (WHISPER)
# ==========================================

# CONFIG
# Sizes: tiny.en (Fastest), base.en (Balanced), small.en (Accurate)
MODEL_SIZE = "tiny.en" 
DEVICE = "cuda" # Uses your GPU

class EarEngine:
    def __init__(self):
        print(f"[SYSTEM] 👂 Initializing Whisper ({MODEL_SIZE})...")
        try:
            self.model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type="float16")
            print("[SYSTEM] 👂 Auditory System Online.")
        except Exception as e:
            print(f"[ERROR] Ear Engine Failed: {e}")
            self.model = None

    def transcribe(self, audio_path):
        """Converts Audio File -> Text"""
        if not self.model: return ""
        
        segments, info = self.model.transcribe(audio_path, beam_size=5)
        text = " ".join([segment.text for segment in segments])
        return text.strip()

# Global Instance
ears = EarEngine()

def listen(file_path):
    if ears:
        return ears.transcribe(file_path)
    return ""

if __name__ == "__main__":
    # Test (You need a test.wav file to run this directly)
    print("Ears are ready. Waiting for API calls.")