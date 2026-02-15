import asyncio
import edge_tts
import pygame
import os
import time

# ==========================================
#   THE VOICE GALLERY (CANDIDATE SELECTION)
# ==========================================

TEXT = (
    "Initializing secure server. Biometrics confirmed. "
    "Welcome back, sir. I am ready for your next instruction."
)

# The Top 5 Best Male Neural Voices
CANDIDATES = [
    {
        "id": 1,
        "name": "Christopher (US) - Professional, Calm",
        "voice": "en-US-ChristopherNeural"
    },
    {
        "id": 2,
        "name": "Eric (US) - Deep, Authoritative",
        "voice": "en-US-EricNeural"
    },
    {
        "id": 3,
        "name": "Thomas (UK) - Formal, Classic Jarvis",
        "voice": "en-GB-ThomasNeural" 
    },
    {
        "id": 4,
        "name": "Ryan (UK) - Modern, Helpful",
        "voice": "en-GB-RyanNeural"
    },
    {
        "id": 5,
        "name": "William (Australia) - Unique, High-Tech",
        "voice": "en-AU-WilliamNeural"
    }
]

async def play_audio(filename):
    try:
        pygame.mixer.init()
        pygame.mixer.music.load(filename)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        pygame.mixer.music.unload()
        pygame.mixer.quit()
    except Exception as e:
        print(f"   [Error playing audio]: {e}")

async def main():
    print("========================================")
    print("      NEURAL VOICE GALLERY              ")
    print("========================================")
    print("Generating 5 candidates... (Please wait)\n")

    for c in CANDIDATES:
        filename = f"voice_test_{c['id']}.mp3"
        print(f"👉 Candidate #{c['id']}: {c['name']}")
        
        # Generate (Pure, no pitch shift for max quality)
        communicate = edge_tts.Communicate(TEXT, c['voice'])
        await communicate.save(filename)
        
        # Play
        print(f"   🔊 Playing...")
        await play_audio(filename)
        time.sleep(0.5) 
        
        # Cleanup
        try: os.remove(filename)
        except: pass
        print("-" * 40)

    print("\n========================================")
    print("DECISION TIME: Which ID (1-5) sounded best?")

if __name__ == "__main__":
    asyncio.run(main())