## 🏛️ Architecture & Paths

- **Canonical Repository**: `/run/media/rodri/AI/skills/audiocpp/`
- **Binary Directory**: `/run/media/rodri/AI/audio.cpp` -> `/home/rodri/audio-v0.9.3-bin-ubuntu-x64-vulkan/`
- **Backend**: `vulkan` (`backends: cpu,vulkan`, `RADV GFX1200`; `BUILD.json` sha `41c1f8f`)
- **Alt build (experimental)**: `/home/rodri/audio-v0.9.3-bin-ubuntu-x64-rocm10.0.0-test/` — HIP/ROCm 10 test prebuilt (`--backend hip`, needs `LD_LIBRARY_PATH=/opt/rocm/lib`); measured 2–35x slower than the Vulkan build on this hardware, kept for upstream parity testing only
- **Server Config**: `/run/media/rodri/AI/audio.cpp/server.json` (Port `8081`)
- **GGUF Weights Directory**: `/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/`
- **Voice Clones Reference**: `/run/media/rodri/AI/voice/`
