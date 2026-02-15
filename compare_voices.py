import asyncio
import edge_tts
import pygame
import os
import time

# ==========================================
#   VOICE REALISM TEST
# ==========================================

TEST_TEXT = (
    "I am fully online. All systems are functioning within normal parameters. "
    "This is a test of the neural interface. "
    "I am ready to assist you."
)

VARIANTS = [
    {
        "id": 1,
        "name": "Christopher (Raw - Most Human)",
        "voice": "en-US-ChristopherNeural",
        "pitch": "+0Hz", # No modification
        "rate": "+0%"
    },
    {
        "id": 2,
        "name": "Christopher (Slightly Deep)", 
        "voice": "en-US-ChristopherNeural",
        "pitch": "-2Hz", # Subtle depth
        "rate": "+0%"
    },
    {
        "id": 3,
        "name": "Ryan (British Jarvis)",
        "voice": "en-GB-RyanNeural",
        "pitch": "+0Hz", # No modification
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
        print(f"[ERROR] Could not play audio: {e}")

async def main():
    print("========================================")
    print("      REALISM COMPARISON TEST           ")
    print("========================================")

    for v in VARIANTS:
        print(f"\n🎧 Generating Option {v['id']}: {v['name']}...")
        filename = f"test_voice_{v['id']}.mp3"
        
        # Generate
        communicate = edge_tts.Communicate(TEST_TEXT, v['voice'], pitch=v['pitch'], rate=v['rate'])
        await communicate.save(filename)
        
        # Play
        print(f"   ▶️ Playing...")
        await play_audio(filename)
        
        # Cleanup
        try: os.remove(filename)
        except: pass
        
        time.sleep(0.5)

    print("\n========================================")
    print("Which one sounded best? (1, 2, or 3?)")

if __name__ == "__main__":
    asyncio.run(main())