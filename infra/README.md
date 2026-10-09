# TensorForge 2.0: AWS deployment (`infra/`)

Infrastructure as code (AWS SAM / CloudFormation) and the runbook for the hosted system.

```
Judges / harness ─┐                        ┌─ Browser
                  │ HTTPS (valid TLS)       │ HTTPS
                  ▼                         ▼
  https://dxxxx.cloudfront.net       https://main.<app-id>.amplifyapp.com   (AWS Amplify Hosting, stack 3)
  CloudFront (no caching)                   │ static React build; calls the API URL with X-API-Key (CORS)
        │ HTTP :8000, CloudFront IPs only   │
        ▼                                   │
  EC2 t4g.medium (Graviton, 2 vCPU / 4 GB) ◄┘   stack 2
   └ systemd → docker run -p 8000:8000 --env-file … -v tf-jobs:/app/data <ECR image:tag>
       API_KEY ◄── SSM SecureString   image/CORS ◄── SSM parameters   logs ──► CloudWatch
  ECR tensorforge-api (multi-arch amd64 + arm64, immutable tags)                 stack 1
        ▲ push (inside AWS)
  CodeBuild tensorforge-api-image: GitHub commit + Git LFS model → native amd64 & arm64 builds   stack "build"
```

| File | What it is |
|---|---|
| `ecr.yaml` | Stack 1 `tensorforge-ecr`: ECR repository (immutable tags, scan on push, kept on delete) |
| `build.yaml` | Stack `tensorforge-build`: CodeBuild project that builds the image from GitHub inside AWS |
| `api.yaml` | Stack 2 `tensorforge-api`: VPC, security group, IAM, EC2 instance + Elastic IP, CloudFront |
| `client.yaml` | Stack 3 `tensorforge-client`: Amplify app + branch for `app/client` |
| `samconfig.toml` | Region, stack names and every parameter. Edit it, then deploy |
| `stack-policy.json` | Blocks updates that would replace the CloudFront distribution or the Elastic IP (= the URL) |
| `scripts/cloud-build.sh` | Run the CodeBuild builds for a pushed commit, print the multi-arch tag |
| `scripts/restart-api.sh` | Restart the container on the instance after a config change, wait until healthy |
| `scripts/parity_check.py` | Same tickets to two instances (local amd64 vs hosted arm64): labels must match |

Why EC2 + CloudFront: see `Resources/architecture_aws_deployment.md` (revision 3).

Run commands **from `infra/`** unless a step says otherwise. Keep one terminal open: the steps reuse
`$AWS_REGION`, `$REPO` and `$TAG`.

**Why the image is built in AWS:** pushing ~1 GB of image layers from a home connection failed after 46 min of
retries. CodeBuild fetches the commit from GitHub (the model comes through Git LFS), builds natively for both
architectures and pushes to ECR inside the region. The laptop sends only API calls. The image is still defined
only by `app/server/Dockerfile` at a pushed commit, which is what judges build locally.

---

## Phase A: API on EC2

### Step 1: Tools and identity

```bash
cd ~/dev/TensorForge/infra
aws --version && sam --version
aws sts get-caller-identity              # the account you will deploy into
docker version --format '{{.Server.Version}}'   # only for the local reference container (step 5)
```

The identity needs CloudFormation, CodeBuild, EC2, IAM, ECR, SSM, CloudWatch Logs, CloudFront, Amplify and
Secrets Manager permissions. An administrator user or SSO role is simplest.

### Step 2: Region lookups → `samconfig.toml`

```bash
export AWS_REGION=ap-south-1
# Amazon Linux 2023 for Graviton (arm64). Pinned: CloudFormation must not swap the AMI on later deploys.
aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
  --query Parameter.Value --output text
# CloudFront origin-facing prefix list (the only source allowed to reach port 8000)
aws ec2 describe-managed-prefix-lists \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text
```

