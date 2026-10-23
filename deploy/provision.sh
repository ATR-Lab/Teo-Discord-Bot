#!/bin/bash
# One-time AWS setup for Teo: private S3 bucket, SSM SecureString secrets, an instance role (SSM + read
# its own secrets and bucket), a security group with no inbound rules and one t4g.micro Amazon Linux 2023
# instance managed through SSM (no SSH). Secrets are read from stdin-style env vars and never echoed:
#   DISCORD_BOT_TOKEN=... ANTHROPIC_API_KEY=... deploy/provision.sh
set -euo pipefail
cd "$(dirname "$0")"; source ./config.sh
A() { $AWS_CLI --region "$REGION" "$@"; }

: "${DISCORD_BOT_TOKEN:?set DISCORD_BOT_TOKEN}"; : "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY}"

# S3 bucket for releases (private, encrypted by default)
A s3api head-bucket --bucket "$BUCKET" 2>/dev/null || A s3api create-bucket --bucket "$BUCKET" \
  --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
A s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Secrets
printf '%s' "$DISCORD_BOT_TOKEN" | A ssm put-parameter --name /atr-teo/DISCORD_BOT_TOKEN --type SecureString --overwrite \
  --value "file:///dev/stdin" >/dev/null
printf '%s' "$ANTHROPIC_API_KEY" | A ssm put-parameter --name /atr-teo/ANTHROPIC_API_KEY --type SecureString --overwrite \
  --value "file:///dev/stdin" >/dev/null

# Instance role
if ! A iam get-role --role-name "$NAME-instance" >/dev/null 2>&1; then
  A iam create-role --role-name "$NAME-instance" --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  A iam attach-role-policy --role-name "$NAME-instance" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  A iam create-instance-profile --instance-profile-name "$NAME-instance" >/dev/null
  A iam add-role-to-instance-profile --instance-profile-name "$NAME-instance" --role-name "$NAME-instance"
  sleep 10
fi
A iam put-role-policy --role-name "$NAME-instance" --policy-name teo-access --policy-document "{
  \"Version\":\"2012-10-17\",\"Statement\":[
   {\"Effect\":\"Allow\",\"Action\":\"ssm:GetParameter\",\"Resource\":\"arn:aws:ssm:$REGION:$ACCOUNT:parameter/atr-teo/*\"},
   {\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"arn:aws:s3:::$BUCKET/*\"}]}"

# Network: default VPC, no inbound rules (the bot only makes outbound connections)
VPC=$(A ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(A ec2 describe-security-groups --filters Name=group-name,Values="$NAME" Name=vpc-id,Values="$VPC" --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(A ec2 create-security-group --group-name "$NAME" --description "Teo Discord bot: outbound only" --vpc-id "$VPC" --query GroupId --output text)
fi

# Instance
ID=$(A ec2 describe-instances --filters Name=tag:Name,Values="$NAME" Name=instance-state-name,Values=pending,running,stopped \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
if [ "$ID" = "None" ]; then
  AMI=$(A ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 --query Parameter.Value --output text)
  ID=$(A ec2 run-instances --image-id "$AMI" --instance-type t4g.micro --iam-instance-profile Name="$NAME-instance" \
    --security-group-ids "$SG" --metadata-options HttpTokens=required,HttpEndpoint=enabled \
    --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=8,VolumeType=gp3,Encrypted=true}' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=project,Value=atr-lab-teo-bot}]" \
    --query 'Instances[0].InstanceId' --output text)
  A ec2 wait instance-running --instance-ids "$ID"
fi
echo "instance $ID (bucket $BUCKET, region $REGION)"
