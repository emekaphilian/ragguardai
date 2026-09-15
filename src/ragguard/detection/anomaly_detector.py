class MetricAnomalyDetector:
    def __init__(self, minimum_score=0.70):
        self.minimum_score = minimum_score

    def is_anomalous(self, score):
        return score < self.minimum_score
