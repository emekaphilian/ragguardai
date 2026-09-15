def below_thresholds(metrics, thresholds):
    return {
        "context_precision": metrics.context_precision < thresholds.context_precision,
        "context_recall": metrics.context_recall < thresholds.context_recall,
        "faithfulness": metrics.faithfulness < thresholds.faithfulness,
        "answer_relevancy": metrics.answer_relevancy < thresholds.answer_relevancy,
    }
