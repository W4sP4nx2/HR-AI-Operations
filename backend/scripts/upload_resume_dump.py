"""Prepare or upload synthetic resume PDFs to S3-compatible object storage.

Default mode is a no-network dry run that writes an upload manifest. Add
``--upload`` to PUT each PDF to MinIO/S3 using AWS Signature V4 and standard
library HTTP.

Example local MinIO:

    python -m scripts.upload_resume_dump --endpoint http://localhost:9000
    python -m scripts.upload_resume_dump --endpoint http://localhost:9000 --upload
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from scripts.generate_hackathon_datasets import DEFAULT_OUT

DEFAULT_BUCKET = "hrcc-synthetic-resumes"


def build_upload_plan(
    manifest_path: Path,
    *,
    bucket: str = DEFAULT_BUCKET,
    prefix: str = "",
) -> list[dict[str, Any]]:
    """Return local file to object-key rows for the generated resume dump."""
    rows = _read_csv(manifest_path)
    plan = []
    normalized_prefix = prefix.strip("/")
    for row in rows:
        filename = row["filename"]
        key = f"{normalized_prefix}/{filename}" if normalized_prefix else filename
        local_path = Path(row["local_path"])
        size_bytes = local_path.stat().st_size
        plan.append(
            {
                "candidate_id": row["candidate_id"],
                "bucket": bucket,
                "key": key,
                "uri": f"s3://{bucket}/{key}",
                "local_path": str(local_path),
                "size_bytes": size_bytes,
                "sha256": _sha256_file(local_path),
            }
        )
    return plan


def upload_plan(
    plan: list[dict[str, Any]],
    *,
    endpoint: str,
    access_key: str,
    secret_key: str,
    region: str,
    create_bucket: bool,
) -> dict[str, Any]:
    """Upload every planned file to an S3-compatible endpoint."""
    if not plan:
        raise ValueError("upload plan is empty")
    if create_bucket:
        try:
            _s3_put(
                endpoint=endpoint,
                bucket=plan[0]["bucket"],
                key="",
                body=b"",
                access_key=access_key,
                secret_key=secret_key,
                region=region,
                content_type="application/octet-stream",
                bucket_create=True,
            )
        except HTTPError as exc:
            if exc.code != 409:
                raise
    uploaded = []
    for row in plan:
        path = Path(row["local_path"])
        _s3_put(
            endpoint=endpoint,
            bucket=row["bucket"],
            key=row["key"],
            body=path.read_bytes(),
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            content_type="application/pdf",
        )
        uploaded.append(row["uri"])
    listed = _s3_list_objects(
        endpoint=endpoint,
        bucket=plan[0]["bucket"],
        prefix=_common_prefix(plan),
        access_key=access_key,
        secret_key=secret_key,
        region=region,
    )
    expected_keys = {row["key"] for row in plan}
    actual_keys = set(listed["keys"])
    missing = sorted(expected_keys - actual_keys)
    unexpected = sorted(actual_keys - expected_keys)
    return {
        "uploaded": len(uploaded),
        "uris": uploaded[:5],
        "verification": {
            "ok": not missing,
            "expected_objects": len(expected_keys),
            "listed_objects": len(actual_keys),
            "missing_count": len(missing),
            "unexpected_count": len(unexpected),
            "total_bytes": listed["total_bytes"],
            "first_missing_keys": missing[:5],
            "first_unexpected_keys": unexpected[:5],
        },
    }


def _common_prefix(plan: list[dict[str, Any]]) -> str:
    """Return the configured object prefix shared by every planned key."""
    if not plan:
        return ""
    first = str(plan[0]["key"])
    return first.rsplit("/", 1)[0] + "/" if "/" in first else ""


def _s3_list_objects(
    *,
    endpoint: str,
    bucket: str,
    prefix: str,
    access_key: str,
    secret_key: str,
    region: str,
) -> dict[str, Any]:
    """List every object under a prefix with signed S3 ListObjectsV2 calls."""
    keys: list[str] = []
    total_bytes = 0
    continuation = ""
    while True:
        page = _s3_list_page(
            endpoint=endpoint,
            bucket=bucket,
            prefix=prefix,
            continuation=continuation,
            access_key=access_key,
            secret_key=secret_key,
            region=region,
        )
        keys.extend(item["key"] for item in page["objects"])
        total_bytes += sum(item["size"] for item in page["objects"])
        continuation = page["next_continuation_token"]
        if not page["is_truncated"]:
            break
        if not continuation:
            raise RuntimeError("S3 listing was truncated without a continuation token")
    return {"keys": keys, "total_bytes": total_bytes}


def _s3_list_page(
    *,
    endpoint: str,
    bucket: str,
    prefix: str,
    continuation: str,
    access_key: str,
    secret_key: str,
    region: str,
) -> dict[str, Any]:
    """Return one authenticated ListObjectsV2 response page."""
    parsed = urlparse(endpoint.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("endpoint must be an http(s) URL")
    path = f"/{bucket}"
    params = {"list-type": "2", "prefix": prefix}
    if continuation:
        params["continuation-token"] = continuation
    canonical_query = "&".join(
        f"{quote(key, safe='-_.~')}={quote(value, safe='-_.~')}"
        for key, value in sorted(params.items())
    )
    now = dt.datetime.now(dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(b"").hexdigest()
    headers = {
        "host": parsed.netloc,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
    canonical_request = "\n".join(
        ["GET", path, canonical_query, canonical_headers, signed_headers, payload_hash]
    )
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = hmac.new(
        _signature_key(secret_key, date_stamp, region, "s3"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    headers["authorization"] = (
        "AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    url = f"{parsed.scheme}://{parsed.netloc}{path}?{canonical_query}"
    with urlopen(Request(url, headers=headers, method="GET"), timeout=30) as response:
        root = ElementTree.fromstring(response.read())
    objects = [
        {
            "key": str(item.findtext("{*}Key", default="")),
            "size": int(item.findtext("{*}Size", default="0")),
        }
        for item in root.findall("{*}Contents")
    ]
    return {
        "objects": objects,
        "is_truncated": root.findtext("{*}IsTruncated", default="false").lower() == "true",
        "next_continuation_token": root.findtext("{*}NextContinuationToken", default=""),
    }


def _s3_put(
    *,
    endpoint: str,
    bucket: str,
    key: str,
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str,
    content_type: str,
    bucket_create: bool = False,
) -> None:
    parsed = urlparse(endpoint.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("endpoint must be an http(s) URL")
    encoded_key = "/".join(quote(part, safe="") for part in key.split("/") if part)
    path = f"/{bucket}" if bucket_create or not encoded_key else f"/{bucket}/{encoded_key}"
    url = f"{parsed.scheme}://{parsed.netloc}{path}"
    now = dt.datetime.now(dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()
    host = parsed.netloc
    headers = {
        "content-type": content_type,
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
    canonical_request = "\n".join(
        [
            "PUT",
            path,
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = _signature_key(secret_key, date_stamp, region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        "AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    req = Request(url, data=body, headers=headers, method="PUT")
    with urlopen(req, timeout=30) as response:  # noqa: S310 - explicit operator endpoint
        if response.status not in {200, 201}:
            raise RuntimeError(f"upload failed for {url}: HTTP {response.status}")


def _signature_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    key = ("AWS4" + secret_key).encode("utf-8")
    for msg in (date_stamp, region, service, "aws4_request"):
        key = hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    return key


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_OUT / "resume_pdf_dump" / "resume_manifest.csv",
    )
    parser.add_argument("--bucket", default=os.environ.get("S3_BUCKET", DEFAULT_BUCKET))
    parser.add_argument("--prefix", default=os.environ.get("S3_PREFIX", ""))
    parser.add_argument("--endpoint", default=os.environ.get("S3_ENDPOINT_URL", ""))
    parser.add_argument("--access-key", default=os.environ.get("AWS_ACCESS_KEY_ID", ""))
    parser.add_argument("--secret-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", ""))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--create-bucket", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    plan = build_upload_plan(args.manifest, bucket=args.bucket, prefix=args.prefix)
    if args.upload:
        missing = [
            name
            for name, value in {
                "S3_ENDPOINT_URL/--endpoint": args.endpoint,
                "AWS_ACCESS_KEY_ID/--access-key": args.access_key,
                "AWS_SECRET_ACCESS_KEY/--secret-key": args.secret_key,
            }.items()
            if not value
        ]
        if missing:
            raise SystemExit("missing upload configuration: " + ", ".join(missing))
        result = upload_plan(
            plan,
            endpoint=args.endpoint,
            access_key=args.access_key,
            secret_key=args.secret_key,
            region=args.region,
            create_bucket=args.create_bucket,
        )
    else:
        result = {
            "dry_run": True,
            "planned_uploads": len(plan),
            "bucket": args.bucket,
            "first_objects": plan[:5],
        }
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if args.upload and not result["verification"]["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
