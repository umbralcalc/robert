"""Backtest: forecast error on the held-out window (t >= 25), relative to its level."""
import json

from common import test_window_rmse

rmse, scale = test_window_rmse()
rel = rmse / scale
print(json.dumps({"passed": rel < 0.15, "metric": rel,
                  "detail": f"relative RMSE {rel:.3f} on t >= 25 (pass < 0.15)"}))
