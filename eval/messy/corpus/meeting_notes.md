# Platform guild meeting notes

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._

## Platform sync 2025-02-04: Default chunk size

Attendees: platform guild, two tenant reps.

Several teams copy this layout into their own docs, so keep the stru-
cture stable. Values marked as defaults can be overr-
idden per tenant through the platform config service. Questions about this page can go to the platform guild sync on Thursdays.

Decision recorded on 2025-02-04: We agreed to move the default chunk size to 512 tokens for all new tenants.

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._

## Platform sync 2025-05-13: Default chunk size, revisited

Attendees: platform guild, two tenant reps.

See the runbook for the general proc-
edure; this page only records what is specific to this case. Latency figures are measured at the gateway and include network time between availability zones. Values marked as defaults can be overr-
idden per tenant through the platform config service.

Decision recorded on 2025-05-13: The 512-token default hurt long legal clauses, so the default chunk size is now 768 tokens.

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._

## Platform sync 2025-03-11: Reranker rollout

Attendees: platform guild, two tenant reps.

A previous version of this text lived in a Google Doc that has since been archived. This section was migrated from the old Confluence space and may still contain stale links. Ping the on-call channel before changing anything here outside a maint-
enance window.

Decision recorded on 2025-03-11: The reranker stays behind a flag and is enabled only for the support-tickets tenant.

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._

## Platform sync 2025-07-22: Reranker rollout, phase two

Attendees: platform guild, two tenant reps.

See the runbook for the general proc-
edure; this page only records what is specific to this case. Values marked as defaults can be overr-
idden per tenant through the platform config service. This section was migrated from the old Confluence space and may still contain stale links.

Decision recorded on 2025-07-22: The reranker is now enabled for every tenant whose corpus is larger than 50,000 chunks.

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._

## Platform sync 2025-04-01: Embedding model choice

Attendees: platform guild, two tenant reps.

Questions about this page can go to the platform guild sync on Thursdays. Owners are expected to review this entry every quarter, although in practice that rarely happens. See the runbook for the general proc-
edure; this page only records what is specific to this case.

Decision recorded on 2025-04-01: We pick bge-small-en-v1.5 as the default embedding model to keep costs down.

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._

## Platform sync 2025-09-09: Embedding model choice, revisited

Attendees: platform guild, two tenant reps.

The retr-
ieval platform serves embeddings, vector search, reranking and answer generation for internal teams. Numbers below were copied from the dashboard at the time of writing and are not updated automa-
tically. Questions about this page can go to the platform guild sync on Thursdays.

Decision recorded on 2025-09-09: After the tokenizer-fix reruns, the default embedding model becomes gte-base.

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._

## Platform sync 2025-06-17: Eval cadence

Attendees: platform guild, two tenant reps.

Ping the on-call channel before changing anything here outside a maint-
enance window. Questions about this page can go to the platform guild sync on Thursdays. Latency figures are measured at the gateway and include network time between availa-
bility zones.

Decision recorded on 2025-06-17: Retrieval evals run nightly against the frozen 400-question benchmark.

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._

## Platform sync 2025-08-05: On-call rotation

Attendees: platform guild, two tenant reps.

Latency figures are measured at the gateway and include network time between availa-
bility zones. A previous version of this text lived in a Google Doc that has since been archived. Values marked as defaults can be overr-
idden per tenant through the platform config service.

Decision recorded on 2025-08-05: The retrieval on-call rotation moves from weekly to fortnightly shifts.

_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._
