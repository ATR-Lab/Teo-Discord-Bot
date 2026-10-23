#!/bin/bash
# One-time: let GitHub Actions in ATR-Lab/Teo-Discord-Bot deploy without stored AWS keys.
# Creates GitHub's OIDC provider in the account (if missing) and the role atr-teo-github-deploy,
# which only the repo's "production" environment can assume, scoped to Teo's bucket and instance.
# Prints the role ARN; store it as the repo variable AWS_DEPLOY_ROLE_ARN.
set -euo pipefail
cd "$(dirname "$0")"; source ./config.sh
A() { $AWS_CLI --region "$REGION" "$@"; }
REPO="${REPO:-ATR-Lab/Teo-Discord-Bot}"
ROLE="$NAME-github-deploy"
PROVIDER="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"

A iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER" >/dev/null 2>&1 ||
  A iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com >/dev/null

TRUST=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Principal":{"Federated":"$PROVIDER"},
  "Action":"sts:AssumeRoleWithWebIdentity",
  "Condition":{"StringEquals":{
    "token.actions.githubusercontent.com:aud":"sts.amazonaws.com",
    "token.actions.githubusercontent.com:sub":"repo:$REPO:environment:production"}}}]}
JSON
)
if A iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  A iam update-assume-role-policy --role-name "$ROLE" --policy-document "$TRUST"
else
  A iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" \
    --description "GitHub Actions deploys for $REPO" >/dev/null
fi

ID=$(A ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
A iam put-role-policy --role-name "$ROLE" --policy-name teo-deploy --policy-document "{
 \"Version\":\"2012-10-17\",\"Statement\":[
  {\"Effect\":\"Allow\",\"Action\":\"s3:PutObject\",\"Resource\":\"arn:aws:s3:::$BUCKET/*\"},
  {\"Effect\":\"Allow\",\"Action\":\"ssm:SendCommand\",\"Resource\":[
     \"arn:aws:ec2:$REGION:$ACCOUNT:instance/$ID\",
     \"arn:aws:ssm:$REGION::document/AWS-RunShellScript\"]},
  {\"Effect\":\"Allow\",\"Action\":[\"ssm:GetCommandInvocation\",\"ssm:ListCommandInvocations\",\"ec2:DescribeInstances\"],\"Resource\":\"*\"}]}"
A iam get-role --role-name "$ROLE" --query Role.Arn --output text
