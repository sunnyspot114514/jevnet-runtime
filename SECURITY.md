# Security Policy

JevNet Runtime is a research prototype and developer preview. It should not be treated as a production security boundary without independent review and production-grade backends.

## Reporting a vulnerability

Please use GitHub's private **Security Advisory / Report a vulnerability** flow for issues that could enable:

- authorization bypass;
- Capability Manifest bypass or spoofing;
- duplicate external effects despite declared idempotency guarantees;
- stale-owner execution despite fencing;
- forged receipts becoming canonical;
- replay/recovery producing unauthorized state;
- secrets being committed or exposed.

Please do not publish an exploit as a public issue before coordinated review.

## Runtime assumptions

Security guarantees depend on the capabilities of the configured backend.

In particular, exactly-once-style recovery requires provider primitives such as idempotency or queryable durable receipts. The runtime cannot manufacture those guarantees when the external provider does not expose them.

The in-memory and SQLite/HTTP reference backends are for protocol testing, not production isolation.

The bundled HTTP provider/lease reference servers bind to loopback in the test harness and do not implement TLS, authentication, multi-tenant authorization, or rate limiting. Do not expose them directly to an untrusted network.
