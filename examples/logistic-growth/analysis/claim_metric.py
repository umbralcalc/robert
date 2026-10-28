"""The quantity the claim is about: forecast population at the end of the horizon."""
import json

from common import model_trajectory

sim = model_trajectory()
print(json.dumps({"score": sim[max(sim)]}))
