# CSTR Model Suite & CrispEmbed Ecosystem

Comprehensive guide to the `cstr` model family (`https://huggingface.co/cstr/`) and its local deployment on this workstation.

---

## 🔬 What is `cstr`?

`cstr` is an open model organization on Hugging Face created in tandem with the **[CrispEmbed](https://github.com/CrispStrobe/CrispEmbed)** project. 

Its mission is providing **purpose-built, ultra-lightweight GGUF and GGML quantizations** for edge and workstation computer vision tasks:
- Document understanding & structured DocTags layout generation
- Text detection (DBNet, PP-OCRv6)
- Text recognition (TrOCR, PARSeq, PP-OCRv6, GLM-OCR)
- Mathematical expression & LaTeX OCR (HMER, BTTR, PP-FormulaNet, Pix2Tex)

All `cstr` models run with **zero cloud dependencies** and minimal VRAM/RAM overhead.

---

## 📂 Models Available Locally (`/run/media/rodri/AI/models/cstr`)

### 1. `smoldocling-GGUF` (`smoldocling-q8_0.gguf` — 261 MB)
- **Base Model**: `ds4sd/SmolDocling-256M-preview` by IBM Research (Docling Team).
- **Architecture**:
  - **Vision**: SigLIP ViT (12 layers, 768 dim, 12 heads, patch=16, 512px).
  - **Connector**: Pixel shuffle (scale=4, 1024 → 64 tokens) + Linear projection (12288 → 576).
  - **Language Model**: SmolLM2-135M (30 layers, 576 dim, GQA 9/3, SwiGLU, RoPE).
  - **Total Parameters**: 256M.
- **Output Format**: Structured **DocTags** XML markup:
  ```xml
  <doctag><title>Document Title</title><paragraph>...</paragraph><table>...</table></doctag>
  ```
- **Workstation Ranking**: **#2 OCR & Document Specialist** (right behind `LightOnOCR-3-1B`). While LightOnOCR excels at rapid video frame and slide transcriptions, SmolDocling excels when document structure (tables, hierarchical headings, formulas, and layouts) must be parsed cleanly into structured Markdown or JSON.

### 2. `dbnet-ic15-GGUF` (`dbnet-ic15-f16.gguf` / `q8_0` — 13 to 24 MB)
- **Base Model**: OpenMMLab MMOCR `dbnet_resnet18_fpnc_1200e_icdar2015`.
- **Architecture**: ResNet-18 backbone + FPNC (FPN-Cat) neck + DBHead probability branch.
- **Role**: Primary text detector for CrispEmbed. Outputs oriented bounding boxes and polygonal coordinates for text lines and words across natural images, scanned documents, and UI screenshots.
- **Performance**: 12.2M parameters. All BatchNorm layers folded into Conv weights for extreme inference speed on CPU and GPU.

### 3. `glm-ocr-crispembed-GGUF` (`glm-ocr-q8_0.gguf` — 1.18 GB)
- **Base Model**: GLM-OCR vision-language model quantized for CrispEmbed inference.
- **Role**: Multimodal document and table recognition, bridging classic OCR pipelines with full vision-language decoding.

### 4. `parseq-GGUF` (`parseq-q8_0.gguf` — 25 MB)
- **Base Model**: Permutation Autoregressive Sequence (PARSeq, ECCV 2022).
- **Architecture**: ViT encoder + autoregressive Transformer decoder (24M parameters).
- **Role**: State-of-the-art scene-text recognition on challenging, distorted, or curved word crops.

### 5. `PP-OCRv6-small-det-GGUF` (`PP-OCRv6_small_det-f16.gguf` — 4.9 MB)
- **Architecture**: Ultra-compact text detector with DB++ neck.
- **Role**: Line-level text detector designed for ultra-low latency on both CPU and Vulkan/ROCm backends.

### 6. `PP-OCRv6_small_rec-GGUF` (`PP-OCRv6_small_rec-q8-head.gguf` — 21 MB)
- **Architecture**: Compact CTC text recognizer (F32 backbone with Q8 head).
- **Languages**: Multilingual support covering Latin, CJK, Japanese Kana, and Greek.

### 7. `trocr-small-printed-GGUF` (`trocr-small-printed-q8_0.gguf` — 67 MB)
- **Base Model**: Microsoft TrOCR small printed.
- **Role**: Paired with `dbnet-ic15` in CrispEmbed to perform end-to-end detection and recognition of printed text.

---

## 🧮 Mathematical & Formula OCR Models (`cstr` Registry)

The `cstr` organization also maintains dedicated mathematical formula recognition GGUFs utilized in CrispEmbed regression fixtures:

| Model | Arch / Parameters | Size | Target Domain |
|---|---|---|---|
| **`hmer-hw`** | DenseNet-121 + GRU | 5 MB | Handwritten math OCR |
| **`bttr-hw`** | DenseNet + Transformer | 11 MB | Bidirectional handwritten math |
| **`ppformulanet-l`** | SAM-ViT + MBart (181M) | 252 MB | Printed mathematical formulas |
| **`posformer-crohme`** | DenseNet + Transformer + ARM | 12 MB | CROHME competition math benchmark |
| **`pix2tex-mfr`** | DeiT + TrOCR (28M) | 17 MB | LaTeX math formula extraction |
| **`texo-distill`** | HGNetv2 + MBart (20M) | 22 MB | Distilled compact LaTeX generator |

---

## 🚀 Running & Consuming `cstr` Models

### 1. Via CrispEmbed CLI (`/run/media/rodri/AI/CrispEmbed`)
```bash
# Full pipeline: DBNet detection + TrOCR recognition
crispembed --det /run/media/rodri/AI/models/cstr/dbnet-ic15-GGUF/dbnet-ic15-f16.gguf \
          -m /run/media/rodri/AI/models/cstr/trocr-small-printed-GGUF/trocr-small-printed-q8_0.gguf \
          --ocr image.png

# SmolDocling document understanding
crispembed -m /run/media/rodri/AI/models/cstr/smoldocling-GGUF/smoldocling-q8_0.gguf \
          --ocr page_scan.png
```

### 2. Via Local HTTP Server (`:8084`)
Launch the CrispEmbed local inference service:
```bash
/run/media/rodri/AI/skills/launchers/crispembed-ocr.sh
```
Send an image for instant transcription:
```bash
curl -X POST http://127.0.0.1:8084/ocr -F "image=@diagram.png"
```
