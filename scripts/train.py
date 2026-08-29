"""Train SVM, kNN, and RiskClassifier; evaluate on eval set; write report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure src/ is on the path when running directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from triagegate.classifier.svm import SvmClassifier
from triagegate.classifier.knn import KnnClassifier
from triagegate.classifier.risk import RiskClassifier

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TRAIN_CSV = DATA_DIR / "tickets.csv"
EVAL_CSV = DATA_DIR / "eval_tickets.csv"
HISTORY_CSV = DATA_DIR / "incident_history.csv"
REPORT_JSON = DATA_DIR / "eval_report.json"
SVM_MODEL = DATA_DIR / "svm_model.joblib"
RISK_MODEL = DATA_DIR / "risk_model.joblib"


def accuracy(classifier, df: pd.DataFrame) -> float:
    correct = 0
    for _, row in df.iterrows():
        pred = classifier.predict(row["title"], row["description"])
        if pred == row["domain"]:
            correct += 1
    return correct / len(df)


def risk_accuracy(classifier: RiskClassifier, eval_df: pd.DataFrame, history_df: pd.DataFrame) -> float:
    """Accuracy of the RiskClassifier on the eval set joined to history labels."""
    merged = history_df.merge(eval_df[["id", "title", "description"]], on="id", how="inner")
    if len(merged) == 0:
        return 0.0
    correct = 0
    for _, row in merged.iterrows():
        pred = classifier.predict(row["title"], row["description"])
        if pred == row["risk_level"]:
            correct += 1
    return correct / len(merged)


def main() -> None:
    print(f"Training on {TRAIN_CSV} ...")

    svm = SvmClassifier()
    svm.fit(TRAIN_CSV)
    svm.save(SVM_MODEL)
    print(f"SVM model saved to {SVM_MODEL}")

    knn = KnnClassifier()
    knn.fit(TRAIN_CSV)

    print(f"Training RiskClassifier on {HISTORY_CSV} (joined to {TRAIN_CSV} + {EVAL_CSV}) ...")
    risk = RiskClassifier()
    risk.fit(TRAIN_CSV, HISTORY_CSV, extra_tickets_csv=EVAL_CSV)
    risk.save(RISK_MODEL)
    print(f"Risk model saved to {RISK_MODEL}")

    print(f"Evaluating on {EVAL_CSV} ...")
    eval_df = pd.read_csv(EVAL_CSV)
    history_df = pd.read_csv(HISTORY_CSV)

    svm_acc = accuracy(svm, eval_df)
    knn_acc = accuracy(knn, eval_df)
    risk_acc = risk_accuracy(risk, eval_df, history_df)

    print(f"SVM accuracy:  {svm_acc:.4f}")
    print(f"kNN accuracy:  {knn_acc:.4f}")
    print(f"Risk accuracy: {risk_acc:.4f}")

    report = {
        "svm_accuracy": round(svm_acc, 4),
        "knn_accuracy": round(knn_acc, 4),
        "risk_accuracy": round(risk_acc, 4),
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    print(f"Report written to {REPORT_JSON}")


if __name__ == "__main__":
    main()
