"""Held-out score for discover: negative RMSE on t >= 25 (higher is better)."""
import json

from common import test_window_rmse

rmse, _ = test_window_rmse()
print(json.dumps({"score": -rmse}))
