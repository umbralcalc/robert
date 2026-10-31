#!/usr/bin/env bash
# The whole loop, end to end, as the commands an agent would call through chat.
# Usage: examples/logistic-growth/walkthrough.sh <empty target dir>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:?give a target directory}"

robert init --path "$TARGET" --name "Logistic growth" --no-git \
  --description "A single population observed yearly for 40 years" \
  --level practitioner \
  --user-knows "populations saturate" --user-knows "per-capita growth" \
  --terms '{"population": "Population (thousands)", "season": "Seasonal forcing"}'
cp -R "$HERE"/data "$HERE"/model "$HERE"/analysis "$HERE"/tests.yaml "$TARGET"/
cd "$TARGET"

# The user's question opens an experiment; the loop below earns its answer.
robert ask --question "How large will the population be over the next 15 years?"

robert pose \
  --question "How large will the population be over the next 15 years?" \
  --claim "The population forecast for years 25-39 is within 15% of what is observed" \
  --intended-use forecast \
  --conditions "no change in habitat" --conditions "yearly census method unchanged" \
  --observables population \
  --metric-script analysis/claim_metric.py

# The agent wrote model/sim.yaml (unconstrained growth) with the stochadex-model skill.
robert conjecture --rationale "simplest mechanism: unconstrained growth" --partitions '{
  "population": {"role": "structural", "hypothesis": "grows at a constant per-capita rate", "observed": true},
  "season": {"role": "nuisance", "hypothesis": "a weak yearly cycle modulates growth"}}'

robert confront --config model/confront.yaml --posterior-partitions ols \
  --indices '{"ols": [6, 7]}'

# Expected to fail: unconstrained growth overshoots the held-out years.
robert test || true
robert intervene --step test --actor user \
  --agent-proposal "raise the noise until the backtest passes" --decision redirect \
  --reason "the confront slope is negative: growth is density dependent, so add a capacity"

robert discover --id v1 --config model/variants/logistic.yaml \
  --rationale "the data's per-capita growth falls with population: add a carrying capacity" \
  --score-script analysis/holdout_score.py --partitions-changed population \
  --partitions '{"population": {"role": "structural", "observed": true,
    "hypothesis": "per-capita growth falls linearly with population to zero at capacity"}}'
robert test

robert compress --id v2 --config model/variants/logistic_compressed.yaml \
  --rationale "the seasonal forcing is too weak to move the forecast" --removed season
robert test

robert warrant \
  --statement "Logistic growth with r = 0.3 and capacity 100 forecasts years 25-39 within 15%" \
  --limits "habitat unchanged" --limits "horizon up to 15 years" --limits "no harvesting"

robert query --id fc-1 --mode forecast --outcome population
# Refused: a decision is an intervention rung, and nothing tested the action path.
robert query --id dec-1 --mode decide --outcome population --actions population || true

robert revise --monitors '[{"name": "census-drift", "partition": "population",
  "script": "analysis/drift_monitor.py", "action": "recalibrate"}]' \
  --value-of-information '[{"partition": "population", "value": 1.0,
  "rationale": "capacity is the least identified parameter"}]'

# The answer, with its assumptions (robert's own build choices included) and the
# evidence behind its numbers, and follow-ups the user can take up.
robert answer --experiment E001 \
  --answer "Logistic growth to a capacity near 100 thousand; years 25-39 are forecast within 15%" \
  --hypotheses "growth is unconstrained" --hypotheses "growth saturates at a carrying capacity" \
  --assumptions '[{"assumption": "habitat unchanged over the horizon", "owner": "user", "kind": "belief", "sensitivity": "untested"},
    {"assumption": "per-capita growth falls linearly with population", "owner": "robert", "kind": "implementation", "sensitivity": "untested", "why": "simplest density dependence that fits"},
    {"assumption": "forecast within 15% means relative RMSE under 0.15 on years 25-39", "owner": "robert", "kind": "operationalisation", "why": "the backtest window the claim names"},
    {"assumption": "the seasonal cycle can be ignored", "owner": "robert", "kind": "implementation", "sensitivity": "insensitive", "why": "compress showed it does not move the forecast"}]' \
  --evidence '[{"kind": "test", "ref": "backtest-population"}, {"kind": "query", "ref": "fc-1"},
    {"kind": "output", "ref": "out/queries/fc-1/factual/model.log"}]' \
  --against '[{"point": "the capacity rests on 40 years of one population; a regime change after year 39 would break it"}]' \
  --tried '[{"analysis": "unconstrained growth (v0)", "outcome": "failed the backtest and the density-dependence check"},
    {"analysis": "logistic growth with the seasonal cycle (v1)", "outcome": "passed; the cycle was then removed by compress"}]' \
  --reports '[{"standing": "S1", "report": "nothing to report"},
    {"standing": "S2", "report": "the observed population overshoots capacity in years 37-38, more than the model allows"},
    {"standing": "S3", "report": "forecast skill is judged on years 25-39 only"},
    {"standing": "S4", "report": "nothing to report"}]' \
  --follow-ups '[{"question": "How sensitive is the forecast to the capacity estimate?", "kind": "test-assumption", "value": "high",
      "discriminates": ["capacity near 100 explains the plateau", "the plateau is a slowdown, not a ceiling"]},
    {"question": "What would harvesting 5 per year do to the population?", "kind": "deepen", "value": "medium"}]'
robert ask --from-follow-up E001.1
robert context

robert graph --overlay tests
robert graph --overlay lineage
robert plot --output out/queries/fc-1/factual/model.log --partitions population \
  --claim-part claim --title "Forecast population"
robert explain --artefact warrants
robert status
