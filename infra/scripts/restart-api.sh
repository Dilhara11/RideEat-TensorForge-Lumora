#!/usr/bin/env bash
# Apply a config change on the EC2 host: restart the container service, which re-reads the image tag, CORS origins
# and API key from SSM, then wait until the public URL is healthy again.
# Use after `sam deploy --config-env api` changed ImageTag or CorsOrigins, or after rotating the API key.
#   ./scripts/restart-api.sh            (from infra/; STACK=... to target another stack)
# A restart mid-job ends that job as failed/interrupted; queued jobs survive (same as `docker restart` locally).
set -euo pipefail
STACK=${STACK:-tensorforge-api}

output() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
INSTANCE_ID=$(output InstanceId)
API_URL=$(output ApiUrl)

echo "restarting tensorforge.service on $INSTANCE_ID"
CMD_ID=$(aws ssm send-command --instance-ids "$INSTANCE_ID" --document-name AWS-RunShellScript \
  --comment "restart tensorforge" --parameters 'commands=["systemctl restart tensorforge"]' \
  --query Command.CommandId --output text)
aws ssm wait command-executed --command-id "$CMD_ID" --instance-id "$INSTANCE_ID"

echo "waiting for $API_URL/health (image pull + model load, usually 1-3 min)"
for _ in $(seq 1 60); do
  body=$(curl -s --max-time 5 "$API_URL/health" || true)
  if echo "$body" | grep -Eq '"status" ?: ?"ok"'; then
    echo "$body"
    exit 0
  fi
  sleep 10
done
echo "not healthy after 10 min; check: aws logs tail /tensorforge/tensorforge-api --since 15m" >&2
exit 1
