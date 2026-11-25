"""The metrics of each kind of task, in one place: what an evaluation computes, what a person who sends a result may
send, and what the screens and the SDK list (`GET /api/metrics`).

An evaluation holds **all** the metrics of its task; its author chooses which ones the others see."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    id: str
    name: str
    # Whether a higher value is better (an error is not).
    higher: bool = True
    # The main metric of the task: the one a comparison starts from.
    primary: bool = False


def _m(id: str, name: str, higher: bool = True, primary: bool = False) -> Metric:
    return Metric(id, name, higher, primary)


_CLASSIFICATION = (
    _m("accuracy", "Accuracy", primary=True),
    _m("precision", "Precision"),
    _m("recall", "Recall"),
    _m("f1", "F1"),
    _m("auc", "AUC"),
)
_SPANS = (
    _m("f1", "F1", primary=True),
    _m("precision", "Precision"),
    _m("recall", "Recall"),
    _m("exact_match", "Exact match"),
)
_TEMPORAL = (
    _m("f1", "F1", primary=True),
    _m("precision", "Precision"),
    _m("recall", "Recall"),
    _m("iou_temporal", "Temporal IoU"),
    _m("boundary_error", "Boundary error (s)", higher=False),
)
_CAPTION = (
    _m("bleu", "BLEU", primary=True),
    _m("rouge_l", "ROUGE-L"),
    _m("cider", "CIDEr"),
    _m("meteor", "METEOR"),
)
_DEFAULT = (_m("accuracy", "Accuracy", primary=True),)

METRICS: dict[str, tuple[Metric, ...]] = {
    "classification": _CLASSIFICATION,
    "image_classification": _CLASSIFICATION,
    "audio_classification": _CLASSIFICATION,
    "video_classification": _CLASSIFICATION,
    "timeseries_classification": _CLASSIFICATION,
    "row_label": _CLASSIFICATION,
    "ner": _SPANS,
    "qa": (_m("exact_match", "Exact match", primary=True), _m("f1", "F1")),
    "regression": (
        _m("mae", "MAE", higher=False, primary=True),
        _m("rmse", "RMSE", higher=False),
        _m("r2", "R²"),
        _m("mape", "MAPE (%)", higher=False),
    ),
    "cell_review": (_m("f1", "F1", primary=True), _m("precision", "Precision"), _m("recall", "Recall")),
    "column_schema": (_m("accuracy", "Accuracy", primary=True), _m("f1", "F1")),
    "image_detection": (
        _m("map50", "mAP@50", primary=True),
        _m("map50_95", "mAP@50:95"),
        _m("precision", "Precision"),
        _m("recall", "Recall"),
    ),
    "image_polyline": (
        _m("f1", "F1", primary=True),
        _m("precision", "Precision"),
        _m("recall", "Recall"),
        _m("chamfer", "Chamfer distance", higher=False),
    ),
    "image_segmentation": (
        _m("miou", "mIoU", primary=True),
        _m("dice", "Dice"),
        _m("pixel_accuracy", "Pixel accuracy"),
        _m("boundary_f1", "Boundary F1"),
    ),
    "image_keypoints": (
        _m("pck", "PCK", primary=True),
        _m("oks_ap", "AP (OKS)"),
        _m("mpjpe", "MPJPE (px)", higher=False),
    ),
    "image_caption": _CAPTION,
    "audio_caption": _CAPTION,
    "video_caption": _CAPTION,
    "timeseries_caption": _CAPTION,
    "image_vqa": (_m("vqa_accuracy", "VQA accuracy", primary=True), _m("exact_match", "Exact match"), _m("f1", "F1")),
    "audio_segments": _TEMPORAL,
    "video_segments": _TEMPORAL,
    "timeseries_segments": _TEMPORAL,
    "audio_transcription": (
        _m("wer", "WER", higher=False, primary=True),
        _m("cer", "CER", higher=False),
        _m("ser", "SER (sentences)", higher=False),
    ),
    "video_tracking": (
        _m("mota", "MOTA", primary=True),
        _m("idf1", "IDF1"),
        _m("hota", "HOTA"),
        _m("id_switches", "Identity switches", higher=False),
    ),
}


def metrics_for(task: str) -> tuple[Metric, ...]:
    """The metrics of a task (an unknown task has accuracy only)."""
    return METRICS.get(task, _DEFAULT)


def default_shown(task: str) -> list[str]:
    """What is shown to the others unless the author chooses: the main metric and the next one."""
    return [metric.id for metric in metrics_for(task)[:2]]
