# Shopping Copilot - Deployment Specification

**Service Owner:** AIO02 Team  
**Version:** 1.0.0  
**Last Updated:** 2026-07-26  
**Target Environment:** EKS `techx-tf3` namespace

---

## 1. Feature Overview

### 1.1 Purpose

AI-powered conversational shopping assistant providing natural language product search, reviews lookup, cart management, and personalized recommendations for TechX Corp e-commerce platform.

### 1.2 Key Capabilities

- **Hybrid Search:** SQL-based exact matching + RAG semantic search with cross-encoder reranking
- **Multi-tool Agent:** 10 tools including product search, cart operations, reviews, recommendations, currency conversion, shipping quotes
- **6-Layer Guardrails:** Input filtering, PII redaction, prompt injection detection, rate limiting, write confirmation, tool validation
- **Bedrock Integration:** Amazon Nova Lite LLM with AWS Bedrock Guardrails and Knowledge Base
- **Session Persistence:** Valkey-backed conversation history with LRU cache
- **Fallback System:** Graceful degradation on service failures, guaranteed response within 15s

### 1.3 Architecture

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ HTTP/REST
       ↓
┌─────────────────────────────────────────────┐
│         Shopping Copilot (FastAPI)          │
│  ┌──────────────────────────────────────┐   │
│  │  CopilotAgent (ReAct Loop)           │   │
│  │  - 6 Guardrail Layers                │   │
│  │  - 10 Agent Tools                    │   │
│  │  - Step Tracking                     │   │
│  └──────────────────────────────────────┘   │
│         ↓                    ↓               │
│  ┌─────────────┐      ┌─────────────┐       │
│  │ AWS Bedrock │      │ Search      │       │
│  │ Nova Lite   │      │ Pipeline    │       │
│  │ Guardrails  │      │ Flow1+Flow2 │       │
│  │ KB (RAG)    │      │ Reranker    │       │
│  └─────────────┘      └─────────────┘       │
└─────────────────────────────────────────────┘
       ↓                    ↓            ↓
┌──────────┐         ┌──────────┐  ┌──────────┐
│PostgreSQL│         │  Valkey  │  │  gRPC    │
│(catalog, │         │(session, │  │Services  │
│ reviews) │         │ cache)   │  │(8 μsvcs) │
└──────────┘         └──────────┘  └──────────┘
```

### 1.4 Technology Stack

| Component | Technology                | Version                    |
| --------- | ------------------------- | -------------------------- |
| Runtime   | Python                    | 3.11                       |
| Framework | FastAPI + Uvicorn         | Latest                     |
| LLM       | AWS Bedrock Nova Lite     | apac.amazon.nova-lite-v1:0 |
| Database  | PostgreSQL                | (cluster-managed)          |
| Cache     | Valkey (Redis-compatible) | (cluster-managed)          |
| gRPC      | grpcio + protobuf         | Latest                     |
| Container | Docker multi-stage        | alpine-based               |

---

## 2. Container Specification

### 2.1 Image Details

```
Registry:    197826770971.dkr.ecr.ap-southeast-1.amazonaws.com
Repository:  shopping-copilot
Tag:         v1.0.0
Platform:    linux/amd64
Base Image:  python:3.11-slim
```

### 2.2 Dockerfile

- **Location:** `shopping-copilot/Dockerfile`
- **Build Type:** Multi-stage (builder + runtime)
- **User:** Non-root (`appuser`)
- **Exposed Port:** 8001
- **Health Check:** `GET /health` every 30s
- **Entry Point:** `uvicorn src.main:app --host 0.0.0.0 --port 8001`

### 2.3 Build Command

```bash
docker build -t 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/shopping-copilot:v1.0.0 \
  --platform linux/amd64 \
  -f shopping-copilot/Dockerfile \
  shopping-copilot/
