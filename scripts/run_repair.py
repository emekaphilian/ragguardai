import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

print("Use scripts/run_pipeline.py for the end-to-end detect → diagnose → repair → validate demo.")
