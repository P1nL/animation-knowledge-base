"""Run the explicitly authorized 90 final-v1 requests; preserve attempts, never retry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import dify_local as d, prepare_final, prepare_pilot, run_pilot
from scripts.prepare_pages import private_output


def run(bundle: Path, authorized: bool = False) -> list[dict]:
    if not authorized:
        raise ValueError("Explicit 90-call paid/source-transfer authorization is required")
    bundle = private_output(bundle)
    config, requests = prepare_final.validate_bundle(bundle)
    state = d.read_json(bundle / "state.json")
    groups = state["groups"]
    if (set(groups) != set(prepare_pilot.CONDITIONS)
            or len({g["app_id"] for g in groups.values()}) != 3
            or len({groups[g]["dataset_id"] for g in ("G1", "G2")}) != 2
            or any(groups[g].get("completed_documents") != config["source_counts"][g] for g in ("G1", "G2"))):
        raise ValueError("Final batch requires three independent apps and two completed source indices")
    # Reject an incomplete attempt before touching a draft or sending another paid call.
    for row in requests:
        attempt = d.read_json(bundle / "runs" / f"{row['question_id']}-{row['condition']}.json")
        if attempt and attempt.get("status") != "succeeded":
            raise ValueError("Incomplete/failed attempt exists; no automatic retry or continuation")
    config.update(chat_calls_authorized=True)
    config.setdefault("authorization", {"recorded_at": run_pilot.now(),
        "basis": "explicit_user_chat_annotation_execute",
        "scope": "90 final-v1 generations and required retrieved snippets; AI scoring; no publication",
        "max_calls": 90, "max_output_tokens_per_call": 2048, "automatic_retries": False})
    d.save_private(bundle / "config.json", config)
    console = d.Console(state["origin"])
    console.login(d.read_json(d.ROOT / "work/local/admin.json"))
    for condition in prepare_pilot.CONDITIONS:
        group = groups[condition]
        path = f"/console/api/apps/{group['app_id']}/workflows/draft"
        current = console.request("GET", path)
        target = prepare_pilot.workflow(condition, group.get("dataset_id"), config)
        if current.get("hash"):
            target["hash"] = current["hash"]
        console.request("POST", path, target)
        saved = console.request("GET", path)
        actual_nodes = {n["id"]: n["data"] for n in saved["graph"]["nodes"]}
        expected_nodes = {n["id"]: n["data"] for n in target["graph"]["nodes"]}
        if actual_nodes.keys() != expected_nodes.keys():
            raise ValueError("Unexpected workflow nodes; stop before paid calls")
        for key in ("model", "prompt_template", "context", "retry_config"):
            if actual_nodes["llm"][key] != expected_nodes["llm"][key]:
                raise ValueError(f"{condition}: saved LLM differs from frozen configuration")
        if condition != "G0":
            for key in ("dataset_ids", "query_variable_selector", "retrieval_mode", "multiple_retrieval_config"):
                if actual_nodes["knowledge"][key] != expected_nodes["knowledge"][key]:
                    raise ValueError(f"{condition}: saved retrieval configuration differs")
        d.save_private(bundle / "workflows" / f"{condition}.json", saved)
    (bundle / "runs").mkdir(exist_ok=True)
    try:
        for index, row in enumerate(requests, 1):
            path = bundle / "runs" / f"{row['question_id']}-{row['condition']}.json"
            answer = run_pilot.execute_one(console, groups[row["condition"]]["app_id"], row, path)
            run_pilot.save_answers(bundle, requests)
            print(f"{index}/90 {row['question_id']} {row['condition']} succeeded; "
                  f"tokens={answer['usage'].get('total_tokens', 'unreported')}; "
                  f"finish_reason={answer.get('finish_reason')}", flush=True)
    finally:
        answers = run_pilot.save_answers(bundle, requests)
    ratings = bundle / "ratings.jsonl"
    if not ratings.exists():
        ratings.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in answers), encoding="utf-8")
    print(f"Completed {len(answers)}/90 actual answers; scores remain null. AI assessment is a separate artifact.")
    return answers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=d.ROOT / "work/final-v1")
    parser.add_argument("--authorize-paid-calls", action="store_true")
    args = parser.parse_args()
    run(args.bundle, args.authorize_paid_calls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
