# Derived from Rizzo Flow, src/rizzo_flow/llama_cpp.py at commit b9ba007e
# (https://github.com/Rizzo-AI-Academy/rizzo-flow). Copyright 2026 Simone Rizzo — Rizzo AI
# Academy. Licensed under the Apache License, Version 2.0.
# Changed for Jiffin: Windows and CUDA only; the GPU is chosen without options; the load mode
# and the KV cache come from the engine settings; a failed load says whether the GPU ran out of
# memory; the model type is read; greedy sampling and detokenizing added for generation; type
# annotations; what the engine does not use is left out.
"""ctypes binding to libllama, limited to what the engine needs: scoring and greedy generation.

Struct layouts and signatures are transcribed from `include/llama.h` and
`ggml/include/ggml-backend.h` of the release pinned in `llama_release.py`. Structs are passed
by value, so a library built from another commit can crash instead of failing cleanly.
"""

import collections
import ctypes
import os
import sys
from collections.abc import Iterable, Sequence
from ctypes import (
    POINTER,
    c_bool,
    c_char_p,
    c_float,
    c_int,
    c_int8,
    c_int32,
    c_size_t,
    c_uint32,
    c_void_p,
)
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Self

from jiffin.engine import llama_release
from jiffin.engine.errors import GpuOutOfMemory, ModelNotLoadable

GPU_LAYERS = 999  # more than any model has: offload everything
DEVICE_TYPE_GPU = 1  # enum ggml_backend_dev_type
# enum llama_load_mode. With direct I/O llama.cpp reads the file instead of mapping it, and
# falls back to plain reads where direct I/O is not available (llama-mmap.cpp).
LOAD_MODES = {"direct_io": 4, "mmap": 1}
KV_TYPES = {"f16": 1}  # enum ggml_type
SPLIT_MODE_NONE = 0
LOG_LEVEL_WARN, LOG_LEVEL_ERROR = 3, 4


class ModelParams(ctypes.Structure):
    _fields_ = [
        ("devices", POINTER(c_void_p)),
        ("tensor_buft_overrides", c_void_p),
        ("n_gpu_layers", c_int32),
        ("split_mode", c_int),
        ("load_mode", c_int),
        ("lazy_mode", c_int),
        ("main_gpu", c_int32),
        ("tensor_split", c_void_p),
        ("progress_callback", c_void_p),
        ("progress_callback_user_data", c_void_p),
        ("kv_overrides", c_void_p),
        ("vocab_only", c_bool),
        ("check_tensors", c_bool),
        ("use_extra_bufts", c_bool),
        ("no_host", c_bool),
        ("no_alloc", c_bool),
        ("load_mtp", c_bool),
    ]


class ContextParams(ctypes.Structure):
    _fields_ = [
        ("n_ctx", c_uint32),
        ("n_batch", c_uint32),
        ("n_ubatch", c_uint32),
        ("n_seq_max", c_uint32),
        ("n_rs_seq", c_uint32),
        ("n_outputs_max", c_uint32),
        ("n_outputs_max_per_seq", c_uint32),
        ("n_threads", c_int32),
        ("n_threads_batch", c_int32),
        ("ctx_type", c_int),
        ("rope_scaling_type", c_int),
        ("pooling_type", c_int),
        ("attention_type", c_int),
        ("flash_attn_type", c_int),
        ("rope_freq_base", c_float),
        ("rope_freq_scale", c_float),
        ("yarn_ext_factor", c_float),
        ("yarn_attn_factor", c_float),
        ("yarn_beta_fast", c_float),
        ("yarn_beta_slow", c_float),
        ("yarn_orig_ctx", c_uint32),
        ("defrag_thold", c_float),
        ("cb_eval", c_void_p),
        ("cb_eval_user_data", c_void_p),
        ("type_k", c_int),
        ("type_v", c_int),
        ("abort_callback", c_void_p),
        ("abort_callback_data", c_void_p),
        ("embeddings", c_bool),
        ("offload_kqv", c_bool),
        ("no_perf", c_bool),
        ("op_offload", c_bool),
        ("swa_full", c_bool),
        ("kv_unified", c_bool),
        ("samplers", c_void_p),
        ("n_samplers", c_size_t),
        ("ctx_other", c_void_p),
    ]


class Batch(ctypes.Structure):
    _fields_ = [
        ("n_tokens", c_int32),
        ("token", POINTER(c_int32)),
        ("embd", POINTER(c_float)),
        ("pos", POINTER(c_int32)),
        ("n_seq_id", POINTER(c_int32)),
        ("seq_id", POINTER(POINTER(c_int32))),
        ("logits", POINTER(c_int8)),
    ]


LOG_CALLBACK = ctypes.CFUNCTYPE(None, c_int, c_char_p, c_void_p)

