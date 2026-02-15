{
  "1": {
    "inputs": {
      "ckpt_name": "ltx-2-19b-dev-fp8.safetensors"
    },
    "class_type": "CheckpointLoaderSimple",
    "_meta": {
      "title": "Load LTX Model"
    }
  },
  "2": {
    "inputs": {
      "text": "cinematic shot of a futuristic cyberpunk car driving in rain, neon lights, highly detailed, 8k",
      "clip": [
        "1",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "Positive Prompt"
    }
  },
  "3": {
    "inputs": {
      "text": "low quality, worst quality, deformed, blurry, watermark",
      "clip": [
        "1",
        1
      ]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {
      "title": "Negative Prompt"
    }
  },
  "4": {
    "inputs": {
      "width": 768,
      "height": 512,
      "batch_size": 16,
      "color": 0
    },
    "class_type": "EmptyLatentImage",
    "_meta": {
      "title": "Video Latents (16 frames)"
    }
  },
  "5": {
    "inputs": {
      "seed": 0,
      "steps": 20,
      "cfg": 3.0,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1.0,
      "model": [
        "1",
        0
      ],
      "positive": [
        "2",
        0
      ],
      "negative": [
        "3",
        0
      ],
      "latent_image": [
        "4",
        0
      ]
    },
    "class_type": "KSampler",
    "_meta": {
      "title": "Sampler"
    }
  },
  "6": {
    "inputs": {
      "samples": [
        "5",
        0
      ],
      "vae": [
        "1",
        2
      ]
    },
    "class_type": "VAEDecode",
    "_meta": {
      "title": "Decode"
    }
  },
  "7": {
    "inputs": {
      "filename_prefix": "EAA_Video_Render",
      "images": [
        "6",
        0
      ]
    },
    "class_type": "SaveImage",
    "_meta": {
      "title": "Save Output"
    }
  }
}