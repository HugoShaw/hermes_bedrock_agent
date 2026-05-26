#!/usr/bin/env python3
"""S3 access verification script — lists files in s3-hulftchina-rd bucket."""

import sys
import boto3
from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError

BUCKET_NAME = "s3-hulftchina-rd"


def check_iam_identity():
    print("[1/3] Checking IAM identity ...")
    sts = boto3.client("sts")
    try:
        identity = sts.get_caller_identity()
        print(f"  Account  : {identity['Account']}")
        print(f"  UserID   : {identity['UserId']}")
        print(f"  ARN      : {identity['Arn']}")
        return True
    except NoCredentialsError:
        print("  ERROR: No AWS credentials found.")
        print("  Hint: Set AWS_PROFILE, AWS_ACCESS_KEY_ID/SECRET, or attach an IAM role.")
        return False
    except ClientError as e:
        print(f"  ERROR: {e}")
        return False


def check_s3_list(bucket: str, max_keys: int = 20):
    print(f"\n[2/3] Listing objects in s3://{bucket}/ (max {max_keys}) ...")
    s3 = boto3.client("s3")
    try:
        resp = s3.list_objects_v2(Bucket=bucket, MaxKeys=max_keys)
        contents = resp.get("Contents", [])
        if not contents:
            print("  Bucket is empty or no objects visible.")
        else:
            for obj in contents:
                size_kb = obj["Size"] / 1024
                print(f"  {obj['Key']:60s}  {size_kb:8.1f} KB  {obj['LastModified'].strftime('%Y-%m-%d')}")
        total = resp.get("KeyCount", 0)
        truncated = resp.get("IsTruncated", False)
        print(f"\n  Shown: {total} object(s){'  [truncated — more exist]' if truncated else ''}")
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg  = e.response["Error"]["Message"]
        print(f"  ERROR [{code}]: {msg}")
        if code == "NoSuchBucket":
            print("  Hint: Bucket name may be wrong or in a different region.")
        elif code in ("AccessDenied", "403"):
            print("  Hint: IAM policy does not allow s3:ListBucket on this bucket.")
        return False


def check_s3_head(bucket: str):
    print(f"\n[3/3] Checking bucket metadata (HeadBucket) ...")
    s3 = boto3.client("s3")
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"  Bucket s3://{bucket} is accessible.")
        return True
    except ClientError as e:
        print(f"  ERROR: {e}")
        return False


def main():
    print("=" * 60)
    print(" AWS S3 Access Check")
    print(f" Target bucket: s3://{BUCKET_NAME}/")
    print("=" * 60)

    ok_iam  = check_iam_identity()
    ok_list = check_s3_list(BUCKET_NAME) if ok_iam else False
    ok_head = check_s3_head(BUCKET_NAME) if ok_iam else False

    print("\n" + "=" * 60)
    print(" Summary")
    print("=" * 60)
    print(f"  IAM identity   : {'OK' if ok_iam  else 'FAIL'}")
    print(f"  S3 ListObjects : {'OK' if ok_list else 'FAIL'}")
    print(f"  S3 HeadBucket  : {'OK' if ok_head else 'FAIL'}")
    print("=" * 60)

    sys.exit(0 if (ok_iam and ok_list and ok_head) else 1)


if __name__ == "__main__":
    main()
