# Retrieval platform incident postmortems

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._

## Postmortem INC-2198: embedding-gateway degradation

Date: 2025-03-25. Severity: SEV-3. Service: embedding-gateway.

Summary: the embedding-gateway dropped documents whose PDFs contained only scanned images. Customer impact lasted 62 minutes. Remediation: the team routed image-only PDFs through OCR.

Several teams copy this layout into their own docs, so keep the structure stable. The retrieval platform serves embeddings, vector search, reranking and answer generation for internal teams.

## Postmortem INC-2779: vector-store degradation

Date: 2025-05-24. Severity: SEV-2. Service: vector-store.

Summary: the vector-store throttled every tenant after a single tenant flooded the queue. Customer impact lasted 137 minutes. Remediation: the team added per-tenant rate limits.

A previous version of this text lived in a Google Doc that has since been archived.

## Postmortem INC-2039: ingest-worker degradation

Date: 2025-11-02. Severity: SEV-3. Service: ingest-worker.

Summary: the ingest-worker double-indexed documents after a retry storm. Customer impact lasted 203 minutes. Remediation: the team made ingestion idempotent by content hash.

Several teams copy this layout into their own docs, so keep the structure stable. This section was migrated from the old Confluence space and may still contain stale links.

## Postmortem INC-2156: retrieval-api degradation

Date: 2025-03-27. Severity: SEV-3. Service: retrieval-api.

Summary: the retrieval-api ran out of disk space because old index snapshots were never pruned. Customer impact lasted 95 minutes. Remediation: the team added a snapshot retention job.

Several teams copy this layout into their own docs, so keep the stru-
cture stable.

## Postmortem INC-2022: ingest-worker degradation

Date: 2025-01-20. Severity: SEV-2. Service: ingest-worker.

Summary: the ingest-worker deadlocked during a schema migration of the metadata table. Customer impact lasted 212 minutes. Remediation: the team split the migration into online steps.

Owners are expected to review this entry every quarter, although in practice that rarely happens. See the runbook for the general procedure; this page only records what is specific to this case.

## Postmortem INC-2536: vector-store degradation

Date: 2025-01-10. Severity: SEV-2. Service: vector-store.

Summary: the vector-store ranked results randomly after a model file was half-downloaded. Customer impact lasted 77 minutes. Remediation: the team verified model checksums on load.

Values marked as defaults can be overr-
idden per tenant through the platform config service. If some-
thing here contradicts the code, the code wins and this page should be fixed.

## Postmortem INC-2560: embedding-gateway degradation

Date: 2025-09-12. Severity: SEV-3. Service: embedding-gateway.

Summary: the embedding-gateway leaked memory in the tokenizer cache under long queries. Customer impact lasted 232 minutes. Remediation: the team bounded the tokenizer cache.

Numbers below were copied from the dashboard at the time of writing and are not updated automatically. Ping the on-call channel before changing anything here outside a maintenance window.

## Postmortem INC-2271: embedding-gateway degradation

Date: 2025-05-22. Severity: SEV-3. Service: embedding-gateway.

Summary: the embedding-gateway hit GPU out-of-memory errors when batch size was doubled. Customer impact lasted 99 minutes. Remediation: the team reverted the batch size and added a memory alarm.

Owners are expected to review this entry every quarter, although in practice that rarely happens.

## Postmortem INC-2661: retrieval-api degradation

Date: 2025-08-28. Severity: SEV-1. Service: retrieval-api.

Summary: the retrieval-api lost writes when two leaders were elected during a network partition. Customer impact lasted 204 minutes. Remediation: the team moved to a quorum-based lease.

A previous version of this text lived in a Google Doc that has since been archived. Several teams copy this layout into their own docs, so keep the stru-
cture stable.

## Postmortem INC-2396: reranker-svc degradation

Date: 2025-02-10. Severity: SEV-2. Service: reranker-svc.

Summary: the reranker-svc returned empty results when a shard failed health checks silently. Customer impact lasted 117 minutes. Remediation: the team made shard failures fail the query loudly.

The retrieval platform serves embeddings, vector search, reranking and answer generation for internal teams. Values marked as defaults can be overridden per tenant through the platform config service.

## Postmortem INC-2817: vector-store degradation

Date: 2025-01-11. Severity: SEV-2. Service: vector-store.

Summary: the vector-store served stale results because the cache TTL was set to a week. Customer impact lasted 187 minutes. Remediation: the team reduced the cache TTL to ten minutes.

A previous version of this text lived in a Google Doc that has since been archived. Owners are expected to review this entry every quarter, although in practice that rarely happens.

## Postmortem INC-2131: reranker-svc degradation

Date: 2025-06-28. Severity: SEV-1. Service: reranker-svc.

Summary: the reranker-svc loaded a cross-encoder checkpoint with the wrong tokenizer. Customer impact lasted 184 minutes. Remediation: the team pinned tokenizer files next to the model.

Values marked as defaults can be overridden per tenant through the platform config service.

## Postmortem INC-2204: retrieval-api degradation

Date: 2025-06-22. Severity: SEV-3. Service: retrieval-api.

Summary: the retrieval-api crashed on startup because an environment variable was renamed. Customer impact lasted 81 minutes. Remediation: the team validated config at boot.

See the runbook for the general procedure; this page only records what is specific to this case. Latency figures are measured at the gateway and include network time between availability zones.

## Postmortem INC-2047: reranker-svc degradation

Date: 2025-02-01. Severity: SEV-3. Service: reranker-svc.

Summary: the reranker-svc timed out because ef_search was raised to 1,000 in production. Customer impact lasted 153 minutes. Remediation: the team restored ef_search and added a config review.

If something here contradicts the code, the code wins and this page should be fixed. Values marked as defaults can be overridden per tenant through the platform config service.

## Postmortem INC-2672: ingest-worker degradation

Date: 2025-07-12. Severity: SEV-2. Service: ingest-worker.

Summary: the ingest-worker exhausted its connection pool after a client stopped closing sessions. Customer impact lasted 231 minutes. Remediation: the team capped connections per client.

Several teams copy this layout into their own docs, so keep the stru-
cture stable.

## Postmortem INC-2228: retrieval-api degradation

Date: 2025-07-26. Severity: SEV-2. Service: retrieval-api.

Summary: the retrieval-api rejected requests after a TLS certificate expired. Customer impact lasted 210 minutes. Remediation: the team automated certificate renewal.

Ping the on-call channel before changing anything here outside a maint-
enance window.
