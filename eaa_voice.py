import asyncio
import edge_tts
import pygame
import threading
import queue
import os
import time

# ==========================================
#   EAA VOICE ENGINE (LOCKED: CHRISTOPHER)
# ==========================================

# The "Hollywood" Standard (Jarvis-style)
VOICE_MODEL = "en-US-ChristopherNeural"

# TUNING: Pure audio (Maximum Fidelity, No Robotic Artifacts)
RATE = "+0%"
VOLUME = "+0%"
PITCH = "+0Hz" 

class VoiceEngine:
    def __init__(self):
        print(f"[SYSTEM] 🔊 Initializing Neural Voice ({VOICE_MODEL})...")
        self.queue = queue.Queue()
        self.is_ready = False
        
        try:
            pygame.mixer.init()
            self.is_ready = True
            print(f"[SYSTEM] 🔊 Voice System Online.")
        except Exception as e:
            print(f"[ERROR] Audio System Failed: {e}")

        # Start Background Worker
        threading.Thread(target=self._worker_loop, daemon=True).start()

    def speak(self, text):
        """Add text to the speech queue"""
        if self.is_ready:
            self.queue.put(text)

    def _worker_loop(self):
        """Process the queue one by one"""
        while True:
            text = self.queue.get()
            if text is None: break

            try:
                # Run the async generation in this thread
                asyncio.run(self._generate_and_play(text))
            except Exception as e:
                print(f"[ERROR] Voice Generation Failed: {e}")
            
            self.queue.task_done()

    async def _generate_and_play(self, text):
        """Generate MP3 -> Play -> Delete"""
        # Use unique filename to avoid file permission locks
        temp_file = f"temp_voice_{int(time.time())}.mp3"
        try:
            # 1. Generate Audio
            communicate = edge_tts.Communicate(text, VOICE_MODEL, rate=RATE, volume=VOLUME, pitch=PITCH)
            await communicate.save(temp_file)

            # 2. Play Audio
            pygame.mixer.music.load(temp_file)
            pygame.mixer.music.play()

            # 3. Wait for playback to finish
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10) # Check every 10ms

            # 4. Cleanup
            pygame.mixer.music.unload()
            
        except Exception as e:
            print(f"[VOICE ERROR] {e}")
        
        finally:
            # Always try to delete the temp file
            if os.path.exists(temp_file):
                try:
                    time.sleep(0.1) # Brief pause to release file handle
                    os.remove(temp_file)
                except:
                    pass

# Global Instance
voice = VoiceEngine()

def say(text):
    if voice:
        voice.speak(text)

if __name__ == "__main__":
    print("Testing Final Configuration...")
    say("Voice calibration complete. I am ready for deployment, sir.")
    time.sleep(5)