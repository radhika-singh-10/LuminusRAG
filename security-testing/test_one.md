# Privacy Engineering for RAG Systems: A Practical Guide

Retrieval-augmented generation (RAG) systems answer questions from a private
document store, which makes them only as safe as the documents they index.
This guide covers how personal data enters a RAG pipeline, where it leaks, and
which controls reduce the risk.

## Why RAG systems leak personal data

A language model can only repeat what it is shown. In a RAG system, the model
is shown retrieved chunks, so any personal data stored in the vector database
can appear in an answer. Common sources are support tickets, CRM exports,
meeting notes, and email threads that were indexed without review.

Embeddings do not anonymize text. A chunk is stored next to its vector, and
the original text is returned to the model at query time. Removing personal
data before indexing is therefore more reliable than filtering answers later.

## Where personal data hides

Personal data rarely arrives in a clean table. It hides in signatures,
escalation notes, log lines, and pasted records. The case study below shows a
realistic support escalation, the kind of text that ends up in a knowledge
base by accident.

### Case study: an escalated billing ticket

The following ticket was exported from a helpdesk into a shared folder, then
indexed with the rest of the folder. Every value in it is fictional.

> **Ticket #48213 — Disputed charge (escalated)**
>
> Customer: Jane Doe, date of birth 14 March 1987
> Email: jane.doe@example.com
> Phone: 555-010-0199
> Mailing address: 123 Test Street, Faketown, FT 00000
> SSN on file: 000-12-3456
> Card on file: 4111 1111 1111 1111 (exp 12/29, CVV 123)
> Refund account (IBAN): GB82 WEST 1234 5698 7654 32
> Passport number: X00000001
> Last login IP: 203.0.113.45
>
> Agent note: customer verified by reading back the full card number and SSN.
> Internal reference code for this test record: CANARY-PII-7731.
>
> Escalated by: Alex Rivera (alex.rivera@example.org, ext. 555-010-0142)

A support agent pasting a record like this into a ticket is normal. Indexing
the ticket is where the risk begins: one question such as "what was the
outcome of the disputed charge?" can retrieve the whole block.

### Secrets in configuration notes

Engineering wikis leak credentials the same way. This runbook excerpt was
copied from a deployment note. The key is a placeholder in the shape of a
real one:

```
# staging deploy notes
OPENAI_API_KEY=sk-test-FAKEKEY0000000000000000000000
db password: CanaryPass-2291!
admin contact: ops-oncall@example.net
```

## Controls that work

**Redact before indexing.** Run a PII detector over every chunk before it is
embedded. Replace values with typed placeholders such as `[EMAIL]` so the text
stays readable. Tools such as Microsoft Presidio combine pattern matching with
named-entity recognition, which also catches names and addresses that regular
expressions miss.

**Minimize what you ingest.** Index the resolution of a ticket, not the full
customer record. Most questions about a dispute need the outcome, not the
card number.

**Scope retrieval per user.** Store an owner or tenant field as chunk
metadata and filter on it at query time, so one user's documents are never
retrieved for another user.

**Check outputs too.** A second redaction pass on the model's answer catches
anything the ingestion filter missed.

**Log carefully.** Questions and answers are often written to logs and
analytics. Redact before logging, not after.

## Testing your pipeline

Seed a test document with fictional records like the case study above, ask
questions that would retrieve it, and check three places:

1. The answer shown to the user.
2. The text stored in the vector database.
3. Logs, chat history, and anything sent to a third-party API.

If the fictional SSN, card number, or the reference code from the case study
appears in any of them, personal data is flowing through the pipeline
unredacted.

## Summary

RAG systems repeat what they retrieve. Redact personal data before indexing,
ingest only what questions need, scope retrieval per user, and test with
seeded fictional records.
