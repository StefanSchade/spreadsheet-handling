# CLAUDE.md

First look for clone specific ai instructions. These are gitignored, but may be around in the project root under the pattern 
clone_specific_ai_instruction.*

Entry point only. Canonical AI and repo-committing guidance lives in
`docs/ai_info/_ai_info.adoc`.

Use that document as the source of truth, then check the active FTR/review note
and nearby architecture docs before changing anything.

Review discipline: if a task is a review or produces findings / validation
work, create or update the matching `*_review.adoc` artifact, commit that
review artifact separately from any follow-up fix, summarize the validation
commands you ran, and record the disposition plus any residual risks.
