"""Execute the authorized 10-question, three-arm development pilot without retries."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request

from scripts import dify_local, prepare_pilot
from scripts.prepare_pages import private_output


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def answer_from_events(events: list[dict]) -> dict:
    finished = next((e["data"] for e in events if e.get("event") == "workflow_finished"), {})
    nodes = [e["data"] for e in events if e.get("event") == "node_finished"]
    llms = [n for n in nodes if n.get("node_type") == "llm"]
    if (finished.get("status") != "succeeded" or len(llms) != 1
            or any(n.get("status") != "succeeded" for n in nodes)
            or any(e.get("event") == "error" for e in events)):
        raise ValueError("Workflow did not finish successfully with exactly one LLM execution")
    answer = ""
    for event in events:
        if event.get("event") == "message":
            answer += event.get("answer", "")
        elif event.get("event") == "message_replace":
            answer = event.get("answer", "")
    if not answer.strip():
        raise ValueError("No completed answer text was received")
    finish_reason = (llms[0].get("outputs") or {}).get("finish_reason")
    if finish_reason in ("length", "max_tokens"):
        raise ValueError("Answer hit its output limit; stop without automatically rerunning")
    metadata = next((e.get("metadata", {}) for e in events if e.get("event") == "message_end"), {})
    return {"answer_text": answer, "score": None, "reviewer": None,
            "citations": metadata.get("retriever_resources", []), "usage": metadata.get("usage", {}),
            "workflow_run_id": finished.get("id"), "elapsed_time": finished.get("elapsed_time"),
            "finish_reason": finish_reason}


def execute_one(console: dify_local.Console, app_id: str, row: dict, output: Path) -> dict:
    """Write the attempt before sending; existing attempts are never charged again."""
    if output.exists():
        previous = dify_local.read_json(output)
        if previous.get("status") != "succeeded":
            raise ValueError("An incomplete/failed attempt already exists; no automatic retry")
        return previous["answer"]
    record = {"question_id": row["question_id"], "condition": row["condition"], "query": row["query"],
              "started_at": now(), "status": "started", "events": []}
    dify_local.save_private(output, record)
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream", "Origin": console.origin}
    for cookie in console.cookies:
        if cookie.name.endswith("csrf_token"):
            headers["X-CSRF-Token"] = cookie.value
    # A fresh conversation per item; reference points are never included.
    request = Request(console.origin + f"/console/api/apps/{app_id}/advanced-chat/workflows/draft/run",
                      data=json.dumps({"inputs": {}, "query": row["query"], "files": []}, ensure_ascii=False).encode("utf-8"),
                      headers=headers, method="POST")
    try:
        with console.opener.open(request, timeout=180) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if line.startswith("data:"):
                    text = line[5:].strip()
                    if text and text != "[DONE]":
                        record["events"].append(json.loads(text))
        answer = {"question_id": row["question_id"], "condition": row["condition"],
                  **answer_from_events(record["events"])}
        record.update(status="succeeded", answer=answer)
        return answer
    except Exception as error:
        record.update(status="failed_or_incomplete", error_type=type(error).__name__)
        raise
    finally:
        record["finished_at"] = now()
        dify_local.save_private(output, record)


def save_answers(bundle: Path, requests: list[dict]) -> list[dict]:
    answers = []
    for row in requests:
        path = bundle / "runs" / f"{row['question_id']}-{row['condition']}.json"
        record = dify_local.read_json(path)
        if record.get("status") == "succeeded":
            answers.append(record["answer"])
    (bundle / "answers.jsonl").write_text(
        "".join(json.dumps(a, ensure_ascii=False) + "\n" for a in answers), encoding="utf-8")
    return answers


def run(bundle: Path, authorized: bool = False, max_output_tokens: int = 2048) -> list[dict]:
    if not authorized:
        raise ValueError("Explicit paid-call and retrieved-source-transfer authorization is required")
    if max_output_tokens != 2048:
        raise ValueError("This authorized batch uses a uniform 2048-token output cap")
    bundle = private_output(bundle)
    config = dify_local.read_json(bundle / "config.json")
    questions = dify_local.read_json(bundle / "questions.json")
    requests = [json.loads(line) for line in (bundle / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = {(q["id"], g): q["question"] for q in questions["questions"] for g in prepare_pilot.CONDITIONS}
    if (config.get("split") != "development_only" or len(expected) != 30 or len(requests) != 30
            or {(r["question_id"], r["condition"]): r["query"] for r in requests} != expected):
        raise ValueError("Batch must contain exactly the existing 10 questions across three conditions")
    runs = bundle / "runs"
    if runs.exists() and any(runs.glob("*.json")) and config["model"]["completion_params"]["max_tokens"] != max_output_tokens:
        raise ValueError("Cannot mix output budgets after a batch has started")
    config["model"]["completion_params"]["max_tokens"] = max_output_tokens
    config.update(maximum_output_tokens=30 * max_output_tokens, chat_calls_authorized=True)
    config.setdefault("authorization", {"recorded_at": now(), "basis": "explicit_user_chat_confirmation",
                                        "scope": "30 pilot generations and their retrieved source snippets; no publication",
                                        "max_calls": 30, "max_output_tokens_per_call": max_output_tokens})
    dify_local.save_private(bundle / "config.json", config)
    state = dify_local.read_json(bundle / "state.json")
    console = dify_local.Console(state["origin"])
    console.login(dify_local.read_json(dify_local.ROOT / "work/local/admin.json"))
    # Configure and read back every arm before starting the first paid request.
    for condition in prepare_pilot.CONDITIONS:
        group = state["groups"][condition]
        path = f"/console/api/apps/{group['app_id']}/workflows/draft"
        current = console.request("GET", path)
        payload = prepare_pilot.workflow(condition, group.get("dataset_id"), config)
        if current.get("hash"):
            payload["hash"] = current["hash"]
        console.request("POST", path, payload)
        saved = console.request("GET", path)
        llm = next(n["data"] for n in saved["graph"]["nodes"] if n["data"]["type"] == "llm")
        target = next(n["data"] for n in payload["graph"]["nodes"] if n["data"]["type"] == "llm")
        for key in ("model", "prompt_template", "context", "retry_config"):
            if llm[key] != target[key]:
                raise ValueError(f"{condition}: saved draft differs from the batch configuration")
    runs.mkdir(exist_ok=True)
    try:
        for index, row in enumerate(requests, 1):
            path = runs / f"{row['question_id']}-{row['condition']}.json"
            answer = execute_one(console, state["groups"][row["condition"]]["app_id"], row, path)
            save_answers(bundle, requests)
            print(f"{index}/30 {row['question_id']} {row['condition']} succeeded; "
                  f"tokens={answer['usage'].get('total_tokens', 'unreported')}; "
                  f"finish_reason={answer.get('finish_reason')}", flush=True)
    finally:
        answers = save_answers(bundle, requests)
    ratings = bundle / "ratings.jsonl"
    if not ratings.exists():
        ratings.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in answers), encoding="utf-8")
    print(f"Completed {len(answers)}/30 actual answers; all scores remain null pending human review.")
    return answers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=dify_local.ROOT / "work/pilot-dev-v1")
    parser.add_argument("--authorize-paid-calls", action="store_true",
                        help="Use only with human authorization covering this batch and source transfer")
    args = parser.parse_args()
    run(args.bundle, authorized=args.authorize_paid_calls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
