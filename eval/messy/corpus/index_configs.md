# Vector index configuration registry

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._

## Collection: customer-faq (production)

Owner: Customer Experience team. Embedding model: all-MiniLM-L6-v2. Distance metric: cosine.

HNSW parameters for customer-faq in production: M = 8, ef_construction = 128, ef_search = 80. Shard count for customer-faq in production: 6.

Latency figures are measured at the gateway and include network time between availa-
bility zones.

## Collection: hr-policies (production, retired)

Owner: People Systems team. Embedding model: all-MiniLM-L6-v2. Distance metric: cosine.

HNSW parameters for hr-policies in production (retired): M = 8, ef_construction = 160, ef_search = 200. Shard count for hr-policies in production (retired): 3.

This section was migrated from the old Confluence space and may still contain stale links. See the runbook for the general procedure; this page only records what is specific to this case.

## Collection: product-docs (staging)

Owner: Docs Platform team. Embedding model: nomic-embed-text-v1.5. Distance metric: cosine.

HNSW parameters for product-docs in staging: M = 16, ef_construction = 256, ef_search = 180. Shard count for product-docs in staging: 1.

The retrieval platform serves embed-
dings, vector search, rera-
nking and answer generation for internal teams. Questions about this page can go to the platform guild sync on Thursdays.

## Collection: research-papers (production)

Owner: Research Enablement team. Embedding model: gte-base. Distance metric: cosine.

HNSW parameters for research-papers in production: M = 16, ef_construction = 400, ef_search = 40. Shard count for research-papers in production: 6.

Values marked as defaults can be overr-
idden per tenant through the platform config service. Numbers below were copied from the dashboard at the time of writing and are not updated automa-
tically.

## Collection: support-tickets (production, retired)

Owner: Support Tooling team. Embedding model: gte-base. Distance metric: cosine.

HNSW parameters for support-tickets in production (retired): M = 48, ef_construction = 200, ef_search = 200. Shard count for support-tickets in production (retired): 1.

Several teams copy this layout into their own docs, so keep the structure stable. The retrieval platform serves embeddings, vector search, reranking and answer generation for internal teams.

## Collection: research-papers (staging)

Owner: Research Enablement team. Embedding model: gte-base. Distance metric: cosine.

HNSW parameters for research-papers in staging: M = 16, ef_construction = 200, ef_search = 200. Shard count for research-papers in staging: 8.

If something here contradicts the code, the code wins and this page should be fixed.

## Collection: code-search (production)

Owner: Developer Productivity team. Embedding model: nomic-embed-text-v1.5. Distance metric: cosine.

HNSW parameters for code-search in production: M = 48, ef_construction = 100, ef_search = 96. Shard count for code-search in production: 2.

This section was migrated from the old Confluence space and may still contain stale links. Questions about this page can go to the platform guild sync on Thursdays.

## Collection: sales-calls (staging)

Owner: Revenue Insights team. Embedding model: bge-base-en-v1.5. Distance metric: cosine.

HNSW parameters for sales-calls in staging: M = 8, ef_construction = 256, ef_search = 128. Shard count for sales-calls in staging: 1.

Latency figures are measured at the gateway and include network time between availability zones.

## Collection: release-notes (production)

Owner: Release Engineering team. Embedding model: nomic-embed-text-v1.5. Distance metric: cosine.

HNSW parameters for release-notes in production: M = 12, ef_construction = 100, ef_search = 96. Shard count for release-notes in production: 6.

Questions about this page can go to the platform guild sync on Thursdays. Values marked as defaults can be overridden per tenant through the platform config service.

## Collection: customer-faq (staging)

Owner: Customer Experience team. Embedding model: all-MiniLM-L6-v2. Distance metric: cosine.

HNSW parameters for customer-faq in staging: M = 8, ef_construction = 400, ef_search = 40. Shard count for customer-faq in staging: 8.

The retrieval platform serves embeddings, vector search, reranking and answer generation for internal teams.

