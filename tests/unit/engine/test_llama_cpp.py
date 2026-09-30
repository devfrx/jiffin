from jiffin.engine.errors import GpuOutOfMemory, ModelNotLoadable
from jiffin.engine.llama_cpp import DEVICE_TYPE_GPU, Device, choose_gpu, load_failure

CPU = Device(1, "Intel Core i7", 0, 16 << 30)
LAPTOP = Device(2, "NVIDIA GeForce RTX 4060 Laptop GPU", DEVICE_TYPE_GPU, 8 << 30)
DESKTOP = Device(3, "NVIDIA GeForce RTX 5060 Ti", DEVICE_TYPE_GPU, 16 << 30)


def test_the_model_runs_on_the_gpu_with_the_most_memory() -> None:
    assert choose_gpu([CPU, LAPTOP, DESKTOP]) == DESKTOP
    assert choose_gpu([CPU]) is None


def test_a_failed_load_is_out_of_memory_only_when_llama_cpp_says_so() -> None:
    oom = (
        "ggml_backend_cuda_buffer_type_alloc_buffer: allocating 2480.00 MiB on device 0: "
        "cudaMalloc failed: out of memory\n"
    )
    failure = load_failure("llama.cpp cannot load rizzo.gguf", ["something else\n", oom])
    assert isinstance(failure, GpuOutOfMemory)
    assert str(failure) == "llama.cpp cannot load rizzo.gguf: the GPU is out of memory"
    failure = load_failure("llama.cpp cannot load rizzo.gguf", ["invalid magic\n"])
    assert type(failure) is ModelNotLoadable