# name -> (result, arguments). Looked up in libllama first, then in the ggml libraries.
SIGNATURES: dict[str, tuple[Any, list[Any]]] = {
    "llama_log_set": (None, [LOG_CALLBACK, c_void_p]),
    "llama_backend_init": (None, []),
    "llama_model_default_params": (ModelParams, []),
    "llama_context_default_params": (ContextParams, []),
    "llama_model_load_from_file": (c_void_p, [c_char_p, ModelParams]),
    "llama_model_free": (None, [c_void_p]),
    "llama_init_from_model": (c_void_p, [c_void_p, ContextParams]),
    "llama_free": (None, [c_void_p]),
    "llama_model_get_vocab": (c_void_p, [c_void_p]),
    "llama_model_meta_val_str": (c_int32, [c_void_p, c_char_p, c_char_p, c_size_t]),
    "llama_model_desc": (c_int32, [c_void_p, c_char_p, c_size_t]),
    "llama_model_chat_template": (c_char_p, [c_void_p, c_char_p]),
    "llama_tokenize": (
        c_int32,
        [c_void_p, c_char_p, c_int32, POINTER(c_int32), c_int32, c_bool, c_bool],
    ),
    "llama_detokenize": (
        c_int32,
        [c_void_p, POINTER(c_int32), c_int32, c_char_p, c_int32, c_bool, c_bool],
    ),
    "llama_vocab_is_eog": (c_bool, [c_void_p, c_int32]),
    "llama_sampler_init_greedy": (c_void_p, []),
    "llama_sampler_sample": (c_int32, [c_void_p, c_void_p, c_int32]),
    "llama_sampler_free": (None, [c_void_p]),
    "llama_n_batch": (c_uint32, [c_void_p]),
    "llama_get_memory": (c_void_p, [c_void_p]),
    "llama_memory_clear": (None, [c_void_p, c_bool]),
    "llama_memory_seq_cp": (None, [c_void_p, c_int32, c_int32, c_int32, c_int32]),
    "llama_memory_seq_rm": (c_bool, [c_void_p, c_int32, c_int32, c_int32]),
    "llama_decode": (c_int32, [c_void_p, Batch]),
    "llama_synchronize": (None, [c_void_p]),
    "llama_get_logits_ith": (POINTER(c_float), [c_void_p, c_int32]),
    "ggml_backend_load_all_from_path": (None, [c_char_p]),
    "ggml_backend_dev_count": (c_size_t, []),
    "ggml_backend_dev_get": (c_void_p, [c_size_t]),
    "ggml_backend_dev_description": (c_char_p, [c_void_p]),
    "ggml_backend_dev_memory": (None, [c_void_p, POINTER(c_size_t), POINTER(c_size_t)]),
    "ggml_backend_dev_type": (c_int, [c_void_p]),
}


@dataclass(frozen=True)
class Device:
    handle: int
    description: str  # e.g. NVIDIA GeForce RTX 4060 Laptop GPU
    kind: int  # enum ggml_backend_dev_type
    total_bytes: int


class Library:
    """The loaded runtime: libllama plus the ggml libraries and compute backends beside it."""

    _loaded: ClassVar[dict[Path, "Library"]] = {}

    if TYPE_CHECKING:
        # The functions of SIGNATURES, bound in __init__.
        def __getattr__(self, name: str) -> Any: ...

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.errors: collections.deque[str] = collections.deque(maxlen=16)
        """The latest error lines of llama.cpp and ggml."""
        self._handles = self._open()
        for name, (result, arguments) in SIGNATURES.items():
            function = next((getattr(h, name) for h in self._handles if hasattr(h, name)), None)
            if function is None:
                raise ModelNotLoadable(
                    f"{self.directory}: symbol {name} is missing; the runtime must be llama.cpp "
                    f"{llama_release.RELEASE} ({llama_release.COMMIT[:7]})"
                )
            function.restype, function.argtypes = result, arguments
            setattr(self, name, function)

        def log(level: int, text: bytes, _: object) -> None:
            # Warnings and errors only; level 5 continues a line that was probably dropped.
            # The full-size window cache is our own choice (see Session.load), not news.
            line = text.decode("utf-8", errors="replace")
            if level == LOG_LEVEL_ERROR:
                self.errors.append(line)
            if level in (LOG_LEVEL_WARN, LOG_LEVEL_ERROR) and "full-size SWA cache" not in line:
                sys.stderr.write(line)

        self._log = LOG_CALLBACK(log)  # referenced for the life of the library
        self.llama_log_set(self._log, None)
        # Release builds ship every compute backend as a plug-in next to libllama.
        self.ggml_backend_load_all_from_path(str(self.directory).encode())
        self.llama_backend_init()

    @classmethod
    def open(cls, directory: Path) -> "Library":
        """One instance per directory and process: backends register globally in ggml."""
        directory = directory.resolve()
        if directory not in cls._loaded:
            cls._loaded[directory] = cls(directory)
        return cls._loaded[directory]

    def _open(self) -> list[ctypes.CDLL]:
        folder = str(self.directory)
        # Dependencies of the plug-ins (CUDA runtime, OpenMP) sit in the same folder.
        os.add_dll_directory(folder)
        if folder not in os.environ.get("PATH", ""):
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
        handles = [
            ctypes.CDLL(str(self.directory / f"{stem}.dll"))
            for stem in ("ggml-base", "ggml", "llama")
        ]
        return handles[::-1]

    def devices(self) -> list[Device]:
        found = []
        for index in range(self.ggml_backend_dev_count()):
            handle = self.ggml_backend_dev_get(index)
            free, total = c_size_t(), c_size_t()
            self.ggml_backend_dev_memory(handle, ctypes.byref(free), ctypes.byref(total))
            found.append(
                Device(
                    handle,
                    self.ggml_backend_dev_description(handle).decode(),
                    self.ggml_backend_dev_type(handle),
                    total.value,
                )
            )
        return found

    def free_bytes(self, device: Device) -> int:
        free, total = c_size_t(), c_size_t()
        self.ggml_backend_dev_memory(device.handle, ctypes.byref(free), ctypes.byref(total))
        return free.value


