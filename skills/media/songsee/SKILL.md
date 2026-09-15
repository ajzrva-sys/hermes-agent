---
name: songsee
description: "Audio spectrograms/features (mel, chroma, MFCC) via CLI."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows, freebsd]
metadata:
  hermes:
    tags: [Audio, Visualization, Spectrogram, Music, Analysis]
    homepage: https://github.com/steipete/songsee
prerequisites:
  commands: [songsee]
---

# songsee

Generate spectrograms and multi-panel audio feature visualizations from audio files.

## Prerequisites

Requires a native `songsee` executable. [Go](https://go.dev/doc/install) is needed only when building from source, not when using a native package:
```bash
go install github.com/steipete/songsee/cmd/songsee@latest
```

Optional: `ffmpeg` for formats beyond WAV/MP3.

### FreeBSD invocation

Prefer the native package route: use `terminal` to check `pkg info songsee` and `sh -c 'command -v songsee'` before requesting any installation. If it is missing, probe the configured FreeBSD package catalog for `songsee`; package availability is not proof of installation. Do not substitute a downloaded Linux binary. A source build is a separate fallback requiring an approved native Go toolchain and a reviewed, pinned version instead of `@latest`.

Use the resolved executable explicitly. These examples assume the native package installed `/usr/local/bin/songsee`; replace that path if command resolution reports a different native executable. Run through `terminal`:

```sh
/usr/local/bin/songsee --help
/usr/local/bin/songsee track.wav -o spectrogram.png
sh -c '"$HERMES_HOME/tool-envs/media/bin/python" -c "from PIL import Image; im=Image.open(\"spectrogram.png\"); im.load(); assert im.width > 0 and im.height > 0; print(im.size)"'
```

Resolve the active `HERMES_HOME` before the last command; its user-owned media environment supplies Pillow for verification, not for running songsee. Explicit `sh -c` avoids tcsh syntax differences without changing global PATH or Hermes' shared interpreter. Start with a short local WAV and verify a decodable image, not just a zero CLI exit; inspect the result with `vision_analyze`. Non-WAV/MP3 decoding needs a separate ffmpeg check.

## Quick Start

```bash
# Basic spectrogram
songsee track.mp3

# Save to specific file
songsee track.mp3 -o spectrogram.png

# Multi-panel visualization grid
songsee track.mp3 --viz spectrogram,mel,chroma,hpss,selfsim,loudness,tempogram,mfcc,flux

# Time slice (start at 12.5s, 8s duration)
songsee track.mp3 --start 12.5 --duration 8 -o slice.jpg

# From stdin
cat track.mp3 | songsee - --format png -o out.png
```

## Visualization Types

Use `--viz` with comma-separated values:

| Type | Description |
|------|-------------|
| `spectrogram` | Standard frequency spectrogram |
| `mel` | Mel-scaled spectrogram |
| `chroma` | Pitch class distribution |
| `hpss` | Harmonic/percussive separation |
| `selfsim` | Self-similarity matrix |
| `loudness` | Loudness over time |
| `tempogram` | Tempo estimation |
| `mfcc` | Mel-frequency cepstral coefficients |
| `flux` | Spectral flux (onset detection) |

Multiple `--viz` types render as a grid in a single image.

## Common Flags

| Flag | Description |
|------|-------------|
| `--viz` | Visualization types (comma-separated) |
| `--style` | Color palette: `classic`, `magma`, `inferno`, `viridis`, `gray` |
| `--width` / `--height` | Output image dimensions |
| `--window` / `--hop` | FFT window and hop size |
| `--min-freq` / `--max-freq` | Frequency range filter |
| `--start` / `--duration` | Time slice of the audio |
| `--format` | Output format: `jpg` or `png` |
| `-o` | Output file path |

## Notes

- WAV and MP3 are decoded natively; other formats require `ffmpeg`
- Output images can be inspected with `vision_analyze` for automated audio analysis
- Useful for comparing audio outputs, debugging synthesis, or documenting audio processing pipelines