Put the two values into `[api.deploy.parameters]` as `AmiId` and `CloudFrontPrefixListId`.

### Step 3: Secrets: API key → SSM, GitHub token → Secrets Manager

Neither value ever appears in a template, a stack parameter or your shell history.

```bash
# API key, read from app/server/.env
aws ssm put-parameter --name /tensorforge/api/api-key --type SecureString \
  --value "$(grep '^API_KEY=' ../app/server/.env | cut -d= -f2-)"
aws ssm get-parameter --name /tensorforge/api/api-key --with-decryption --query 'length(Parameter.Value)'
```

GitHub token, used by CodeBuild to clone the private repo and its LFS model, and later by Amplify (phase B):
GitHub → Settings → Developer settings → Personal access tokens → **Tokens (classic)** → *Generate new token
(classic)*, expiry ≥ 7 days, scopes **`repo`** and **`admin:repo_hook`**. Then paste the token, press Enter, then
Ctrl-D:

```bash
aws secretsmanager create-secret --name tensorforge/github-token --secret-string "$(cat)"
```

### Step 4: Validate templates, create the registry and the build project

```bash
for t in ecr.yaml build.yaml api.yaml client.yaml; do sam validate --lint -t $t; done
sam deploy --config-env ecr                       # review the change set, answer y
sam deploy --config-env build                     # CodeBuild project tensorforge-api-image
export REPO=$(aws cloudformation describe-stacks --stack-name tensorforge-ecr \
  --query "Stacks[0].Outputs[?OutputKey=='RepositoryUri'].OutputValue" --output text)
echo "$REPO"
```

### Step 5: Build the image in AWS, and a local reference

The commit you build must be **pushed to GitHub, including its LFS model** (`git push` uploads LFS objects).
The build fails early with a clear message if `model.onnx` on GitHub is only an LFS pointer.

```bash
./scripts/cloud-build.sh            # builds HEAD; ~10-20 min; ends with: ImageTag="<tag>"
export TAG=<the tag it printed>
aws ecr describe-images --repository-name tensorforge-api --image-ids imageTag=$TAG \
  --query 'imageDetails[0].[imageManifestMediaType,imageSizeInBytes]'      # an image index (multi-arch)
```

Meanwhile, build the **same commit** locally. This is exactly what judges do, and it is the reference for the parity
check in step 8 (nothing is pulled or pushed):

```bash
cd ..
docker build -f app/server/Dockerfile -t tensorforge-api:ref .
docker rm -f tf-api tf-ref 2>/dev/null            # free port 8000
docker run -d --name tf-ref -p 8000:8000 --env-file app/server/.env tensorforge-api:ref
sleep 30 && curl -s localhost:8000/health         # {"status":"ok",...,"model_version":"v1.2-..."}
cd infra
```

### Step 6: Deploy the API (stack 2)

1. In `samconfig.toml` → `[api.deploy.parameters]`, set `ImageTag` to the `$TAG` you pushed.
2. Deploy:

```bash
sam deploy --config-env api      # review, answer y. ~10-20 min: CloudFront distribution + instance boot,
                                 # image pull, model load. The stack waits until /health is 200 on the instance.
export API_URL=$(aws cloudformation describe-stacks --stack-name tensorforge-api \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
echo "$API_URL"                  # https://dxxxxxxxxxxxxx.cloudfront.net
```

### Step 7: Lock the URL

```bash
aws cloudformation set-stack-policy --stack-name tensorforge-api --stack-policy-body file://stack-policy.json
```

CloudFormation now refuses any update that would replace the CloudFront distribution or the Elastic IP.

### Step 8: Verify, then decide (go / no-go before submitting the URL)

