---
name: eryndal-audiobook
description: "Produce and QC the Eryndal audiobook (The Pale Road) on the GX10 cluster. Covers the engine choice (Kokoro reference voices + Chatterbox Original for expressiveness), the six-voice cast with cfg/exag settings, the parse/generate/post-process pipeline scripts, the GB10 aarch64 quirks that bite (float32, soundfile, --no-deps, protobuf), full-cast audiobook adaptation, and distribution. Use when generating/regenerating narration, tuning voices, parsing chapters for TTS, or post-processing audio."
---

# Eryndal Audiobook — TTS Production

Produce and QC the **Eryndal** audiobook (*The Pale Road*) on the GX10 cluster. Use
when generating or regenerating narration, tuning voices, parsing chapters for TTS,
post-processing audio, or planning distribution. Full technical doc:
`docs/TTS_PIPELINE_SUMMARY.md` (authoritative). Status: all 29 chapters generated
(WAV + MP3) in `narration/chapters/multicast/`; parsed scripts in
`narration/parsed/`. Reach the GX10 over SSH (`ssh` skill).

## Engine choice
**Kokoro generates reference voices → Chatterbox Original generates the audio.**
Kokoro gives clean, consistent voice *identity* (no actor cloning, no legal risk);
Chatterbox Original adds human *expressiveness* (cfg_weight + exaggeration). The
pre-generated Kokoro reference WAVs are fed to Chatterbox as `audio_prompt_path` —
no Kokoro step at generation time. **Rejected:** Chatterbox Turbo (no expressiveness
control), Dia (too slow, 2 speakers), Parler (poor), actor cloning (legal risk),
Voxtral (license grey zone).

## Voice cast
| Character | Kokoro ref | cfg | exag | Notes |
|-----------|-----------|-----|------|-------|
| Narrator | am_michael | 0.12 | 0.55 | all prose/description |
| Aldric | am_onyx | 0.15 | 0.45 | restrained, military |
| Tam | am_fenrir | 0.12 | 0.70 | warm, most expressive |
| Halric | am_santa | 0.15 | 0.40 | blunt, flat by design |
| Seris | af_nicole | 0.12 | 0.35 | guarded, precise (NOT af_sarah) |
| Dara | af_heart | 0.15 | 0.55 | pragmatic, young |

Reference WAVs: `narration/voice_refs/*.wav` (local) ←
`/root/tts_output/compare/refs/*.wav` (GX10 — **KEEP THESE**). Secondary characters
(Renn, Vessen, Coren, Nessa, Maren, Veren, Mera) reuse main-cast refs with adjusted
cfg/exag — see the table in `docs/TTS_PIPELINE_SUMMARY.md`.

## Pipeline (scripts in `scripts/`)
1. `parse_chapter.py` — split chapter text into narrator vs. dialogue segments →
   `narration/parsed/*.json` (done: 29 chapters, 2,307 segments, 11 speakers).
2. `generate_chapter.py` — persistent Chatterbox server on GX10, per-segment
   generation by voice, stitch + post-process. Multicast + narrated modes; resumes
   on failure.
3. `generate_narration.py` — uploads a ref to GX10, runs Chatterbox, downloads.
- Stitch with 0.2–0.7s pauses by context.
- **Post-process locally** (ffmpeg not on GX10):
  `highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=50,loudnorm=I=-16:TP=-1.5:LRA=11`

## GB10 (aarch64) quirks — don't get burned
- `librosa` returns float64; Chatterbox mel expects float32 (Turbo patched with
  `.astype("float32")`; Original `tts.py` is fine).
- `torchaudio.save()` broken (no torchcodec) → use `soundfile.write()`.
- Install with `--no-deps` to avoid pulling x86 torch/triton wheels that break the
  aarch64 build; restore triton from `/root/vllm-build/triton` if overwritten.
- protobuf 3.x breaks onnx → `uv pip install "protobuf>=4.25" --force-reinstall`.
- Package manager: `uv` for the vLLM venv (`/root/vllm-build/.venv`, Chatterbox),
  `pip` for the TTS venv (`/root/tts-venv`, Kokoro). Stop vLLM during heavy TTS work.

## Audiobook adaptation
Full-cast (narrator + character voices) — rare in audiobooks, fits Eryndal's strong
distinct voices. In full-cast: move/cut attribution tags ("X said") when the voice
identifies the speaker; keep action beats with the narrator; em-dashes read as
natural pauses. Maintain a find-replace **pronunciation map** for fantasy terms
(e.g. "Vael'Sorn" → "Vail Soarn"). Chapter 15 is merged into Chapter 14 — keep
audio numbering consistent.

## Remaining / distribution
Open: finalise the pronunciation map, Chapter-1 QC pass, light per-chapter audio-
adaptation edit, full QC listen + regenerate artefact segments. Distribution:
ACX/Audible, Spotify, Apple Books Audio, direct sales — consider chapter-by-chapter
release to match a serialized book launch.
