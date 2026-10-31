"""One registry of tools, consumed by both the CLI and the MCP server.

Each loop step is one tool, and the same tool is a CLI command with identical
arguments, so a chat-driven project and a hand-driven one leave the same trail.
Schemas are JSON Schema, which is what MCP speaks and what the CLI parser reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import experiments, loop, support
from .contracts import ACTORS, DECISIONS, MODES, ROLES, TEST_KINDS
from .project import Project

STR = {"type": "string"}
STRS = {"type": "array", "items": STR}
NUM = {"type": "number"}
BOOL = {"type": "boolean"}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]
    handler: Callable[..., dict[str, Any]]
    needs_project: bool = True

    @property
    def input_schema(self) -> dict[str, Any]:
        props = dict(self.properties)
        if self.needs_project:
            props["project"] = {**STR, "description": "project root; defaults to the "
                                "current directory or the nearest one above it"}
        return {"type": "object", "properties": props, "required": self.required,
                "additionalProperties": False}

    def call(self, args: dict[str, Any]) -> dict[str, Any]:
        args = dict(args)
        if not self.needs_project:
            return self.handler(**args)
        project = Project.find(args.pop("project", None))
        return self.handler(project, **args)


SETS = {**STRS, "description": "stochadex --set overrides, e.g. main.partitions[name=w].seed=7"}

TOOLS: list[Tool] = [
    Tool("init",
         "Scaffold a new project repo and record the domain interview. Ask the user about "
         "their domain, what they already know and their level before calling this.",
         {"path": STR, "name": STR, "description": STR,
          "level": {"type": "string", "enum": ["novice", "practitioner", "expert"]},
          "user_knows": {**STRS, "description": "what the user already knows, so outputs "
                         "can skip it"},
          "terms": {"type": "object", "additionalProperties": STR,
                    "description": "partition name -> the user's term for it"},
          "git": BOOL},
         ["path", "name", "description", "level", "user_knows"],
         loop.init, needs_project=False),
    Tool("pose",
         "Write claim.yaml: the question, the claim to establish, its intended use and the "
         "conditions it must hold under. Everything later serves this claim.",
         {"question": STR, "claim": STR,
          "intended_use": {"type": "string", "enum": MODES},
          "conditions": STRS,
          "observables": {**STRS, "description": "partitions (or domain terms) the claim "
                          "is about"},
          "compress_tolerance": {**NUM, "description": "relative change in the claim metric "
                                 "that still counts as unchanged"},
          "metric_script": {**STR, "description": "analysis script printing {\"score\": x} "
                            "for the quantity the claim is about"}},
         ["question", "claim", "intended_use", "conditions", "observables"], loop.pose),
    Tool("conjecture",
         "Register the structure written in model/sim.yaml (via the stochadex-model skill): "
         "a role and one-line hypothesis per partition. Gate: stochadex --check, a twice-run "
         "harness, sidecar completeness, observables mapped, input licences.",
         {"partitions": {"type": "object", "additionalProperties": {
              "type": "object", "properties": {
                  "role": {"type": "string", "enum": ROLES}, "hypothesis": STR,
                  "observed": BOOL}}},
          "rationale": STR, "config": STR},
         ["partitions", "rationale"], loop.conjecture),
    Tool("confront",
         "Run an inference config against data and record parameter beliefs in the ledger. "
         "Gate: the posterior has converged; weak identifiability is flagged for judgment.",
         {"config": STR, "posterior_partitions": STRS, "output": STR, "sets": SETS,
          "prior_sd": {"type": "object", "additionalProperties": {"type": "array",
                                                                   "items": NUM}},
          "indices": {"type": "object", "description": "partition -> state slots that hold "
                      "estimates; default all",
                      "additionalProperties": {"type": "array", "items": {"type": "integer"}}},
          "convergence_tolerance": NUM},
         ["config", "posterior_partitions"], loop.confront),
    Tool("test",
         "Try to break the claim: run every check in tests.yaml ("
         + ", ".join(TEST_KINDS) + ") on the current variant and set a verdict per partition.",
         {"only": {**STRS, "description": "check ids to run; default all"}},
         [], loop.test),
    Tool("discover",
         "Propose a structural variant where a test failed, and score it against its parent "
         "on held-out prediction. Learned (ONNX) structural partitions need recorded "
         "mechanistic failures and the user's logged approval.",
         {"id": STR, "rationale": STR, "score_script": STR, "partitions_changed": STRS,
          "config": STR, "sets": SETS, "parent": STR, "higher_is_better": BOOL,
          "partitions": {"type": "object", "description": "revised role/hypothesis for "
                         "partitions the variant changes or adds",
                         "additionalProperties": {"type": "object", "properties": {
                             "role": {"type": "string", "enum": ROLES}, "hypothesis": STR,
                             "observed": BOOL}}}},
         ["id", "rationale", "score_script", "partitions_changed"], loop.discover),
    Tool("compress",
         "Propose a smaller variant once the claim holds. Accepted only if the claim metric "
         "is unchanged within claim.yaml's tolerance and generalisation holds.",
         {"id": STR, "rationale": STR, "removed": STRS, "config": STR, "sets": SETS,
          "generalisation_script": STR},
         ["id", "rationale", "removed"], loop.compress),
    Tool("warrant",
         "Commit what is established for the current (minimal) variant, within stated "
         "limits, to the hash-chained ledger.",
         {"statement": STR, "limits": STRS},
         ["statement", "limits"], loop.warrant),
    Tool("query",
         "Explain, forecast, decide, automate, design or ask a counterfactual. Refuses when "
         "the warrant does not reach the mode's rung.",
         {"id": STR, "mode": {"type": "string", "enum": MODES}, "outcome": STR,
          "actions": STRS, "config": STR, "sets": SETS,
          "intervention_sets": {**SETS, "description": "the counterfactual arm's overrides; "
                                "seeds are shared so the arms are paired"}},
         ["id", "mode", "outcome"], loop.query),
    Tool("revise",
         "Commit drift monitors, a value-of-information ranking and new questions; these "
         "reopen the loop.",
         {"monitors": {"type": "array", "items": {"type": "object", "properties": {
              "name": STR, "partition": STR, "script": STR,
              "action": {"type": "string", "enum": ["recalibrate", "reopen", "rollback"]}}}},
          "value_of_information": {"type": "array", "items": {"type": "object", "properties": {
              "partition": STR, "value": NUM, "rationale": STR}}},
          "new_questions": STRS},
         ["monitors"], loop.revise),
    Tool("ask",
         "Open an experiment for a question, and get back what robert already knows that "
         "bears on it. Call it for every question the user asks, and for a suggested "
         "follow-up the user takes up (from_follow_up: E002.1).",
         {"question": STR, "asked_by": {"type": "string", "enum": experiments.ASKERS},
          "parent": {**STR, "description": "the experiment this question follows from"},
          "from_follow_up": {**STR, "description": "a suggested follow-up, e.g. E002.1"}},
         [], experiments.ask),
    Tool("answer",
         "Record the answer to an experiment: the answer in the user's terms; every "
         "assumption it rests on (owner, kind: implementation, operationalisation or "
         "belief, and sensitivity); the evidence behind every number; the strongest case "
         "against it; every analysis tried; a report on each standing question; and "
         "follow-ups, ranked by value, at least one naming the explanations it would "
         "tell apart.",
         {"experiment": STR, "answer": STR,
          "hypotheses": {**STRS, "description": "the competing explanations considered"},
          "assumptions": {"type": "array", "items": {"type": "object", "properties": {
              "assumption": STR, "owner": {"type": "string", "enum": experiments.OWNERS},
              "kind": {"type": "string", "enum": experiments.CHOICE_KINDS},
              "sensitivity": {"type": "string", "enum": experiments.SENSITIVITY},
              "why": STR}}},
          "evidence": {"type": "array", "items": {"type": "object", "properties": {
              "kind": {"type": "string", "enum": experiments.EVIDENCE_KINDS},
              "ref": {**STR, "description": "out/ path, ledger hash, test id, query id "
                      "or file path"},
              "shows": STR}}},
          "against": {"type": "array", "description": "the strongest evidence or argument "
                      "against the answer, or the result that would refute it",
                      "items": {"type": "object", "properties": {
                          "point": STR,
                          "kind": {"type": "string", "enum": experiments.EVIDENCE_KINDS},
                          "ref": STR}}},
          "tried": {"type": "array", "description": "every analysis tried, kept or not",
                    "items": {"type": "object", "properties": {
                        "analysis": STR, "outcome": STR, "ref": STR}}},
          "reports": {"type": "array", "description": "one per standing question; "
                      "\"nothing to report\" is a report",
                      "items": {"type": "object", "properties": {
                          "standing": STR, "report": STR}}},
          "follow_ups": {"type": "array", "items": {"type": "object", "properties": {
              "question": STR,
              "kind": {"type": "string", "enum": experiments.FOLLOW_UP_KINDS},
              "value": {"type": "string", "enum": experiments.VALUES},
              "discriminates": {**STRS, "description": "the explanations its result "
                                "would tell apart"},
              "why": STR}}},
          "supersedes": {**STR, "description": "an earlier experiment this answer replaces"}},
         ["experiment", "answer", "assumptions", "evidence", "against", "follow_ups"],
         experiments.answer),
    Tool("standing",
         "List the standing questions every answer must report on, add the user's own, "
         "or retire one. They are the channel for what nobody thought to ask about.",
         {"add": STRS, "retire": STRS}, [], experiments.standing),
    Tool("context",
         "What robert knows so far, compressed: answered questions with their live "
         "assumptions, open questions, and follow-ups not yet taken up. With focus, the "
         "chain that experiment follows from in full.",
         {"focus": STR}, [], experiments.context),
    Tool("run", "Run the current variant (or a config) with provenance; skips unchanged runs.",
         {"config": STR, "sets": SETS, "force": BOOL}, [], support.run),
    Tool("graph",
         "Render the partition graph from stochadex's own derivation, with one overlay: "
         "roles, tests, lineage, warrant or query.",
         {"overlay": {"type": "string", "enum": ["roles", "tests", "lineage", "warrant",
                                                 "query"]},
          "query": STR, "fmt": {"type": "string", "enum": ["mermaid", "dot"]}},
         [], support.graph),
    Tool("plot",
         "Chart partitions from a stochadex output. Must name the claim.yaml field it bears on.",
         {"output": STR, "partitions": STRS, "claim_part": STR, "title": STR},
         ["output", "partitions", "claim_part"], support.plot),
    Tool("status", "Where the loop stands: next step, gates, partition verdicts, counts.",
         {}, [], support.status),
    Tool("explain",
         "Compress an artefact to the user's domain terms: claim, partitions, tests, "
         "lineage, beliefs or warrants.",
         {"artefact": {"type": "string", "enum": ["claim", "partitions", "tests", "lineage",
                                                  "beliefs", "warrants"]}},
         ["artefact"], support.explain),
    Tool("intervene",
         "Log a redirection: what the agent proposed, what the user (or stand-in) decided, "
         "and why. Call it every time the agent is redirected.",
         {"step": STR, "actor": {"type": "string", "enum": ACTORS}, "agent_proposal": STR,
          "decision": {"type": "string", "enum": DECISIONS}, "reason": STR},
         ["step", "actor", "agent_proposal", "decision", "reason"], support.intervene),
]

BY_NAME = {t.name: t for t in TOOLS}


def _doctor(project: str | None = None) -> dict[str, Any]:
    try:
        p = Project.find(project)
    except Exception:
        p = None
    return support.doctor(p)


BY_NAME["doctor"] = Tool("doctor", "Check the stochadex toolchain and version pin.",
                         {"project": STR}, [], _doctor, needs_project=False)
TOOLS.append(BY_NAME["doctor"])