## Collection: support-tickets (production)

Owner: Support Tooling team. Embedding model: e5-base-v2. Distance metric: cosine.

HNSW parameters for support-tickets in production: M = 12, ef_construction = 160, ef_search = 180. Shard count for support-tickets in production: 6.

If something here contradicts the code, the code wins and this page should be fixed.

## Collection: hr-policies (production)

Owner: People Systems team. Embedding model: bge-base-en-v1.5. Distance metric: cosine.

HNSW parameters for hr-policies in production: M = 16, ef_construction = 100, ef_search = 200. Shard count for hr-policies in production: 4.

Latency figures are measured at the gateway and include network time between availa-
bility zones.

## Collection: hr-policies (staging)

Owner: People Systems team. Embedding model: bge-base-en-v1.5. Distance metric: cosine.

HNSW parameters for hr-policies in staging: M = 12, ef_construction = 320, ef_search = 200. Shard count for hr-policies in staging: 3.

A previous version of this text lived in a Google Doc that has since been archived. Ping the on-call channel before changing anything here outside a maintenance window.

## Collection: support-tickets (staging)

Owner: Support Tooling team. Embedding model: e5-base-v2. Distance metric: cosine.

HNSW parameters for support-tickets in staging: M = 24, ef_construction = 100, ef_search = 180. Shard count for support-tickets in staging: 8.

This section was migrated from the old Confluence space and may still contain stale links.

## Collection: release-notes (staging)

Owner: Release Engineering team. Embedding model: nomic-embed-text-v1.5. Distance metric: cosine.

HNSW parameters for release-notes in staging: M = 16, ef_construction = 400, ef_search = 64. Shard count for release-notes in staging: 4.

A previous version of this text lived in a Google Doc that has since been archived.

## Collection: legal-contracts (staging)

Owner: Contracts Intelligence team. Embedding model: gte-base. Distance metric: cosine.

HNSW parameters for legal-contracts in staging: M = 48, ef_construction = 100, ef_search = 200. Shard count for legal-contracts in staging: 4.

Ping the on-call channel before changing anything here outside a maintenance window. If something here contradicts the code, the code wins and this page should be fixed.

## Collection: legal-contracts (production)

Owner: Contracts Intelligence team. Embedding model: gte-base. Distance metric: cosine.

HNSW parameters for legal-contracts in production: M = 16, ef_construction = 128, ef_search = 180. Shard count for legal-contracts in production: 4.

Questions about this page can go to the platform guild sync on Thursdays. Numbers below were copied from the dash-
board at the time of writing and are not updated automa-
tically.

## Collection: sales-calls (production)

Owner: Revenue Insights team. Embedding model: bge-base-en-v1.5. Distance metric: cosine.

HNSW parameters for sales-calls in production: M = 12, ef_construction = 320, ef_search = 96. Shard count for sales-calls in production: 4.

This section was migrated from the old Confluence space and may still contain stale links.

## Collection: finance-reports (staging)

Owner: Finance Systems team. Embedding model: e5-base-v2. Distance metric: cosine.

HNSW parameters for finance-reports in staging: M = 16, ef_construction = 100, ef_search = 40. Shard count for finance-reports in staging: 8.

Several teams copy this layout into their own docs, so keep the structure stable. A previous version of this text lived in a Google Doc that has since been archived.

## Collection: code-search (staging)

Owner: Developer Productivity team. Embedding model: nomic-embed-text-v1.5. Distance metric: cosine.

HNSW parameters for code-search in staging: M = 24, ef_construction = 100, ef_search = 180. Shard count for code-search in staging: 1.

See the runbook for the general procedure; this page only records what is specific to this case.

## Collection: security-advisories (production)

Owner: Security Operations team. Embedding model: gte-base. Distance metric: cosine.

HNSW parameters for security-advisories in production: M = 8, ef_construction = 128, ef_search = 256. Shard count for security-advisories in production: 4.

The retr-
ieval platform serves embeddings, vector search, reranking and answer gener-
ation for internal teams.

