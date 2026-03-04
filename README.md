# Quick Start Guide

Get started with DataSync task creation in minutes.

## Prerequisites

1. **AWS Credentials**: Configure with `aws configure`
2. **IAM Permissions**:
   - `iam:CreateRole`, `iam:PutRolePolicy`, `iam:GetRole`
   - `iam:CreateServiceLinkedRole` (for Enhanced mode)
   - `s3:CreateBucket` (if auto-creating destination bucket)
   - `datasync:*`
3. **Source Bucket**: Must exist in source region (default: me-central-1)

## Simplest Usage

Auto-create destination bucket and all resources:

```bash
python create_datasync_task.py \
    --source-bucket my-bucket \
    --source-region me-central-1 \
    --dest-region us-east-1
```

This automatically:
- Creates destination bucket: `my-bucket-us-east-1`
- Creates IAM roles (source read-only, destination write)
- Creates DataSync locations
- Creates Enhanced mode task (250 MB/s default)
- Saves to `datasync_tasks.json`

## Command Line Options

### Required
- `--source-bucket` - Source S3 bucket name
- `--dest-region` - Destination AWS region (e.g., us-east-1, eu-west-1)

### Optional
- `--source-region` - Source AWS region (default: me-central-1)
- `--dest-bucket` - Destination bucket name (omit to auto-create)
- `--throughput-mbps` - Throughput limit in Mbps (default: 250)
- `--source-role-arn` - IAM role ARN for source (omit to auto-create)
- `--dest-role-arn` - IAM role ARN for destination (omit to auto-create)
- `--task-name` - Friendly name for the task
- `--output-file` - JSON registry file (default: datasync_tasks.json)
- `--start` - Auto-start task after creation
- `--csv-file` - CSV file for batch processing

## Common Examples

### Use Existing Destination Bucket
```bash
python create_datasync_task.py \
    --source-bucket my-bucket \
    --dest-bucket existing-bucket \
    --dest-region us-east-1
```

### Custom Source Region
```bash
python create_datasync_task.py \
    --source-bucket my-bucket \
    --source-region us-west-2 \
    --dest-region eu-west-1
```

### Custom Throughput
```bash
python create_datasync_task.py \
    --source-bucket my-bucket \
    --dest-region us-east-1 \
    --throughput-mbps 100
```

### Auto-Start Task
```bash
python create_datasync_task.py \
    --source-bucket my-bucket \
    --dest-region us-east-1 \
    --start
```

### Use Existing IAM Roles
```bash
python create_datasync_task.py \
    --source-bucket my-bucket \
    --dest-bucket my-dest \
    --dest-region us-east-1 \
    --source-role-arn arn:aws:iam::123456789012:role/SourceRole \
    --dest-role-arn arn:aws:iam::123456789012:role/DestRole
```

## CSV Batch Processing

### CSV Format

**Required columns**: `source_bucket`, `dest_region`

**Optional columns**: `source_region`, `dest_bucket`, `throughput_mbps`, `source_role_arn`, `dest_role_arn`, `task_name`, `start`

### Example CSV

```csv
source_bucket,source_region,dest_region,throughput_mbps,start
bucket1,me-central-1,us-east-1,250,false
bucket2,us-west-2,eu-west-1,100,true
bucket3,ap-south-1,us-east-1,250,true
```

### Run Batch

```bash
python create_datasync_task.py --csv-file tasks.csv
```

**Notes**:
- Column names are case-insensitive
- Boolean values: `true`, `false`, `yes`, `no`, `1`, `0`
- Empty `dest_bucket` auto-creates bucket
- Tasks processed sequentially
- Failures don't stop other tasks

## Starting Tasks

### Manual Start
```bash
aws datasync start-task-execution \
    --task-arn <TASK_ARN> \
    --region <DEST_REGION>
```

### Auto-Start
Add `--start` flag or set `start` column to `true` in CSV.

## Cleanup

Preview what will be deleted:
```bash
python cleanup_datasync_tasks.py --dry-run
```

Delete all resources (buckets are never deleted):
```bash
python cleanup_datasync_tasks.py
```

## What Gets Created

1. **Destination Bucket** (if omitted):
   - Name: `{source-bucket}-{dest-region}`
   - Public access blocked
   - AES256 encryption enabled
   - Versioning matches source

2. **IAM Roles** (if not provided):
   - Source: `DataSyncS3Role-{bucket}-source` (read-only)
   - Destination: `DataSyncS3Role-{bucket}-dest` (write)

3. **DataSync Locations**:
   - Source location in source region
   - Destination location in destination region

4. **DataSync Task**:
   - Enhanced mode (optimal for S3-to-S3)
   - Created in destination region
   - Throughput limit applied
   - Verify: ONLY_FILES_TRANSFERRED
   - Overwrite: ALWAYS
   - Transfer: CHANGED

5. **Registry File**: JSON file tracking all created resources

## Next Steps

See [SCRIPT_DETAILS.md](SCRIPT_DETAILS.md) for:
- Security and permissions details
- Idempotent operation behavior
- Error handling
- Registry format
- Advanced usage
