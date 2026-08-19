"""
Model Export & INT8 Dynamic Quantization Script for Jetson Orin Nano.
Converts sentence-transformers/all-MiniLM-L6-v2 to optimized INT8 ONNX model.
"""
import logging
import os
import sys

# Force UTF-8 encoding on Windows terminals to prevent emoji/unicode errors
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
os.environ["PYTHONIOENCODING"] = "utf-8"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ONNX_Exporter")


def export_and_quantize(
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    output_dir: str = ".",
):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.join(base_dir, output_dir)
    os.makedirs(target_dir, exist_ok=True)

    fp32_onnx_path = os.path.join(target_dir, "model_fp32.onnx")
    int8_onnx_path = os.path.join(target_dir, "model_quantized.onnx")

    logger.info(f"Loading PyTorch model: {model_name}...")
    import torch
    from transformers import AutoModel, AutoTokenizer
    from onnxruntime.quantization import quantize_dynamic, QuantType

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval()

    dummy_text = ["Kisan Credit Card Scheme low interest crop loan 4 percent"]
    dummy_input = tokenizer(dummy_text, padding=True, truncation=True, return_tensors="pt")

    logger.info("Exporting to ONNX FP32...")
    torch.onnx.export(
        model,
        (dummy_input["input_ids"], dummy_input["attention_mask"]),
        fp32_onnx_path,
        input_names=["input_ids", "attention_mask"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch_size", 1: "sequence_length"},
            "attention_mask": {0: "batch_size", 1: "sequence_length"},
            "last_hidden_state": {0: "batch_size", 1: "sequence_length"},
        },
        opset_version=14,
        do_constant_folding=True,
    )

    logger.info(f"Applying INT8 dynamic quantization for Jetson Orin Nano (ARM64)...")
    quantize_dynamic(
        model_input=fp32_onnx_path,
        model_output=int8_onnx_path,
        weight_type=QuantType.QInt8,
    )

    fp32_size_mb = os.path.getsize(fp32_onnx_path) / (1024 * 1024)
    int8_size_mb = os.path.getsize(int8_onnx_path) / (1024 * 1024)
    logger.info(f"FP32 Model Size: {fp32_size_mb:.2f} MB")
    logger.info(f"INT8 Quantized Model Size: {int8_size_mb:.2f} MB (Compression: {(1 - int8_size_mb/fp32_size_mb)*100:.1f}%)")

    # Clean up intermediate FP32 model
    if os.path.exists(fp32_onnx_path):
        os.remove(fp32_onnx_path)

    logger.info(f"Quantized INT8 model ready at: {int8_onnx_path}")
    return int8_onnx_path


if __name__ == "__main__":
    export_and_quantize()