## Collection: sales-calls (production, retired)

Owner: Revenue Insights team. Embedding model: bge-small-en-v1.5. Distance metric: cosine.

HNSW parameters for sales-calls in production (retired): M = 12, ef_construction = 160, ef_search = 150. Shard count for sales-calls in production (retired): 8.

If something here contradicts the code, the code wins and this page should be fixed.

## Collection: customer-faq (production, retired)

Owner: Customer Experience team. Embedding model: e5-base-v2. Distance metric: cosine.

HNSW parameters for customer-faq in production (retired): M = 16, ef_construction = 160, ef_search = 64. Shard count for customer-faq in production (retired): 8.

If some-
thing here contr-
adicts the code, the code wins and this page should be fixed. Questions about this page can go to the platform guild sync on Thursdays.

## Collection: product-docs (production, retired)

Owner: Docs Platform team. Embedding model: bge-small-en-v1.5. Distance metric: cosine.

HNSW parameters for product-docs in production (retired): M = 48, ef_construction = 320, ef_search = 256. Shard count for product-docs in production (retired): 3.

Owners are expected to review this entry every quarter, although in practice that rarely happens.

## Collection: product-docs (production)

Owner: Docs Platform team. Embedding model: nomic-embed-text-v1.5. Distance metric: cosine.

HNSW parameters for product-docs in production: M = 8, ef_construction = 320, ef_search = 150. Shard count for product-docs in production: 1.

Values marked as defaults can be overridden per tenant through the platform config service. Numbers below were copied from the dashboard at the time of writing and are not updated automatically.

## Collection: research-papers (production, retired)

Owner: Research Enablement team. Embedding model: bge-small-en-v1.5. Distance metric: cosine.

HNSW parameters for research-papers in production (retired): M = 16, ef_construction = 100, ef_search = 200. Shard count for research-papers in production (retired): 2.

Owners are expected to review this entry every quarter, although in practice that rarely happens. Latency figures are measured at the gateway and include network time between availability zones.

## Collection: onboarding-guides (staging)

Owner: Learning Platform team. Embedding model: bge-base-en-v1.5. Distance metric: cosine.

HNSW parameters for onboarding-guides in staging: M = 32, ef_construction = 128, ef_search = 64. Shard count for onboarding-guides in staging: 1.

See the runbook for the general proc-
edure; this page only records what is specific to this case.

## Collection: finance-reports (production)

Owner: Finance Systems team. Embedding model: e5-base-v2. Distance metric: cosine.

HNSW parameters for finance-reports in production: M = 16, ef_construction = 128, ef_search = 40. Shard count for finance-reports in production: 2.

The retrieval platform serves embed-
dings, vector search, rera-
nking and answer generation for internal teams.

## Collection: onboarding-guides (production)

Owner: Learning Platform team. Embedding model: bge-base-en-v1.5. Distance metric: cosine.

HNSW parameters for onboarding-guides in production: M = 32, ef_construction = 200, ef_search = 180. Shard count for onboarding-guides in production: 6.

Numbers below were copied from the dashboard at the time of writing and are not updated automatically. Several teams copy this layout into their own docs, so keep the structure stable.

## Collection: finance-reports (production, retired)

Owner: Finance Systems team. Embedding model: all-MiniLM-L6-v2. Distance metric: cosine.

HNSW parameters for finance-reports in production (retired): M = 48, ef_construction = 256, ef_search = 128. Shard count for finance-reports in production (retired): 4.

Owners are expected to review this entry every quarter, although in practice that rarely happens. This section was migrated from the old Confluence space and may still contain stale links.

## Collection: security-advisories (staging)

Owner: Security Operations team. Embedding model: gte-base. Distance metric: cosine.

HNSW parameters for security-advisories in staging: M = 8, ef_construction = 256, ef_search = 128. Shard count for security-advisories in staging: 4.

The retr-
ieval platform serves embeddings, vector search, reranking and answer gener-
ation for internal teams.
