import asyncio
import edge_tts
import pygame
import os
import time

# ==========================================
#   VOICE LAB (SAFE & STABLE)
# ==========================================

TEXT = (
    "All systems online. Accessing the secure network. "
    "I am ready to assist you with your project, sir."
)

# THESE 3 ARE GUARANTEED TO WORK
CANDIDATES = [
    {
        "id": "A",
        "name": "Christopher (US) - Deepest / Most 'Movie-Like'",
        "voice": "en-US-ChristopherNeural", 
        "pitch": "+0Hz",
        "rate": "+0%"
    },
    {
        "id": "B",
        "name": "Ryan (UK) - The Standard 'Jarvis' Alternative",
        "voice": "en-GB-RyanNeural",
        "pitch": "+0Hz",
        "rate": "+0%"
    },
    {
        "id": "C",
        "name": "Connor (Irish) - The SMOOTHEST (Least Robotic)",
        "voice": "en-IE-ConnorNeural",
        "pitch": "+0Hz",
        "rate": "+0%"
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
        print(f"   [Audio Error]: {e}")

async def main():
    print("========================================")
    print("      GUARANTEED VOICE TEST             ")
    print("========================================")

    for c in CANDIDATES:
        print(f"\n🎧 Testing Option {c['id']}: {c['name']}")
        filename = f"test_{c['id']}.mp3"
        
        try:
            # Generate
            communicate = edge_tts.Communicate(TEXT, c['voice'], pitch=c['pitch'], rate=c['rate'])
            await communicate.save(filename)
            
            # Play
            print(f"   ▶️ Playing...")
            await play_audio(filename)
            
            # Cleanup
            try: os.remove(filename)
            except: pass
            
        except Exception as e:
            print(f"   ❌ Failed: {e}")
        
        time.sleep(0.5)

    print("\n========================================")
    print("WHICH LETTER WINS? (A, B, or C)")

if __name__ == "__main__":
    asyncio.run(main())