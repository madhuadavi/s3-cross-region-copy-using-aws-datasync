#!/usr/bin/env python3
"""
Cross-Account Bucket Policy Setup for DataSync

Run this script while authenticated to the SOURCE AWS account (via SSO or
credentials).  It attaches a bucket policy that allows a DataSync IAM role
in the DESTINATION account to read from the source bucket.

After running this script, switch to the destination account and run
create_datasync_task.py as usual — no other changes needed.

Usage:
    # Single bucket
    python setup_cross_account_bucket_policy.py \\
        --source-bucket my-source-bucket \\
        --dest-account-id 123456789012

    # Multiple buckets via CSV (reuses the same tasks.csv format)
    python setup_cross_account_bucket_policy.py \\
        --csv-file tasks.csv \\
        --dest-account-id 123456789012

    # Provide the exact destination role ARN instead of account ID
    python setup_cross_account_bucket_policy.py \\
        --source-bucket my-source-bucket \\
        --dest-role-arn arn:aws:iam::123456789012:role/DataSyncS3Role-my-source-bucket-source

    # Dry run — show the policy without applying
    python setup_cross_account_bucket_policy.py \\
        --source-bucket my-source-bucket \\
        --dest-account-id 123456789012 \\
        --dry-run

    # Remove a previously applied cross-account statement
    python setup_cross_account_bucket_policy.py \\
        --source-bucket my-source-bucket \\
        --dest-account-id 123456789012 \\
        --remove
"""

import argparse
import csv
import json
import sys
from typing import Dict, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

BOTO3_CONFIG = Config(retries={"max_attempts": 10, "mode": "standard"})

# Must stay in sync with create_datasync_task.py
MAX_IAM_ROLE_NAME_LENGTH = 64
STATEMENT_SID_PREFIX = "DataSyncCrossAccount"


def _truncate_name(name: str, max_length: int) -> str:
    """Truncate a name to fit within max_length, stripping trailing hyphens."""
    if len(name) <= max_length:
        return name
    return name[:max_length].rstrip("-")


def _expected_role_name(bucket_name: str) -> str:
    """Return the role name that create_datasync_task.py would generate."""
    return _truncate_name(
        f"DataSyncS3Role-{bucket_name}-source", MAX_IAM_ROLE_NAME_LENGTH
    )


def _statement_sid(dest_account_id: str) -> str:
    """Deterministic SID so we can find / replace / remove our statement."""
    return f"{STATEMENT_SID_PREFIX}-{dest_account_id}"


def _build_cross_account_statements(
    bucket_name: str, principal_arn: str, dest_account_id: str
) -> List[Dict]:
    """Build the two policy statements (bucket-level + object-level)."""
    sid = _statement_sid(dest_account_id)
    return [
        {
            "Sid": f"{sid}-Bucket",
            "Effect": "Allow",
            "Principal": {"AWS": principal_arn},
            "Action": [
                "s3:GetBucketLocation",
                "s3:ListBucket",
                "s3:ListBucketMultipartUploads",
            ],
            "Resource": f"arn:aws:s3:::{bucket_name}",
        },
        {
            "Sid": f"{sid}-Objects",
            "Effect": "Allow",
            "Principal": {"AWS": principal_arn},
            "Action": [
                "s3:GetObject",
                "s3:GetObjectTagging",
                "s3:ListMultipartUploadParts",
            ],
            "Resource": f"arn:aws:s3:::{bucket_name}/*",
        },
    ]


