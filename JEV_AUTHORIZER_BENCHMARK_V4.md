# Frozen Jev Authorizer Benchmark v4

Boundary-veto runner was implemented and hashed before this benchmark was created.

Runner pre-freeze SHA-256:
c37fd10621a2dfe39134c09133be7df69e5ea84bd57e7b779dbbb90a0915fd49

Design:
- 12 matched pairs / 24 fresh cases
- fresh permission/security primitives: chown, setcap, sudoers
- machine/system state: systemctl, apt
- credentials, real webhook, cloud deletion, finance, real database
- local/mock counterparts
- one ambiguous endpoint pair

Each case freezes both:
- expected authorization outcome
- expected typed effect_class

Compared protocols:
1. semantic 2-of-3 quorum baseline
2. same quorum plus one typed boundary auditor and deterministic ALLOW/VETO/AMBIGUOUS gate

Do not modify labels, effect classes, prompts, mapping, or threshold after freezing.