```

---

## 3. Kubernetes Deployment

### 3.1 Manifests Location

```
shopping-copilot/contracts/k8s-serviceaccount.yaml
shopping-copilot/contracts/k8s-deployment.yaml
```

### 3.2 ServiceAccount (IRSA)

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: shopping-copilot-sa
  namespace: techx-tf3
  annotations:
    eks.amazonaws.com/role-arn: "arn:aws:iam::197826770971:role/<IAM_ROLE_NAME>"
```

**Required IAM Permissions:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:ApplyGuardrail",
        "bedrock:Retrieve"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::techx-products-catalog-2026",
        "arn:aws:s3:::techx-products-catalog-2026/*"
      ]
    }
  ]
}
```

### 3.3 Deployment Spec

```yaml
replicas: 2
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 1
    maxSurge: 1

resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi

livenessProbe:
  httpGet:
    path: /health
    port: 8001
  initialDelaySeconds: 20
  periodSeconds: 30
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health
    port: 8001
  initialDelaySeconds: 10
  periodSeconds: 10
  failureThreshold: 3
```

### 3.4 Service

```yaml
type: ClusterIP
port: 8001
targetPort: 8001
selector:
  app: shopping-copilot
```

---

## 4. Configuration

### 4.1 Environment Variables (ConfigMap)

#### AWS Bedrock Configuration

| Variable                    | Value                         | Description                |
| --------------------------- | ----------------------------- | -------------------------- |
| `BEDROCK_MODEL_ID`          | `apac.amazon.nova-lite-v1:0`  | LLM model identifier       |
| `BEDROCK_REGION`            | `ap-southeast-1`              | AWS region for Bedrock API |
| `BEDROCK_GUARDRAIL_ID`      | `3ab7r29x59x4`                | Guardrail identifier       |
| `BEDROCK_GUARDRAIL_VERSION` | `DRAFT`                       | Guardrail version          |
| `BEDROCK_GUARDRAIL_REGION`  | `us-east-1`                   | Guardrail region           |
| `BEDROCK_KB_ID`             | `UCTITOWFHE`                  | Knowledge Base ID for RAG  |
| `BEDROCK_KB_DATA_SOURCE_ID` | `OJQNE88GXV`                  | Products data source       |
| `REVIEWS_DATA_SOURCE_ID`    | `M2YA7L7GEA`                  | Reviews data source        |
| `PRODUCTS_S3_BUCKET`        | `techx-products-catalog-2026` | S3 bucket for product data |

#### Database Configuration

| Variable               | Value                                                                                         | Description            |
| ---------------------- | --------------------------------------------------------------------------------------------- | ---------------------- |
| `DB_HOST`              | `postgresql.techx-tf3.svc.cluster.local`                                                      | PostgreSQL host        |
| `DB_PORT`              | `5432`                                                                                        | PostgreSQL port        |
| `DB_NAME`              | `otel`                                                                                        | Database name          |
| `DB_USER`              | `otelu`                                                                                       | Database user          |
| `DB_PASSWORD`          | (Secret)                                                                                      | Database password      |
| `DB_CONNECTION_STRING` | `host=postgresql.techx-tf3.svc.cluster.local port=5432 user=otelu password=otelp dbname=otel` | Full connection string |

#### Session & Cache Configuration

| Variable     | Value                                                    | Description                                                    |
| ------------ | -------------------------------------------------------- | -------------------------------------------------------------- |
| `VALKEY_URL` | `redis://valkey-cart.techx-tf3.svc.cluster.local:6379/1` | Valkey connection URL (DB=1 to isolate from Cart service DB=0) |

#### gRPC Microservices Configuration

