# CLAUDE.md

## REVIEW COMPLETION CONTRACT

For any task that:
- performs a review,
- validates a change,
- produces findings,
- or evaluates implementation quality,

the task is NOT COMPLETE until:

1. a matching `*_review.adoc` artifact exists,
2. the review artifact is committed separately from follow-up fixes,
3. validation commands are documented,
4. findings/disposition/residual risks are recorded.

Agents must not treat review summaries in chat output as sufficient replacement
for the review artifact.

## Further instructions


First look for clone specific ai instructions. These are gitignored, but may be around in the project root under the pattern 
clone_specific_ai_instruction.*

Entry point only. Canonical AI and repo-committing guidance lives in
`docs/ai_info/_ai_info.adoc`.

Use that document as the source of truth, then check the active FTR/review note
and nearby architecture docs before changing anything.