```bash
curl -s "$API_URL/health"                                                    # 200, status ok
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$API_URL/predict" \
  -H 'Content-Type: application/json' -d '{"channel":"chat","text":"x"}'    # 401

cd .. && source app/server/.venv/bin/activate
python app/server/scripts/smoke_test.py --base-url "$API_URL"                # all checks pass
python infra/scripts/parity_check.py --a http://localhost:8000 --b "$API_URL" \
  app/server/tests/fixtures/multilingual_tickets.json app/client/test-data/05_large_job.csv
python app/server/scripts/smoke_test.py --base-url "$API_URL" --job-size 2000 # note the job duration
deactivate && cd infra
```

| Gate | Pass | If it fails |
|---|---|---|
| Smoke test | all checks pass | Read the failing check, `aws logs tail /tensorforge/tensorforge-api` |
| Parity | `OK: all 5 label fields identical` | arm64 kernels change a label → switch to x86 (below) |
| `/predict/batch` 100 tickets | median < 30 s (parity output, side B) | Faster instance (below) |
| 2,000-ticket job | < 15 min (5,000 < 30 min follows from the same rate) | Faster instance (below) |

**Faster instance, same architecture (in place, URL unchanged):** set `InstanceType = "c7g.large"` (Graviton3,
fixed performance, no CPU credits) → `sam deploy --config-env api`. The instance is stopped and started (~2-3 min),
and the job volume and Elastic IP stay.

**Switch to x86 (only if parity fails):** do it before submitting the URL. `aws cloudformation delete-stack
--stack-name tensorforge-api`, wait, then in `samconfig.toml` set `InstanceType = "t3.medium"` (or `c7i.large`)
and `AmiId` = the value of `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`, then
steps 6-8 again. You get a new URL, and the image is the same multi-arch tag.

**Same image as submitted:** the instance pulls the immutable tag, built from the pushed commit. The registry digest
and the digest on the host must be equal:

```bash
aws ecr describe-images --repository-name tensorforge-api --image-ids imageTag=$TAG \
  --query 'imageDetails[0].imageDigest' --output text                         # registry
IID=$(aws cloudformation describe-stacks --stack-name tensorforge-api \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)
CMD=$(aws ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript \
  --parameters 'commands=["docker images --digests"]' --query Command.CommandId --output text)
sleep 5; aws ssm get-command-invocation --command-id "$CMD" --instance-id "$IID" \
  --query StandardOutputContent --output text                                 # DIGEST column (running host)
```

Then submit `$API_URL` and stop the local reference container: `docker rm -f tf-ref`.

### Day-2 operations

| Task | How |
|---|---|
| Logs | `aws logs tail /tensorforge/tensorforge-api --follow` |
| Shell on the instance | `aws ssm start-session --target $IID` (no SSH, no open port 22) |
| Ship a new image | Commit + `git push` → `./scripts/cloud-build.sh` → `ImageTag` in `samconfig.toml` → `sam deploy --config-env api` → `./scripts/restart-api.sh` |
| Build logs | `aws logs tail /tensorforge/codebuild --since 1h` |
| Change CORS | `CorsOrigins` in `samconfig.toml` → `sam deploy --config-env api` → `./scripts/restart-api.sh` |
| Rotate the API key | `aws ssm put-parameter --name /tensorforge/api/api-key --type SecureString --overwrite --value "$(grep '^API_KEY=' ../app/server/.env \| cut -d= -f2-)"` → `./scripts/restart-api.sh` |
| Restart | `./scripts/restart-api.sh`. Running job → `failed/interrupted`, queued jobs survive (contract behaviour) |
| Tear down (after evaluation) | `aws cloudformation delete-stack` for `tensorforge-client`, `tensorforge-api`, then `tensorforge-ecr`. ECR repo is kept on purpose: `aws ecr delete-repository --repository-name tensorforge-api --force` |