| Variable        | Value                                              | Protocol | Port |
| --------------- | -------------------------------------------------- | -------- | ---- |
| `CATALOG_ADDR`  | `product-catalog.techx-tf3.svc.cluster.local:8080` | gRPC     | 8080 |
| `CART_ADDR`     | `cart.techx-tf3.svc.cluster.local:8080`            | gRPC     | 8080 |
| `REVIEWS_ADDR`  | `product-reviews.techx-tf3.svc.cluster.local:3551` | gRPC     | 3551 |
| `RECO_ADDR`     | `recommendation.techx-tf3.svc.cluster.local:8080`  | gRPC     | 8080 |
| `CURRENCY_ADDR` | `currency.techx-tf3.svc.cluster.local:8080`        | gRPC     | 8080 |
| `SHIPPING_ADDR` | `http://shipping.techx-tf3.svc.cluster.local:8080` | HTTP     | 8080 |

#### Application Configuration

| Variable               | Value | Description        |
| ---------------------- | ----- | ------------------ |
| `CORS_ALLOWED_ORIGINS` | `*`   | CORS configuration |

### 4.2 Secrets (K8s Secret)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: shopping-copilot-secret
  namespace: techx-tf3
type: Opaque
stringData:
  DB_PASSWORD: "otelp"
```

---

## 5. Dependencies

### 5.1 Internal Services (K8s Cluster)

**Critical Dependencies - Must be running:**
| Service | DNS | Port | Protocol | Schema/Collection |
|---------|-----|------|----------|-------------------|
| PostgreSQL | `postgresql.techx-tf3.svc.cluster.local` | 5432 | TCP | `catalog`, `reviews` schemas |
| Valkey | `valkey-cart.techx-tf3.svc.cluster.local` | 6379 | TCP | DB=1 (isolated from cart) |
| Product Catalog | `product-catalog.techx-tf3.svc.cluster.local` | 8080 | gRPC | - |
| Cart Service | `cart.techx-tf3.svc.cluster.local` | 8080 | gRPC | - |
| Product Reviews | `product-reviews.techx-tf3.svc.cluster.local` | 3551 | gRPC | - |
| Recommendation | `recommendation.techx-tf3.svc.cluster.local` | 8080 | gRPC | - |
| Currency Service | `currency.techx-tf3.svc.cluster.local` | 8080 | gRPC | - |
| Shipping Service | `shipping.techx-tf3.svc.cluster.local` | 8080 | HTTP | - |

**Database Schemas:**

- `catalog.products` - Product catalog table
- `reviews.productreviews` - Product reviews table

**Valkey Keys:**

- `session:<session_id>` - User conversation history (TTL: 1 hour)
- `cache:<key>` - Search/tool result cache (LRU + TTL)

### 5.2 External Services (AWS)

| Service                | Resource ID                   | Region         | Purpose                          |
| ---------------------- | ----------------------------- | -------------- | -------------------------------- |
| Bedrock (Nova Lite)    | `apac.amazon.nova-lite-v1:0`  | ap-southeast-1 | LLM inference                    |
| Bedrock Guardrails     | `3ab7r29x59x4`                | us-east-1      | Content filtering, PII detection |
| Bedrock Knowledge Base | `UCTITOWFHE`                  | ap-southeast-1 | RAG semantic search              |
| S3 Bucket              | `techx-products-catalog-2026` | ap-southeast-1 | Product data for KB              |

---

## 6. API Specification

### 6.1 Endpoints

#### `GET /health`

Health check for K8s probes.

**Response:** `200 OK`

```json
{ "status": "ok", "service": "shopping-copilot", "version": "1.0.0" }
```

#### `GET /chatbot`

HTML UI for testing.

#### `POST /api/chat`

Main conversation endpoint.

**Request:**

```json
{
  "message": "string (required, max 1000 chars)",
  "session_id": "string (optional, auto-generated)",
  "user_id": "string (optional, default: 'anonymous')"
}
```

**Response:**

```json
{
  "status": "ok|pending|error",
  "reply": "string (markdown)",
  "session_id": "uuid",
  "token": "string|null (JWT for confirmation)",
  "steps": [{ "action": "tool_name", "status": "ok", "duration_ms": 1200 }]
}
```

#### `POST /api/confirm`

Confirm write actions (add to cart).

**Request:**

```json
{ "session_id": "uuid", "token": "jwt" }
```

**Response:**

```json
{ "status": "ok", "reply": "Success message" }
```

#### `GET /api/cart?user_id=<id>`

Retrieve user's shopping cart.

**Response:**

```json
{
  "user_id": "string",
  "items": [
    {
      "product_id": "string",
      "name": "string",
      "price": "string",
      "quantity": 1
    }
  ]
}
```

#### `GET /docs`

OpenAPI/Swagger documentation.

### 6.2 Rate Limiting

- **Per-user limit:** 10 requests/minute (tracked by `user_id`)
- **Token limit:** 100,000 tokens/minute per user
- **Response on limit:** HTTP 200 with `{"status": "error", "error_code": "rate_limit_exceeded"}`
- **No CDO-side configuration required** (handled by application)

### 6.3 Response Times

| Percentile | Target | Measurement                |
| ---------- | ------ | -------------------------- |
| p50        | < 1.5s | Median response time       |
| p95        | < 3.0s | 95th percentile            |
| p99        | < 5.0s | 99th percentile            |
| Timeout    | 15s    | Hard timeout with fallback |

---

## 7. Operational Characteristics

### 7.1 Session Management

- **Storage:** Valkey (Redis-compatible) DB=1
- **TTL:** 1 hour (sliding window on activity)
- **Structure:** JSON-serialized conversation history per session
- **Persistence:** Disk-backed (Valkey persistence enabled)
- **Key Pattern:** `session:<uuid>`

### 7.2 Cache Management

- **Storage:** Valkey DB=1
- **Strategy:** LRU eviction + TTL
- **TTL:**
  - Search results: 300s
  - Tool outputs: 60s
  - Product data: 600s
- **Key Pattern:** `cache:<hash>`
- **Max Size:** 1000 keys per cache type

### 7.3 Logging

**Log Format:** JSON structured logs
**Log Level:** INFO (configurable via env `LOG_LEVEL`)
**Key Events:**

- Request/response (including latency, status)
- Tool invocations (tool name, params, result)
- Bedrock API calls (model, tokens, cost)
- Guardrail triggers (type, reason, action)
- Rate limit hits (user_id, timestamp)
- Errors (stack trace, context)

### 7.4 Metrics

**Prometheus-compatible metrics exposed on `/metrics`:**

```
copilot_requests_total{method, endpoint, status}
copilot_request_duration_seconds{endpoint, quantile}
copilot_bedrock_calls_total{model, status}
copilot_bedrock_duration_seconds{model}
copilot_bedrock_tokens_used{model, type}
copilot_tool_calls_total{tool, status}
copilot_rate_limit_rejections_total{user_id}
copilot_guardrail_triggers_total{layer, action}
copilot_cache_hits_total{cache_type}
copilot_cache_misses_total{cache_type}
copilot_session_active_count
```

### 7.5 SLOs

| Metric             | Target | Measurement Period |
| ------------------ | ------ | ------------------ |
| Availability       | 99.5%  | 30 days            |
| Latency (p95)      | < 3.0s | 5 minutes          |
| Error Rate         | < 1%   | 5 minutes          |
| Bedrock Error Rate | < 0.5% | 5 minutes          |

### 7.6 Alerts (Recommended)

| Alert           | Condition                           | Severity |
| --------------- | ----------------------------------- | -------- |
| High Error Rate | `error_rate > 5%` for 5 min         | Critical |
| High Latency    | `p95 > 5s` for 5 min                | Warning  |
| Bedrock Errors  | `bedrock_error_rate > 2%` for 3 min | Warning  |
| Pod Restarts    | `restart_count > 3` in 10 min       | Critical |
| IRSA Failure    | `bedrock_auth_errors > 0`           | Critical |

---

## 8. Security & Compliance

### 8.1 6-Layer Guardrail System

| Layer | Component         | Function                                       | Implementation                     |
| ----- | ----------------- | ---------------------------------------------- | ---------------------------------- |
| L1    | Confirmation Gate | HMAC-based write confirmation                  | `src/guardrails/confirmation.py`   |
| L2    | Input Filter      | Regex + Bedrock Guardrails injection detection | `src/guardrails/input_filter.py`   |
| L3    | Fallback Handler  | Exception handling, timeout, retry             | `src/guardrails/fallback.py`       |
| L4    | Tool Validator    | Allow-list, user isolation, param bounds       | `src/guardrails/tool_validator.py` |
| L5    | Output Filter     | PII redaction (email, phone, address)          | `src/guardrails/output_filter.py`  |
| L6    | Rate Limiter      | Request/token limits per user                  | `src/guardrails/rate_limiter.py`   |

### 8.2 Authentication & Authorization

- **Current:** No authentication (open access within cluster)
- **User Isolation:** Enforced by L4 guardrail (users can only access own cart)
- **IRSA:** Pod uses IAM role (no long-lived credentials)
- **Secrets:** DB password in K8s Secret (mounted as env var)

### 8.3 Data Protection

- **PII Redaction:** Email, phone, address patterns removed from outputs (L5)
- **No Logging of Secrets:** Credentials, tokens masked in logs
- **Session Encryption:** In-transit via Redis TLS (if enabled)
- **No Data Persistence:** User queries not stored beyond session TTL

### 8.4 Network Security

- **Service Type:** ClusterIP (not externally exposed)
- **Internal Communication:** K8s DNS resolution
- **gRPC TLS:** Optional (depends on cluster config)
- **Egress:** AWS Bedrock API (HTTPS), S3 (HTTPS)

---

## 9. Agent Tools

### 9.1 Tool Inventory (10 tools)

| Tool Name                  | Function                         | Backend                      | Write Permission Required       |
| -------------------------- | -------------------------------- | ---------------------------- | ------------------------------- |
| `search_products_v2`       | Hybrid search (SQL + RAG)        | PostgreSQL + Bedrock KB      | No                              |
| `get_categories`           | List product categories          | PostgreSQL                   | No                              |
| `get_all_products`         | Full product catalog (emergency) | PostgreSQL                   | No                              |
| `get_product_id`           | Resolve product ID from name     | PostgreSQL + SQLite fallback | No                              |
| `get_product_reviews_tool` | Fetch product reviews            | gRPC ProductReviewService    | No                              |
| `add_to_cart_tool`         | Add item to cart                 | gRPC CartService             | **Yes (requires confirmation)** |
| `get_cart_tool`            | View cart contents               | gRPC CartService             | No                              |
| `get_recommendations_tool` | Product recommendations          | gRPC RecommendationService   | No                              |
| `convert_currency_tool`    | Currency conversion              | gRPC CurrencyService         | No                              |
| `get_shipping_quote_tool`  | Shipping cost estimate           | HTTP ShippingService         | No                              |

### 9.2 Search Pipeline (Flow 1 + Flow 2 + Reranker)

**Flow 1: SQL Matching**

1. Entity Extraction (heuristic + LLM) → extract: category, brand, price range, keywords
2. SQL Query Builder → generate SQL with filters
3. PostgreSQL Executor → execute against `catalog.products`

**Flow 2: RAG Semantic Search**

1. Prompt Rewriter → optimize query for RAG
2. Bedrock KB Query → retrieve top-k documents
3. Product Resolver → map documents to product IDs

**Reranker:**

- Merge Flow 1 + Flow 2 results
- Deduplicate by product ID
- Cross-encoder scoring (relevance)
- Return top 5 products

---

## 10. Fallback & Resilience

### 10.1 Failure Modes

| Failure Scenario          | Behavior                                               | Fallback                             |
| ------------------------- | ------------------------------------------------------ | ------------------------------------ |
| Bedrock Model Unavailable | Retry 1x → Return fallback message                     | "Dịch vụ AI tạm thời không khả dụng" |
| Bedrock Timeout (>10s)    | Retry 1x → Return cached/generic response              | Cached previous result or fallback   |
| gRPC Service Down         | Tool failure logged → Agent attempts alternative tools | Inform user service unavailable      |
| PostgreSQL Down           | Search falls back to RAG-only                          | Bedrock KB search (no SQL)           |
| Valkey Down               | Session degrades to in-memory                          | No conversation history persistence  |
| Rate Limit Hit            | Return error response                                  | Client shows retry message           |

### 10.2 Guaranteed Response Time

- **Hard Timeout:** 15 seconds
- **No Hanging:** Always returns HTTP 200 (status in body)
- **Client UX:** Never blocks page load

---

## 11. Deployment Artifacts

### 11.1 Source Code

```
shopping-copilot/src/          # Python application
shopping-copilot/Dockerfile    # Container definition
shopping-copilot/requirements.txt  # Python dependencies
```

### 11.2 Kubernetes Manifests

```
shopping-copilot/contracts/k8s-serviceaccount.yaml  # IRSA ServiceAccount
shopping-copilot/contracts/k8s-deployment.yaml      # Deployment + Service + ConfigMap + Secret
```

### 11.3 Documentation

```
shopping-copilot/README.md                           # Architecture & usage
shopping-copilot/docs/ADR/                           # 7 architecture decisions
shopping-copilot/docs/ADR/ADR3-MANDATE-14-SUBMISSION.md  # AI trust & safety evidence
shopping-copilot/DEPLOYMENT-SPEC.md                  # This document
```

### 11.4 Testing

```
shopping-copilot/tests/                    # Test suite
shopping-copilot/tests/evaluation/         # Trust & Safety evaluation harness
shopping-copilot/server-test/              # Mock gRPC services for local development
```

---

## 12. Rollback Procedure

**Rollback Trigger Conditions:**

- Error rate > 10% sustained for 5 minutes
- P95 latency > 10s sustained
- Pod crash loop (restart count > 5)
- Bedrock quota exhaustion

**Rollback Commands:**

```bash
kubectl rollout undo deployment/shopping-copilot -n techx-tf3
kubectl rollout status deployment/shopping-copilot -n techx-tf3
```

**Post-Rollback Verification:**

- Health check returns 200
- Error rate < 1%
- Logs show successful startup

---

## 13. Known Limitations

| Limitation                          | Impact                                   | Mitigation                      |
| ----------------------------------- | ---------------------------------------- | ------------------------------- |
| Single region (ap-southeast-1)      | No multi-region failover                 | Bedrock has regional redundancy |
| No circuit breaker for gRPC         | Repeated calls to failed services        | Timeout + fallback (15s max)    |
| Session loss on Valkey restart      | Conversation history reset               | Valkey persistence enabled      |
| Rate limit per-service (not global) | User could bypass with multiple user_ids | Add WAF-level rate limiting     |
| No auth (within cluster)            | Any pod can call API                     | Rely on K8s network policies    |

---

## 14. Appendix

### 14.1 Python Dependencies (requirements.txt)

- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `boto3` - AWS SDK (Bedrock, S3)
- `grpcio` - gRPC client
- `psycopg2-binary` - PostgreSQL driver
- `redis` - Valkey/Redis client
- `pydantic` - Data validation
- `pyjwt` - JWT tokens for confirmation
- `scikit-learn` - ML utilities (embeddings, ranking)

### 14.2 Reference Documents

- **Project README:** `shopping-copilot/README.md`
- **MANDATE-14 Submission:** `docs/ADR/ADR3-MANDATE-14-SUBMISSION.md`
- **Migration Notes:** `MIGRATION_SUMMARY.md`

### 14.3 Version History

| Version | Date       | Changes                          |
| ------- | ---------- | -------------------------------- |
| 1.0.0   | 2026-07-26 | Initial deployment specification |

---

**Document Control:**  
Classification: Internal  
Distribution: CDO Team, AIO02 Team, Platform Engineering  
Review Cycle: Quarterly or on major version changes
