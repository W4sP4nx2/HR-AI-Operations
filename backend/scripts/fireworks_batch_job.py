"""Submit and inspect Fireworks Batch jobs using only injected configuration."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from services.fireworks_batch import (
    BatchConfig,
    FireworksBatchClient,
    batch_status_view,
)


async def monitor_batch_job(
    client: FireworksBatchClient,
    *,
    job_id: str,
    interval: float,
    max_polls: int,
    store=None,
) -> dict:
    """Poll to a terminal state and persist normalized progress metadata."""
    from core.memory import memory

    target_store = store or memory
    for attempt in range(max_polls):
        provider_payload = await client.get_job(job_id)
        result = batch_status_view(provider_payload)
        output_dataset = str(provider_payload.get("outputDatasetId", "")).split("/")[-1] or None
        await target_store.upsert_batch_job(
            job_id=job_id,
            status=result["status"],
            provider_state=result["provider_state"],
            processed_requests=result["processed_requests"],
            total_requests=result["total_requests"],
            failed_requests=result["failed_requests"],
            output_dataset_id=output_dataset,
        )
        print(json.dumps({"job_id": job_id, **result}, sort_keys=True))
        if result["terminal"]:
            return result
        if attempt + 1 < max_polls:
            await asyncio.sleep(interval)
    raise TimeoutError("Batch job did not reach a terminal state within the polling budget")


async def _submit(args: argparse.Namespace) -> None:
    payload = args.jsonl.read_bytes()
    config = BatchConfig.from_env()
    async with FireworksBatchClient(config) as client:
        await client.create_dataset(args.input_dataset)
        await client.upload_jsonl(
            args.input_dataset,
            payload,
            filename=args.jsonl.name,
        )
        result = await client.create_job(
            job_id=args.job_id,
            model_id=args.model,
            input_dataset_id=args.input_dataset,
            output_dataset_id=args.output_dataset,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_k=args.top_k,
            top_p=args.top_p,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


async def _status(args: argparse.Namespace) -> None:
    config = BatchConfig.from_env()
    async with FireworksBatchClient(config) as client:
        result = await client.get_job(args.job_id)
    print(json.dumps(result, indent=2, sort_keys=True))


async def _watch(args: argparse.Namespace) -> None:
    config = BatchConfig.from_env()
    async with FireworksBatchClient(config) as client:
        try:
            await monitor_batch_job(
                client,
                job_id=args.job_id,
                interval=args.interval,
                max_polls=args.max_polls,
            )
        except TimeoutError as exc:
            raise SystemExit(str(exc)) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Fireworks Batch job operations")
    subcommands = parser.add_subparsers(dest="command", required=True)

    submit = subcommands.add_parser("submit")
    submit.add_argument("jsonl", type=Path)
    submit.add_argument("--job-id", required=True)
    submit.add_argument("--model", required=True)
    submit.add_argument("--input-dataset", required=True)
    submit.add_argument("--output-dataset", required=True)
    submit.add_argument("--max-tokens", type=int, default=800)
    submit.add_argument("--temperature", type=float, default=0.0)
    submit.add_argument("--top-k", type=int)
    submit.add_argument("--top-p", type=float)

    status = subcommands.add_parser("status")
    status.add_argument("--job-id", required=True)

    watch = subcommands.add_parser("watch")
    watch.add_argument("--job-id", required=True)
    watch.add_argument("--interval", type=float, default=10.0)
    watch.add_argument("--max-polls", type=int, default=60)

    args = parser.parse_args()
    commands = {"submit": _submit, "status": _status, "watch": _watch}
    if args.command == "watch" and (args.interval <= 0 or args.max_polls < 1):
        parser.error("watch interval and max-polls must be positive")
    asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    main()