**Evaluation window rules:** no deploys, no restarts, no OS updates. Patch before the window if you want:
`aws ssm start-session --target $IID` → `sudo dnf upgrade --security -y` (no reboot needed for the container).

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `cloud-build.sh`: "not on GitHub yet" | `git push` the branch first |
| Build fails at `git fetch` (401/403/404) | Token expired, missing `repo` scope, or wrong `RepositoryUrl`. Update with `aws secretsmanager put-secret-value --secret-id tensorforge/github-token --secret-string "$(cat)"` |
| Build fails: "model.onnx is a Git LFS pointer" | The LFS object never reached GitHub: from the repo root `git lfs push origin <branch>`, or use a faster network once |
| Build fails at `docker build` | Same error as a local build would give: read the log, fix, commit, push, rebuild |
| Stack 2 fails at `ApiReady` (timeout or FAILURE) | `aws ssm start-session --target <InstanceId>` → `sudo cat /var/log/tensorforge-bootstrap.log`, `sudo journalctl -u tensorforge -n 100`. Typical: wrong `ImageTag`, image without arm64, API key parameter missing |
| `InsufficientInstanceCapacity` / type not offered in the AZ | Rare for t4g in ap-south-1. Retry later or use `c7g.large` |
| CloudFront `502` / `504` | Container restarting (check logs), or a request took > 60 s (origin read timeout) |
| `http://` request redirected / POST lost | The URL is HTTPS-only by design (`redirect-to-https`): always use `https://` |
| Browser CORS error (phase B) | `CorsOrigins` must be the exact `ClientUrl` (no trailing slash), then `restart-api.sh` |

**Cost** (ap-south-1, on-demand, estimate): t4g.medium ≈ $22-25/month, public IPv4 ≈ $3.6/month, 30 GB gp3
≈ $2.5/month, CloudFront within the always-free tier (1 TB, 10 M requests per month), ECR ≈ $0.30/month:
**≈ $1 per day**. Unlimited CPU credits add ≈ $0.04 per vCPU-hour only for sustained use above the 20 % baseline.

---

## Phase B: web client on AWS Amplify (after phase A passes step 8)

Amplify builds from GitHub, so the branch it serves must be **pushed** and contain `amplify.yml` and `app/client`.

### B1: Connect Amplify to GitHub (once)

1. Install the Amplify GitHub App for this region, limited to the repository:
   <https://github.com/apps/aws-amplify-ap-south-1/installations/new> → *Only select repositories* →
   `RideEat-TensorForge-Lumora` → *Install*.
2. The GitHub token is already in Secrets Manager (step 3, scope `admin:repo_hook` included). Amplify uses it
   once to set up the connection and does not store it.

### B2: Deploy the client stack (stack 3)

Set `BranchName` in `[client.deploy.parameters]` to the branch you pushed, then:

```bash
sam deploy --config-env client
APP_ID=$(aws cloudformation describe-stacks --stack-name tensorforge-client \
  --query "Stacks[0].Outputs[?OutputKey=='AppId'].OutputValue" --output text)
CLIENT_URL=$(aws cloudformation describe-stacks --stack-name tensorforge-client \
  --query "Stacks[0].Outputs[?OutputKey=='ClientUrl'].OutputValue" --output text)
aws amplify start-job --app-id "$APP_ID" --branch-name <BranchName> --job-type RELEASE   # first build
aws amplify list-jobs --app-id "$APP_ID" --branch-name <BranchName> --max-items 1 \
  --query 'jobSummaries[0].status'                                                      # until SUCCEED
echo "$CLIENT_URL"
```

`VITE_API_BASE_URL` comes from stack 2's `ApiUrl` output. Later pushes to the branch rebuild automatically.

### B3: Allow the site in the API

`CorsOrigins` in `[api.deploy.parameters]` = `$CLIENT_URL` → `sam deploy --config-env api` → `./scripts/restart-api.sh`.
Do this before the evaluation window: it is a restart.

### B4: Check

Open `$CLIENT_URL`. The header shows "Model ready · v1.2-…". Enter the key, classify a sample, run a small batch
(`app/client/test-data/01_quick_batch.csv`). The full manual test is in `app/client/TESTING.md`.
