"""
Edge ONNX Runtime Retrieval Engine for NVIDIA Jetson Orin Nano.
Provides INT8/FP16 quantized embedding inference and hybrid RRF retrieval
to meet the strict sub-45ms latency and <1.5GB memory constraint.
"""
import gc
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

# Configure thread limits for Jetson CPU cores to prevent contention
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Edge_ONNX_Retriever")

# Optional imports with graceful fallbacks
try:
    import onnxruntime as ort
    HAS_ORT = True
except ImportError:
    HAS_ORT = False
    logger.warning("onnxruntime not installed. Will fallback to SentenceTransformer / NumPy dot product.")

try:
    from transformers import AutoTokenizer
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False


class QuantizedONNXEmbedder:
    """
    Manages INT8/FP16 quantized ONNX embedding model inference.
    Supports CUDAExecutionProvider (TensorRT/CUDA on Jetson) and CPUExecutionProvider.
    """
    def __init__(
        self,
        model_name_or_path: str = "sentence-transformers/all-MiniLM-L6-v2",
        onnx_model_path: Optional[str] = None,
        use_cuda: bool = False,
    ):
        self.model_name = model_name_or_path
        self.use_cuda = use_cuda
        self.session = None
        self.tokenizer = None
        self.dimension = 384

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.onnx_path = onnx_model_path or os.path.join(base_dir, "model_quantized.onnx")

        self._init_tokenizer()
        self._init_onnx_session()

    def _init_tokenizer(self):
        if HAS_TRANSFORMERS:
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, local_files_only=True)
            except Exception:
                try:
                    self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                except Exception as e:
                    logger.warning(f"Could not load HuggingFace tokenizer: {e}")

    def _init_onnx_session(self):
        if not HAS_ORT or not os.path.exists(self.onnx_path):
            logger.info(f"ONNX model file not found at {self.onnx_path}. Using fallback sentence-transformers.")
            return

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.intra_op_num_threads = 2
        sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

        providers = ["CPUExecutionProvider"]
        if self.use_cuda and "CUDAExecutionProvider" in ort.get_available_providers():
            providers.insert(0, ("CUDAExecutionProvider", {
                "device_id": 0,
                "arena_extend_strategy": "kNextPowerOfTwo",
                "gpu_mem_limit": 1 * 1024 * 1024 * 1024,  # 1 GB VRAM limit on Jetson
                "cudnn_conv_algo_search": "EXHAUSTIVE",
                "do_copy_in_default_stream": True,
            }))

        try:
            self.session = ort.InferenceSession(self.onnx_path, sess_options=sess_options, providers=providers)
            logger.info(f"ONNX Runtime session initialized with providers: {self.session.get_providers()}")
        except Exception as e:
            logger.error(f"Failed to load ONNX session: {e}. Falling back to CPU.")
            self.session = ort.InferenceSession(self.onnx_path, sess_options=sess_options, providers=["CPUExecutionProvider"])

    def encode(self, texts: List[str], max_length: int = 128, batch_size: int = 32) -> np.ndarray:
        """
        Encodes a list of texts into normalized L2 dense embedding vectors with batching.
        """
        if self.session is not None and self.tokenizer is not None:
            all_embeddings = []
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i : i + batch_size]
                encoded_input = self.tokenizer(
                    batch_texts,
                    padding=True,
                    truncation=True,
                    max_length=max_length,
                    return_tensors="np"
                )
                ort_inputs = {
                    "input_ids": encoded_input["input_ids"].astype(np.int64),
                    "attention_mask": encoded_input["attention_mask"].astype(np.int64),
                }
                if "token_type_ids" in [inp.name for inp in self.session.get_inputs()]:
                    ort_inputs["token_type_ids"] = encoded_input.get(
                        "token_type_ids", np.zeros_like(encoded_input["input_ids"])
                    ).astype(np.int64)

                ort_outs = self.session.run(None, ort_inputs)
                token_embeddings = ort_outs[0]
                input_mask_expanded = np.expand_dims(encoded_input["attention_mask"], -1).astype(np.float32)
                sum_embeddings = np.sum(token_embeddings * input_mask_expanded, axis=1)
                sum_mask = np.clip(input_mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
                emb = sum_embeddings / sum_mask
                all_embeddings.append(emb)

            embeddings = np.vstack(all_embeddings)
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.clip(norms, a_min=1e-12, a_max=None)
            return (embeddings / norms).astype(np.float32)

        # Fallback to SentenceTransformer if ONNX runtime is absent
        from sentence_transformers import SentenceTransformer
        if not hasattr(self, "_fallback_st"):
            self._fallback_st = SentenceTransformer("all-MiniLM-L6-v2")
        emb = self._fallback_st.encode(texts, show_progress_bar=False, batch_size=batch_size)
        emb = np.array(emb, dtype=np.float32)
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        return (emb / np.clip(norms, a_min=1e-12, a_max=None)).astype(np.float32)
