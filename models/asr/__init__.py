"""Deliberately empty. Used to eagerly import the old multilingual model_loader.py here,
which meant even `from models.asr.quantized_multilang_loader import ...` (torch-free) dragged
in model_loader.py's `import torch` as a side effect of Python initializing this package --
defeating part of the point of the 2026-08-07 switch to per-language quantized ONNX models
(see quantized_multilang_loader.py's module docstring). Import submodules directly instead:
    from models.asr.quantized_multilang_loader import QuantizedMultiLangASR
    from models.asr.model_loader import IndicConformerASR, SUPPORTED_LANGUAGES  # old model, still on disk
"""
