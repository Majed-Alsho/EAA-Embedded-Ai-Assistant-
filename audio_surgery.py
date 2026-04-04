from pydub import AudioSegment
import os

input_file = "weekend.wav" 
output_file = "weekend_final.wav"

try:
    if os.path.exists(input_file):
        print(f"Starting surgery on {input_file}...")
        audio = AudioSegment.from_file(input_file)
        audio = audio.set_frame_rate(44100).set_sample_width(2).set_channels(2)
        audio.export(output_file, format="wav")
        print(f"SUCCESS: {output_file} created. Upload this to CD Baby.")
    else:
        print(f"Error: {input_file} not found in this folder.")
except Exception as e:
    print(f"Surgery failed: {str(e)}")
