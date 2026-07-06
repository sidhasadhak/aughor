# DRAFT — Spider2 Secure Data Share request (DO NOT SEND without explicit approval)

*WS5-P0 deliverable (2026-07-06). Self-hosting the Spider2-Snow data in our own Snowflake
account removes the shared participant warehouse's queueing — the June campaign's ~2.5h
throughput wall. Requires our Snowflake account to be in AWS us-west-2 (Oregon). The
maintainers' documented turnaround is ~12h. Source: xlang-ai/Spider2 README News 2025-10-29 +
`assets/Spider2_Data_Host.md` + the `lfy79001/spider2-data-share` tooling repo.*

**To:** lfy79001@gmail.com
**Subject:** Spider 2.0 — Secure Data Share request (self-hosted evaluation)

Hi Fangyu,

We are evaluating Spider 2.0-Snow / the Snowflake-hosted portion of Spider 2.0-Lite and
would like to self-host the data via the Snowflake Secure Data Share
(SPIDER2_MERGED_250922), per the October 29 update, to avoid loading the shared
participant warehouse.

Our Snowflake account identifier (AWS us-west-2 / Oregon): `<ACCOUNT_IDENTIFIER_HERE>`

We understand the 18 non-`sf_` examples are not shareable and will run those against the
public participant account. Thank you for maintaining the benchmark!

Best,
`<NAME>` — Aughor

---
*Before sending: fill in the account identifier (must be us-west-2 — create the account in
that region if needed), and confirm the user has explicitly approved sending.*
