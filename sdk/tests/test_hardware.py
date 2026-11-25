import subprocess
import time

import pytest

from myhug import Stopwatch, hardware


def test_this_machine_is_described_with_what_can_be_known_and_nothing_empty() -> None:
    described = hardware.detect()
    assert described["device"] in ("cpu", "gpu") and described["cpu_cores"] >= 1 and described["os"]
    assert described["runtime"].startswith("python ")
    assert all(value not in (None, "", []) for value in described.values())  # what is unknown is not said


def test_what_ran_the_model_can_be_said() -> None:
    assert hardware.detect("onnxruntime 1.20")["runtime"] == "onnxruntime 1.20"


def test_the_cards_come_from_nvidia_smi_when_it_is_there(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    answer = subprocess.CompletedProcess([], 0, stdout="NVIDIA A100, 40960\nNVIDIA T4, 15360\n\n")
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: answer)
    described = hardware.detect()
    assert described["device"] == "gpu"
    assert described["gpus"] == [{"name": "NVIDIA A100", "memory_gb": 40.0}, {"name": "NVIDIA T4", "memory_gb": 15.0}]


def test_a_card_that_cannot_be_read_is_no_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware.shutil, "which", lambda name: "/usr/bin/nvidia-smi")

    def broken(*args, **kwargs):
        raise subprocess.CalledProcessError(9, "nvidia-smi")

    monkeypatch.setattr(hardware.subprocess, "run", broken)
    assert hardware.detect()["device"] == "cpu" and "gpus" not in hardware.detect()


def test_at_most_sixteen_cards_are_said(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    answer = subprocess.CompletedProcess([], 0, stdout="GPU, 1024\n" * 40)
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: answer)
    assert len(hardware.detect()["gpus"]) == 16


def test_a_stopwatch_gives_the_time_of_the_block() -> None:
    with Stopwatch() as watch:
        time.sleep(0.05)
    assert 0.04 <= watch.seconds < 1