def load_failure(message: str, errors: Iterable[str]) -> ModelNotLoadable | GpuOutOfMemory:
    """The error of a load that failed, from the error lines llama.cpp logged meanwhile."""
    # ggml's CUDA backend logs "cudaMalloc failed: out of memory" (ggml-cuda.cu, b11081).
    if any("out of memory" in line for line in errors):
        return GpuOutOfMemory(f"{message}: the GPU is out of memory")
    return ModelNotLoadable(message)


def choose_gpu(devices: list[Device]) -> Device | None:
    """The GPU that runs the whole model: the dedicated one with the most memory."""
    gpus = [device for device in devices if device.kind == DEVICE_TYPE_GPU]
    return max(gpus, key=lambda device: device.total_bytes, default=None)


class Session:
    """One model and one context. Sequence 0 holds the shared prefix, the others its branches."""

    def __init__(
        self, library: Library, model: int, context: int, device: Device, n_batch: int
    ) -> None:
        self.library = library
        self.model = model
        self.context = context
        self.device = device
        self.n_batch = n_batch
        self.vocab: int = library.llama_model_get_vocab(model)
        self.memory: int = library.llama_get_memory(context)
        self.sampler: int = library.llama_sampler_init_greedy()

    @classmethod
    def load(
        cls,
        gguf: Path,
        *,
        directory: Path,
        n_ctx: int,
        n_batch: int,
        n_ubatch: int,
        n_seq_max: int,
        load_mode: str,
        kv_type: str,
    ) -> Self:
        library = Library.open(directory)
        chosen = choose_gpu(library.devices())
        if chosen is None:
            raise ModelNotLoadable("llama.cpp finds no CUDA GPU")
        model_params = library.llama_model_default_params()
        # A NULL-terminated device list. One device, never a split: a second GPU would
        # otherwise receive part of the layers.
        targets = (c_void_p * 2)(chosen.handle, None)
        model_params.devices = targets
        model_params.split_mode = SPLIT_MODE_NONE
        model_params.n_gpu_layers = GPU_LAYERS
        model_params.load_mode = LOAD_MODES[load_mode]
        library.errors.clear()
        model = library.llama_model_load_from_file(str(gguf).encode(), model_params)
        if not model:
            raise load_failure(f"llama.cpp cannot load {gguf}", library.errors)
        params = library.llama_context_default_params()
        params.n_ctx = n_ctx
        params.n_batch = min(n_batch, n_ctx)
        params.n_ubatch = min(n_ubatch, params.n_batch)
        params.n_seq_max = n_seq_max
        # One buffer shared by all sequences: branching the prefix then shares its cells
        # instead of copying them, and the context is a budget rather than a per-branch slice.
        params.kv_unified = True
        # Sliding-window layers keep every position too. With the compact window cache a cell
        # held by several sequences is never recycled, and after a long prefix the branches
        # find no free cell (llama_decode returns 1). Costs memory, not correctness.
        params.swa_full = True
        # Logits are read at one position per sequence; the default reserves n_batch rows of
        # the whole vocabulary.
        params.n_outputs_max = n_seq_max
        params.type_k = params.type_v = KV_TYPES[kv_type]
        params.offload_kqv = True
        params.no_perf = True
        context = library.llama_init_from_model(model, params)
        if not context:
            library.llama_model_free(model)
            raise load_failure(
                f"llama.cpp cannot create a context of {n_ctx} tokens for {n_seq_max} sequences",
                library.errors,
            )
        return cls(library, model, context, chosen, int(library.llama_n_batch(context)))

    def close(self) -> None:
        if self.context:
            self.library.llama_sampler_free(self.sampler)
            self.library.llama_free(self.context)
            self.library.llama_model_free(self.model)
            self.context = self.model = self.vocab = self.memory = self.sampler = 0

    # --- text -----------------------------------------------------------------------------

    def tokenize(self, text: str) -> list[int]:
        raw = text.encode("utf-8")
        capacity = len(raw) + 8  # a token covers at least one byte
        buffer = (c_int32 * capacity)()
        # parse_special: control tokens written in the template text become their own ids.
        count = self.library.llama_tokenize(
            self.vocab, raw, len(raw), buffer, capacity, False, True
        )
        if count < 0:
            raise ValueError("llama_tokenize: buffer too small")
        return buffer[:count]

    def detokenize(self, tokens: Sequence[int]) -> str:
        """The text of `tokens`, without special tokens."""
        ids = (c_int32 * len(tokens))(*tokens)
        capacity = 16 * len(tokens) + 16
        buffer = ctypes.create_string_buffer(capacity)
        count = self.library.llama_detokenize(
            self.vocab, ids, len(tokens), buffer, capacity, False, False
        )
        if count < 0:  # the size it needs
            capacity = -count
            buffer = ctypes.create_string_buffer(capacity)
            count = self.library.llama_detokenize(
                self.vocab, ids, len(tokens), buffer, capacity, False, False
            )
        return buffer.raw[:count].decode("utf-8", errors="replace")

    def is_end(self, token: int) -> bool:
        """Whether `token` ends a generation: end of sentence, of turn, and the like."""
        return bool(self.library.llama_vocab_is_eog(self.vocab, token))

    def meta(self, key: str) -> str | None:
        buffer = ctypes.create_string_buffer(1024)
        count = self.library.llama_model_meta_val_str(self.model, key.encode(), buffer, 1024)
        return buffer.value.decode("utf-8") if count >= 0 else None

    def description(self) -> str:
        """The model type as llama.cpp names it: "spark2_5 4B Q4_K - Medium"."""
        buffer = ctypes.create_string_buffer(256)
        self.library.llama_model_desc(self.model, buffer, 256)
        return buffer.value.decode("utf-8")

    def chat_template(self) -> str | None:
        template = self.library.llama_model_chat_template(self.model, None)
        return template.decode("utf-8") if template else None

    # --- compute --------------------------------------------------------------------------

    def decode(
        self,
        tokens: Sequence[int],
        positions: Sequence[int],
        sequences: Sequence[int],
        outputs: Iterable[int] = (),
    ) -> None:
        """One forward pass over a flat batch; logits are produced only at `outputs` indices."""
        count = len(tokens)
        if not 0 < count <= self.n_batch:
            raise ValueError(f"Batch of {count} tokens; the limit is {self.n_batch}")
        ids = (c_int32 * count)(*sequences)
        width = ctypes.sizeof(c_int32)
        base = ctypes.addressof(ids)
        flags = (c_int8 * count)()
        for index in outputs:
            flags[index] = 1
        batch = Batch(
            count,
            (c_int32 * count)(*tokens),
            None,
            (c_int32 * count)(*positions),
            (c_int32 * count)(*([1] * count)),
            (POINTER(c_int32) * count)(
                *(ctypes.cast(base + width * i, POINTER(c_int32)) for i in range(count))
            ),
            flags,
        )
        status = self.library.llama_decode(self.context, batch)
        if status != 0:
            raise RuntimeError(f"llama_decode returned {status}")

    def logits(self, index: int, slots: list[int]) -> list[float]:
        """Logits of the given vocabulary rows at batch position `index`."""
        row = self.library.llama_get_logits_ith(self.context, index)
        if not row:
            raise ValueError(f"No logits were produced at batch position {index}")
        return [float(row[slot]) for slot in slots]

    def sample(self, index: int) -> int:
        """The most likely next token at batch position `index`: greedy, temperature 0."""
        return int(self.library.llama_sampler_sample(self.sampler, self.context, index))

    def clear(self) -> None:
        self.library.llama_memory_clear(self.memory, True)

    def branch(self, source: int, target: int) -> None:
        self.library.llama_memory_seq_cp(self.memory, source, target, -1, -1)

    def drop(self, sequence: int) -> None:
        self.library.llama_memory_seq_rm(self.memory, sequence, -1, -1)

    def synchronize(self) -> None:
        self.library.llama_synchronize(self.context)

    def free_bytes(self) -> int:
        return self.library.free_bytes(self.device)