def _get_existing_policy(s3_client: "boto3.client", bucket_name: str) -> Dict:
    """Return the current bucket policy as a dict, or an empty policy."""
    try:
        response = s3_client.get_bucket_policy(Bucket=bucket_name)
        return json.loads(response["Policy"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchBucketPolicy":
            return {"Version": "2012-10-17", "Statement": []}
        raise


def _remove_our_statements(policy: Dict, dest_account_id: str) -> Dict:
    """Remove any statements we previously added for this dest account."""
    sid_prefix = _statement_sid(dest_account_id)
    policy["Statement"] = [
        s
        for s in policy.get("Statement", [])
        if not s.get("Sid", "").startswith(sid_prefix)
    ]
    return policy


def apply_bucket_policy(
    bucket_name: str,
    source_region: str,
    dest_account_id: str,
    dest_role_arn: Optional[str] = None,
    dry_run: bool = False,
    remove: bool = False,
) -> bool:
    """Apply or remove the cross-account DataSync policy on a source bucket.

    Returns True on success, False on failure.
    """
    s3_client = boto3.client("s3", region_name=source_region, config=BOTO3_CONFIG)

    # Verify bucket exists and we have access
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "404":
            print(f"✗ Bucket not found: {bucket_name}", file=sys.stderr)
        elif code == "403":
            print(
                f"✗ Access denied to bucket: {bucket_name}. "
                "Are you authenticated to the source account?",
                file=sys.stderr,
            )
        else:
            print(f"✗ Error accessing bucket {bucket_name}: {e}", file=sys.stderr)
        return False

    # Resolve the principal ARN
    if dest_role_arn:
        principal_arn = dest_role_arn
    else:
        role_name = _expected_role_name(bucket_name)
        principal_arn = f"arn:aws:iam::{dest_account_id}:role/{role_name}"

    # Get current policy
    policy = _get_existing_policy(s3_client, bucket_name)

    # Always strip old statements for this dest account first (idempotent)
    policy = _remove_our_statements(policy, dest_account_id)

    if remove:
        action_label = "Removing"
    else:
        action_label = "Applying"
        new_statements = _build_cross_account_statements(
            bucket_name, principal_arn, dest_account_id
        )
        policy["Statement"].extend(new_statements)

    print(f"\n{'='*60}")
    print(f"{action_label} cross-account policy on: {bucket_name}")
    print(f"  Principal: {principal_arn}")
    print(f"{'='*60}")

    # If removing and no statements left, delete the policy entirely
    if remove and not policy["Statement"]:
        if dry_run:
            print("[DRY RUN] Would delete bucket policy (no statements remain)")
            return True
        try:
            s3_client.delete_bucket_policy(Bucket=bucket_name)
            print("✓ Deleted bucket policy (no statements remain)")
            return True
        except ClientError as e:
            print(f"✗ Failed to delete bucket policy: {e}", file=sys.stderr)
            return False

    policy_json = json.dumps(policy, indent=2)

    if dry_run:
        print(f"\n[DRY RUN] Would apply policy:\n{policy_json}")
        return True

    try:
        s3_client.put_bucket_policy(Bucket=bucket_name, Policy=policy_json)
        print(f"✓ Bucket policy updated successfully")
        return True
    except ClientError as e:
        print(f"✗ Failed to apply bucket policy: {e}", file=sys.stderr)
        return False


def load_buckets_from_csv(csv_file: str) -> List[Tuple[str, str]]:
    """Extract unique (source_bucket, source_region) pairs from a tasks CSV."""
    buckets = []
    seen = set()
    with open(csv_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row["source_bucket"].strip()
            region = row.get("source_region", "").strip() or "me-central-1"
            if key not in seen:
                seen.add(key)
                buckets.append((key, region))
    return buckets


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set up cross-account S3 bucket policy for DataSync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--source-bucket",
        help="Source S3 bucket name (use with single-bucket mode)",
    )
    parser.add_argument(
        "--source-region",
        default="me-central-1",
        help="Source bucket region (default: me-central-1)",
    )
    parser.add_argument(
        "--csv-file",
        help="CSV file with task configs — extracts unique source buckets",
    )
    parser.add_argument(
        "--dest-account-id",
        help="Destination AWS account ID (12 digits)",
    )
    parser.add_argument(
        "--dest-role-arn",
        help="Exact IAM role ARN in dest account (overrides --dest-account-id for principal)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the policy that would be applied without making changes",
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove the cross-account statements instead of adding them",
    )

    args = parser.parse_args()

    # --- Validation -----------------------------------------------------------
    if not args.source_bucket and not args.csv_file:
        parser.error("Provide --source-bucket or --csv-file")

    if not args.dest_account_id and not args.dest_role_arn:
        parser.error("Provide --dest-account-id or --dest-role-arn")

    # Derive account ID from role ARN if needed
    dest_account_id = args.dest_account_id
    if args.dest_role_arn and not dest_account_id:
        # arn:aws:iam::ACCOUNT_ID:role/RoleName
        try:
            dest_account_id = args.dest_role_arn.split(":")[4]
        except (IndexError, ValueError):
            parser.error("Could not extract account ID from --dest-role-arn")

    if not dest_account_id or len(dest_account_id) != 12 or not dest_account_id.isdigit():
        parser.error("Destination account ID must be exactly 12 digits")

    # --- Confirm current identity ---------------------------------------------
    sts = boto3.client("sts", config=BOTO3_CONFIG)
    try:
        identity = sts.get_caller_identity()
        current_account = identity["Account"]
        print(f"Authenticated as: {identity['Arn']}")
        print(f"Current account:  {current_account}")

        if current_account == dest_account_id:
            print(
                "\n⚠  WARNING: You appear to be logged into the DESTINATION account.\n"
                "   This script should be run from the SOURCE account.\n"
                "   If this is intentional (same-account setup), proceed with caution.\n"
            )
    except ClientError as e:
        print(f"✗ Could not verify identity: {e}", file=sys.stderr)
        return 1

    # --- Build bucket list ----------------------------------------------------
    if args.csv_file:
        try:
            buckets = load_buckets_from_csv(args.csv_file)
            print(f"\nLoaded {len(buckets)} unique source bucket(s) from {args.csv_file}")
        except Exception as e:
            print(f"✗ Failed to read CSV: {e}", file=sys.stderr)
            return 1
    else:
        buckets = [(args.source_bucket, args.source_region)]

    # --- Apply / remove policies ----------------------------------------------
    success_count = 0
    fail_count = 0

    for bucket_name, region in buckets:
        ok = apply_bucket_policy(
            bucket_name=bucket_name,
            source_region=region,
            dest_account_id=dest_account_id,
            dest_role_arn=args.dest_role_arn,
            dry_run=args.dry_run,
            remove=args.remove,
        )
        if ok:
            success_count += 1
        else:
            fail_count += 1

    # --- Summary --------------------------------------------------------------
    print(f"\n{'='*60}")
    action = "Removed" if args.remove else "Applied"
    if args.dry_run:
        action = f"[DRY RUN] Would have {'removed' if args.remove else 'applied'}"
    print(f"{action} policies: {success_count} succeeded, {fail_count} failed")
    print(f"{'='*60}")

    if not args.remove and not args.dry_run and success_count > 0:
        print(
            "\nNext step: switch to the destination account and run "
            "create_datasync_task.py.\n"
            "The DataSync role in the destination account will now have "
            "cross-account access to the source bucket(s)."
        )

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
