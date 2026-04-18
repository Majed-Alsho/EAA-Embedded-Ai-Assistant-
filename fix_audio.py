from pydub import AudioSegment

# Load your current file
audio = AudioSegment.from_file("Mirror Light Routine.wav")

# Set to CD Standard: 44,100 Hz, 16-bit, Stereo
audio = audio.set_frame_rate(44100).set_sample_width(2).set_channels(2)

# Export the new version
audio.export("Pathetic_Game_Final_Master.wav", format="wav")
print("Export complete: 44.1kHz, 16-bit WAV ready for CD Baby.")