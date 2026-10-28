"""Process check: per-capita growth must fall with population as it does in the data
(density dependence), not just match the aggregate curve."""
import json

from common import growth_table, model_trajectory, slope

sim = model_trajectory()
times = sorted(sim)
model_points = [(sim[a], (sim[b] - sim[a]) / sim[a]) for a, b in zip(times, times[1:])]
data_slope, model_slope = slope(growth_table()), slope(model_points)
ratio = model_slope / data_slope
print(json.dumps({"passed": 0.5 < ratio < 2.0, "metric": ratio,
                  "detail": f"density dependence: model slope {model_slope:.2e}, "
                            f"data slope {data_slope:.2e}"}))
