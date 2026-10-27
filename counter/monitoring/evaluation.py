"""Model evaluation for the quality gate on promotion (X5).

A version is scored on a labelled image set: for each image, the classes it detects at
EVALUATION_THRESHOLD are compared with the classes labelled as visible. Precision, recall and F1
are computed per class and micro-averaged over all (image, class) pairs. Image-level labels need
no boxes; box-level mAP (pycocotools) would need box annotations.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from counter.adapters.model_manifest import REPO_ROOT

EVALUATION_THRESHOLD = 0.5
DEFAULT_EVALUATION_SET = REPO_ROOT / "models" / "evaluation" / "coco_sample.json"
# How much worse than the champion (in micro F1) a candidate may be and still be promoted.
DEFAULT_TOLERANCE = 0.02


@dataclass(frozen=True)
class EvaluationSet:
    name: str
    images_dir: Path
    labels: dict[str, frozenset[str]]
    fingerprint: str  # changes when the labels or any image change

    @property
    def images(self) -> list[Path]:
        return [self.images_dir / name for name in sorted(self.labels)]


@dataclass
class ClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int  # images where the class is labelled


@dataclass
class Evaluation:
    dataset: str
    fingerprint: str
    images: int
    precision: float
    recall: float
    f1: float
    per_class: dict[str, ClassMetrics] = field(default_factory=dict)


def load_evaluation_set(path: Path = DEFAULT_EVALUATION_SET) -> EvaluationSet:
    data = json.loads(Path(path).read_text())
    images_dir = (Path(path).parent / data["images_dir"]).resolve()
    labels = {name: frozenset(classes) for name, classes in data["labels"].items()}
    missing = [name for name in labels if not (images_dir / name).exists()]
    if missing:
        raise ValueError(f"{path}: images not found in {images_dir}: {missing}")
    digest = hashlib.sha256(Path(path).read_bytes())
    for name in sorted(labels):
        digest.update((images_dir / name).read_bytes())
    return EvaluationSet(data["name"], images_dir, labels, digest.hexdigest()[:12])


def evaluate(evaluation_set: EvaluationSet, detected: dict[str, set[str]]) -> Evaluation:
    """detected: image name -> classes detected at EVALUATION_THRESHOLD."""
    classes = sorted(set().union(*evaluation_set.labels.values(), *detected.values()))
    totals = {"tp": 0, "fp": 0, "fn": 0}
    per_class = {}
    for class_name in classes:
        tp = fp = fn = 0
        for image, expected in evaluation_set.labels.items():
            found = class_name in detected.get(image, set())
            labelled = class_name in expected
            tp += found and labelled
            fp += found and not labelled
            fn += labelled and not found
        precision, recall, f1 = _scores(tp, fp, fn)
        support = sum(class_name in expected for expected in evaluation_set.labels.values())
        per_class[class_name] = ClassMetrics(precision, recall, f1, support)
        totals["tp"] += tp
        totals["fp"] += fp
        totals["fn"] += fn
    precision, recall, f1 = _scores(totals["tp"], totals["fp"], totals["fn"])
    return Evaluation(
        evaluation_set.name,
        evaluation_set.fingerprint,
        len(evaluation_set.labels),
        precision,
        recall,
        f1,
        per_class,
    )


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str


def gate(
    candidate_f1: float | None,
    candidate_fingerprint: str | None,
    champion_f1: float | None,
    champion_fingerprint: str | None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> GateDecision:
    """Whether a candidate may replace the champion. Both must be evaluated on the same set."""
    if candidate_f1 is None:
        return GateDecision(False, "the candidate has not been evaluated")
    if champion_f1 is None and champion_fingerprint is None:
        return GateDecision(True, f"no evaluated champion; candidate F1 {candidate_f1:.3f}")
    if champion_f1 is None or champion_fingerprint != candidate_fingerprint:
        return GateDecision(
            False, "the champion was not evaluated on the same evaluation set; evaluate it first"
        )
    if candidate_f1 < champion_f1 - tolerance:
        return GateDecision(
            False,
            f"candidate F1 {candidate_f1:.3f} is below the champion's {champion_f1:.3f} "
            f"(tolerance {tolerance})",
        )
    return GateDecision(
        True,
        f"candidate F1 {candidate_f1:.3f} vs champion {champion_f1:.3f} (tolerance {tolerance})",
    )


def model_card(
    model: str, version: str, description: str, source: str, evaluation: Evaluation
) -> str:
    """A short Markdown model card, stored with the version in the registry."""
    dataset = (
        f"`{evaluation.dataset}` ({evaluation.images} images, "
        f"fingerprint `{evaluation.fingerprint}`)"
    )
    rows = "\n".join(
        f"| {name} | {m.support} | {m.precision:.2f} | {m.recall:.2f} | {m.f1:.2f} |"
        for name, m in sorted(evaluation.per_class.items())
    )
    return f"""# Model card: {model} v{version}

{description or "No description in the manifest."}

- **Source:** {source or "unknown"}
- **Serving:** TensorFlow Serving (SavedModel)
- **Evaluation set:** {dataset}
- **Method:** image-level class presence at score >= {EVALUATION_THRESHOLD}

| Metric | Value |
|---|---|
| Precision | {evaluation.precision:.3f} |
| Recall | {evaluation.recall:.3f} |
| F1 | {evaluation.f1:.3f} |

| Class | Images labelled | Precision | Recall | F1 |
|---|---|---|---|---|
{rows}

**Limitations:** the evaluation set is small; image-level labels don't check box positions.
"""


def _scores(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)
