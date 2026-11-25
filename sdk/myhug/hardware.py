"""What a machine is, for the evaluations: the processor, the memory, the graphics cards and the system.

It is read from the machine that runs this, when you ask for it (`hardware=True` of `evaluate`): nothing is sent that
you did not ask for, and it is what you say, not something the platform can check."""

import os
import platform
import shutil
import subprocess
import time
from types import TracebackType
from typing import Any

MIB_IN_GB = 1024**3


def _cpu_name() -> str | None:
    try:
        with open("/proc/cpuinfo") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def _ram_gb() -> float | None:
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / MIB_IN_GB, 1)
    except (ValueError, OSError, AttributeError):
        return None


def _gpus() -> list[dict[str, Any]]:
    """The NVIDIA cards, from `nvidia-smi` when it is there (nothing is imported: no torch is needed)."""
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return []
    try:
        out = subprocess.run(  # noqa: S603 - a fixed command
            [smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        name, _, memory = line.partition(",")
        if name.strip():
            card: dict[str, Any] = {"name": name.strip()[:200]}
            if memory.strip().isdigit():
                card["memory_gb"] = round(int(memory) / 1024, 1)
            found.append(card)
    return found[:16]


def detect(runtime: str | None = None) -> dict[str, Any]:
    """The hardware of this machine, as `evaluate` sends it. `runtime` says what ran the model (`onnxruntime 1.20`)."""
    gpus = _gpus()
    described: dict[str, Any] = {
        "device": "gpu" if gpus else "cpu",
        "cpu": _cpu_name(),
        "cpu_cores": os.cpu_count(),
        "ram_gb": _ram_gb(),
        "gpus": gpus,
        "os": f"{platform.system()} {platform.release()}".strip(),
        "runtime": runtime or f"python {platform.python_version()}",
    }
    return {key: value for key, value in described.items() if value not in (None, "", [])}


class Stopwatch:
    """`with Stopwatch() as watch: predictions = [model(x) for x in items]`, then `watch.seconds`."""

    seconds: float = 0.0

    def __enter__(self) -> "Stopwatch":
        self._start = time.perf_counter()
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None
    ) -> None:
        self.seconds = time.perf_counter() - self._start
