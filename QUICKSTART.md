# Script Details

Complete reference for DataSync task creation scripts.

## Table of Contents
- [Overview](#overview)
- [Security & Permissions](#security--permissions)
- [Bucket Creation](#bucket-creation)
- [CSV Batch Processing](#csv-batch-processing)
- [Idempotent Operation](#idempotent-operation)
- [Error Handling](#error-handling)
- [Registry Format](#registry-format)
- [Cleanup Script](#cleanup-script)
- [Advanced Usage](#advanced-usage)

## Overview

### What It Does
Creates AWS DataSync tasks to transfer data between S3 buckets across regions with:
- Enhanced mode for optimal S3-to-S3 performance
- Automatic resource creation (buckets, roles, locations)
- Throughput limits
- Batch processing via CSV
- Idempotent operation (safe to re-run)

### Task Configuration
- **Mode**: Enhanced (parallel operations, no object limits)
- **Task Region**: Destination region
- **Verification**: ONLY_FILES_TRANSFERRED
- **Overwrite**: ALWAYS
- **Transfer**: CHANGED
- **Default Throughput**: 250 MB/s

### Task Monitoring
The script can optionally start task executions.  When this option is provided, the task
is started and will run asynchronously in the background.  It can be monitored via the 
AWS DataSync console in the destination region or you can query for the status via
the AWS CLI.

**Check task status**:
```bash
aws datasync describe-task-execution \
  --task-execution-arn <EXECUTION_ARN> \
  --region <DEST_REGION>
```

**List executions**:
```bash
aws datasync list-task-executions \
  --task-arn <TASK_ARN> \
  --region <DEST_REGION>
```

## Security & Permissions

### Required IAM Permissions

**For script execution**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:PutRolePolicy",
        "iam:GetRole",
        "iam:CreateServiceLinkedRole",
        "s3:CreateBucket",
        "s3:GetBucketVersioning",
        "s3:PutBucketPublicAccessBlock",
        "s3:PutEncryptionConfiguration",
        "s3:PutBucketVersioning",
        "datasync:CreateLocationS3",
        "datasync:CreateTask",
        "datasync:ListLocations",
        "datasync:ListTasks",
        "datasync:DescribeTask",
        "datasync:StartTaskExecution"
      ],
      "Resource": "*"
    }
  ]
}
```

### Auto-Created IAM Roles

#### Source Role (Read-Only)
**Name**: `DataSyncS3Role-{bucket}-source`

**Permissions**:
- `s3:GetBucketLocation` - Get bucket region
- `s3:ListBucket` - List objects
- `s3:ListBucketMultipartUploads` - List uploads
- `s3:GetObject` - Read object data
- `s3:GetObjectTagging` - Read tags
- `s3:ListMultipartUploadParts` - List parts

**No write permissions** - Source bucket protected from modification.

#### Destination Role (Write Access)
**Name**: `DataSyncS3Role-{bucket}-dest`

**Permissions**:
- All source role permissions, plus:
- `s3:PutObject` - Write objects
- `s3:DeleteObject` - Delete objects (for overwrite)
- `s3:AbortMultipartUpload` - Cancel failed uploads
- `s3:PutObjectTagging` - Write tags

### Security Benefits
1. **Least Privilege**: Source role cannot modify source data
2. **Isolation**: Each bucket has dedicated role
3. **Audit Trail**: Separate roles for clear CloudTrail logs
4. **Risk Reduction**: Compromised source role cannot write

## Bucket Creation

### When Destination Bucket is Omitted

**Naming**: `{source-bucket}-{dest-region}`

**Examples**:
- `my-data` → `my-data-us-east-1`
- `analytics-source` → `analytics-source-eu-west-1`

### Security Settings

**Public Access Block** (all enabled):
```json
{
  "BlockPublicAcls": true,
  "IgnorePublicAcls": true,
  "BlockPublicPolicy": true,
  "RestrictPublicBuckets": true
}
```

**Default Encryption** (AES256):
```json
{
  "SSEAlgorithm": "AES256",
  "BucketKeyEnabled": true
}
```
- S3-managed keys (no KMS required)
- Automatic encryption at rest
- Cost-optimized with bucket keys

**Versioning** (matches source):
- If source has versioning enabled → destination enabled
- If source has versioning disabled → destination suspended
- Maintains consistency between source and destination

### DataSync Compatibility
All security settings are fully compatible with DataSync:
- ✅ Public Access Block (DataSync uses IAM roles)
- ✅ Default Encryption (automatic encrypt/decrypt)
- ✅ Versioning (creates new versions on overwrite)

### Existing Bucket Handling
If bucket exists and is owned by your account:
- Script continues without error
- Existing settings are **not modified**
- DataSync uses bucket as-is

## CSV Batch Processing

### CSV Format

**Required columns**:
- `source_bucket` - Source S3 bucket name
- `dest_region` - Destination AWS region

**Optional columns**:
- `source_region` - Source region (default: me-central-1)
- `dest_bucket` - Destination bucket (empty = auto-create)
- `throughput_mbps` - Throughput limit (default: 250)
- `source_role_arn` - Source IAM role (empty = auto-create)
- `dest_role_arn` - Destination IAM role (empty = auto-create)
- `task_name` - Friendly task name
- `start` - Auto-start task (true/false/yes/no/1/0)

### Format Rules
- Column names are case-insensitive
- Whitespace automatically trimmed
- Boolean values: `true`, `false`, `yes`, `no`, `1`, `0`
- Empty optional columns use defaults

### Example CSV
```csv
source_bucket,source_region,dest_region,dest_bucket,throughput_mbps,start,task_name
bucket1,me-central-1,us-east-1,,,false,Transfer to US
bucket2,us-west-2,eu-west-1,custom-dest,100,true,Transfer to EU
bucket3,ap-south-1,us-east-1,,,true,Transfer to AP
```

### Validation

**Pre-flight checks**:
- ✅ File exists and readable
- ✅ Not empty
- ✅ Required columns present
- ✅ No invalid columns
- ✅ Required fields not empty
- ✅ Boolean fields valid
- ✅ Numeric fields valid
- ✅ At least one data row

**Validation errors stop processing before any tasks are created.**

### Processing Behavior
- **Sequential**: Tasks processed one at a time
- **Independent**: Each task is isolated
- **Resilient**: Failure of one task doesn't stop others
- **Summary**: Reports succeeded/failed counts

### Example Output
```
Processing task 1/3
✅ Task 1 completed successfully.

Processing task 2/3
❌ Task 2 failed: Bucket already exists in different account

Processing task 3/3
✅ Task 3 completed successfully.

Summary: 2 succeeded, 1 failed out of 3 total
```

## Idempotent Operation

The script is safe to re-run. It reuses existing resources instead of failing.

### IAM Roles
- **Check**: Calls `iam:GetRole` with role name
- **Exists**: Reuses existing role ARN
- **Not Exists**: Creates new role
- **Error**: `EntityAlreadyExists` caught and ignored

### S3 Locations
- **Check**: Lists all locations, compares bucket ARNs
- **Exists**: Reuses existing location ARN
- **Not Exists**: Creates new location

### DataSync Tasks
- **Check**: Lists all tasks in destination region
- **Comparison**: Checks both source and destination location ARNs
- **Exists**: Reuses existing task ARN
- **Not Exists**: Creates new task

**Note**: LocationId filter doesn't work cross-region, so script lists all tasks and filters manually.

### S3 Buckets
- **Check**: Attempts to create bucket
- **Exists**: `BucketAlreadyOwnedByYou` caught, continues
- **Different Owner**: `BucketAlreadyExists` error raised

### Benefits
- Safe to re-run after failures
- No duplicate resources created
- Consistent task configuration
- Predictable behavior

### Limitations
- Script doesn't update existing resources (throughput, options)
- Registry may accumulate duplicate entries on re-runs
- Existing bucket settings not modified

## Error Handling

### CSV Validation Errors
**When**: Before any tasks are created
**Behavior**: Script exits with error message and row number
**Example**:
```
❌ CSV validation failed: Row 3: 'source_bucket' cannot be empty
```

### Task Creation Errors
**When**: During individual task creation
**Behavior**: 
- Error logged to stderr
- Task marked as failed
- Processing continues to next task
- Registry saved with successful tasks

### Task Start Errors
**When**: Auto-starting task execution
**Behavior**:
- Exception caught (including timeouts)
- Task creation still successful
- Registry always saved
- Manual start command printed

**Example**:
```
⚠ Failed to start task execution: Connection timeout

To start manually, run:
  aws datasync start-task-execution --task-arn <ARN> --region us-east-1
```

### Registry Save Errors
**When**: Writing to JSON file
**Behavior**: 
- Warning printed to stderr
- Exception raised
- Task creation considered failed

## Registry Format

### File Structure
```json
{
  "tasks": [
    {
      "task_arn": "arn:aws:datasync:...",
      "task_name": "my-transfer-task",
      "task_region": "us-east-1",
      "created_at": "2024-01-15T10:30:00Z",
      "source": {
        "bucket": "my-source-bucket",
        "region": "me-central-1",
        "location_arn": "arn:aws:datasync:...",
        "role_arn": "arn:aws:iam::...",
        "role_created": true
      },
      "destination": {
        "bucket": "my-source-bucket-us-east-1",
        "region": "us-east-1",
        "location_arn": "arn:aws:datasync:...",
        "role_arn": "arn:aws:iam::...",
        "role_created": true
      },
      "throughput_mbps": 250,
      "task_execution_arn": "arn:aws:datasync:...",
      "execution_started_at": "2024-01-15T10:30:15Z"
    }
  ]
}
```

### Field Descriptions

**task_arn**: DataSync task ARN
**task_name**: Friendly name (if provided)
**task_region**: Region where task was created (destination region)
**created_at**: ISO 8601 timestamp
**source.bucket**: Source bucket name
**source.region**: Source region
**source.location_arn**: DataSync source location ARN
**source.role_arn**: IAM role ARN for source
**source.role_created**: True if role was created by script
**destination.***: Same fields for destination
**throughput_mbps**: Configured throughput limit
**task_execution_arn**: Execution ARN (if task was started)
**execution_started_at**: Execution start timestamp (if started)

### Usage
- **Cleanup**: Used by cleanup script to delete resources
- **Audit**: Track what was created and when
- **Troubleshooting**: Reference ARNs for AWS CLI commands
- **Idempotency**: Check for existing resources (future enhancement)

## Cleanup Script

### What It Deletes
1. **DataSync Tasks**: All tasks in registry
2. **DataSync Locations**: Source and destination locations
3. **IAM Roles**: Only roles created by script (`role_created: true`)

### What It Preserves
- **S3 Buckets**: Never deleted (data safety)
- **Manually Created Roles**: Only auto-created roles deleted

### Usage

**Preview (dry-run)**:
```bash
python cleanup_datasync_tasks.py --dry-run
```

**Execute cleanup**:
```bash
python cleanup_datasync_tasks.py
```

**Custom registry file**:
```bash
python cleanup_datasync_tasks.py --registry-file my-tasks.json
```

### Dry-Run Output
```
🔍 DRY RUN MODE - No resources will be deleted

Task 1/2:
  Task ARN: arn:aws:datasync:us-east-1:...
  Source Location: arn:aws:datasync:me-central-1:...
  Dest Location: arn:aws:datasync:us-east-1:...
  Source Role: arn:aws:iam::...:role/DataSyncS3Role-bucket-source (will delete)
  Dest Role: arn:aws:iam::...:role/DataSyncS3Role-bucket-dest (will delete)

Summary: Would delete 2 tasks, 4 locations, 4 roles
```

### Safety Features
- Dry-run mode for preview
- Never deletes buckets
- Only deletes script-created roles
- Continues on errors (best-effort cleanup)
- Reports success/failure counts

## Advanced Usage

### Custom Encryption (Post-Creation)

**Switch to KMS**:
```bash
aws s3api put-bucket-encryption \
  --bucket BUCKET_NAME \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "aws:kms",
        "KMSMasterKeyID": "arn:aws:kms:REGION:ACCOUNT:key/KEY_ID"
      }
    }]
  }'
```

### Lifecycle Policies

**Add lifecycle rule**:
```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket BUCKET_NAME \
  --lifecycle-configuration file://lifecycle.json
```

**Example lifecycle.json**:
```json
{
  "Rules": [{
    "Id": "DeleteOldVersions",
    "Status": "Enabled",
    "NoncurrentVersionExpiration": {
      "NoncurrentDays": 90
    }
  }]
}
```

### Monitoring Task Execution

**Check task status**:
```bash
aws datasync describe-task-execution \
  --task-execution-arn <EXECUTION_ARN> \
  --region <DEST_REGION>
```

**List executions**:
```bash
aws datasync list-task-executions \
  --task-arn <TASK_ARN> \
  --region <DEST_REGION>
```

### Manual Resource Creation

**Create role manually**:
```bash
aws iam create-role \
  --role-name MyDataSyncRole \
  --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy \
  --role-name MyDataSyncRole \
  --policy-name DataSyncS3Access \
  --policy-document file://permissions.json
```

Then use with `--source-role-arn` or `--dest-role-arn`.

### Cross-Account Transfers

For cross-account transfers, manually create:
1. IAM roles in both accounts
2. Bucket policies allowing cross-account access
3. Use `--source-role-arn` and `--dest-role-arn`

**Not supported by auto-creation** - requires manual setup.

### Troubleshooting

**Task creation fails**:
- Check IAM permissions
- Verify source bucket exists
- Check region names are valid
- Review CloudTrail logs

**Task execution fails**:
- Check IAM role permissions
- Verify bucket policies
- Check encryption settings
- Review DataSync execution logs

**Cleanup fails**:
- Check IAM permissions for delete operations
- Verify resources still exist
- Use `--dry-run` to preview
- Manually delete stuck resources

### Best Practices

1. **Use CSV for multiple tasks**: More efficient than multiple CLI runs
2. **Enable versioning**: Protects against accidental deletion
3. **Monitor executions**: Check CloudWatch metrics
4. **Test with small datasets**: Verify configuration before large transfers
5. **Use dry-run**: Always preview cleanup before executing
6. **Keep registry file**: Essential for cleanup and audit
7. **Review IAM permissions**: Follow least privilege principle
8. **Consider costs**: Throughput limits affect transfer time and cost
9. **Plan for failures**: Tasks can be restarted from last checkpoint
10. **Document custom settings**: If modifying auto-created resources

### Performance Tuning

**Throughput limits**:
- Default: 250 MB/s (good balance)
- Lower: 100 MB/s (cost-sensitive)
- Higher: 500+ MB/s (time-sensitive)

**Enhanced mode benefits**:
- Parallel operations
- No object count limits
- Better performance for S3-to-S3
- Automatic optimization

**Transfer optimization**:
- Use CHANGED transfer mode (only modified files)
- Enable versioning for incremental transfers
- Consider lifecycle policies for old versions
- Monitor CloudWatch metrics for bottlenecks
