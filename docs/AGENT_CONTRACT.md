# The agent contract (v2027.1)

> Rendered from `aughor/kernel/contract.py`; `tests/unit/test_agent_contract.py` holds this file equal to the code. Edit the module, then regenerate with `uv run python -m aughor.kernel.contract`.

An agent is defined by the kind of entry it is licensed to book in the ledger, not by the name it is given. An outside agent takes the same duties through the MCP server and the ledger API, under a service principal, held to the same contract as the platform's own agents — which are held to it first.

## The seven duties

| Duty | Books | Proposes | Today | Why it exists |
|---|---|---|---|---|
| **Observe** | observation, reading | monitor | Explorer, Watcher | somebody has to look where nobody asked |
| **Inquire** | hypothesis, finding | — | Analyst (SQL Engineer, Narrator, Orchestrator inside it) | explanation is a search over causes |
| **Challenge** | cause | refutation of a hypothesis | Verifier; the skeptic step and its causal_checks record | a claim rises a tier only after an attempt to break it — by a different binding where the install has two |
| **Forecast** | prediction | scenario | the scenario ladder's methods (code); no model forecasts | a system that never commits to an expectation can never be scored |
| **Steward** | definition, said | duplicate, coverage gap | Curator, the business explorer | the model of the business goes stale; people confirm what a steward proposes |
| **Operate** | action | preview | the executor, under a person's approval or a standing grant | closes the loop |
| **Deliver** | departure | — | Responder, Briefer | attention is spent at this door and nowhere else |

## The typed verdicts a run ends in

Every run books one, never an empty result: `answered` · `contradicted` · `no_data` · `no_definition` · `withheld` · `out_of_budget` · `tool_failed`.

## What an entry must carry

- **kinds**: `observation`, `finding`, `reading`, `definition`, `hypothesis`, `prediction`, `said`, `cause`
- **tiers** (the authority ladder, minus the one that is not a claim): `measured`, `approved`, `declared`, `mined`, `said`
- **statuses**: `Final`, `Provisional`, `To date`
- **about**: `object`, `segment`, `type`, `connection`, `domain`, `organisation`
- **author kinds**: `person`, `agent`, `system`
- **warrants**: `run`, `document`, `attestation`, `claim`
- **fields an author writes**: `kind`, `about`, `statement`, `tier`, `status`, `as_of`, `valid_from`, `valid_until`, `warrants`, `falsifier`, `next_check`, `owner`, `author`, `author_kind`, `definition_version`, `state`, `extra`
- **filled by the ledger, never by an author**: `id`, `key`, `version`, `recorded_at`, `supersedes`, `superseded_by`, `confidence`
- **states**: hypothesis open · supported · refuted · abandoned; prediction open · scored

### The laws at the door

1. No fact without a warrant: a claim at tier `measured` carries a `run` warrant (the receipt of the statement that produced it); `approved` and `declared` need a person as author or an `attestation` warrant. A tier a claim cannot warrant is refused, never quietly lowered.
2. No model-authored fact: tier `inferred` is not a claim. What a model concludes without a run behind it is a `hypothesis` at tier `said`, and stays one until a run or a person raises it.
3. Confidence is counted or absent: no author sets it. It is filled on read as the hit rate of the claim's reference class with its n, or left empty.
4. The ledger API refuses a claim that names no warrant at all, whatever its tier: an outside author's claim enters through the one door, with what entitles it to be relied on.

## Who may book

Principal kinds: person (user:<id>); agent (agent:<id>, the platform's own); service (service:<name>, an outside vendor's); group (group:<id>).

A **service principal** is:

- minted by: a person, at POST /ledger/v1/principals/service — the key is returned once, stored hashed
- presented as: `X-Aughor-Service`: the service name, `X-Aughor-Service-Key`: the key
- held to: the organisation's agent policy (read · run · act, connection and tool allowlists), audited as an agent
- author: every entry it books carries `service:<name>` as author with author_kind `agent`
- scored: like every author: by what became of its entries (GET /ledger/v1/principals/{principal}/record)

## Levels

The agent policy: `read` · `run` · `act` (default `run`). Read: look things up. Run: start work or book an entry with its warrant. Act: change something outside the conversation — given only by a person.

The authority ladder for actions: L0 observe · L1 recommend · L2 prepare · L3 execute with approval · L4 execute within policy · L5 autonomous. the lower of the ceiling a person set and what the record earned; L4 only on a graduation receipt; an irreversible action never passes L3; L5 only on an L5 receipt a person books on a long L4 record inside a mission whose ceiling sets it, and the agent then chooses among the declared actions at L5 by their measured effect on the mission's objective, one action per review period; graduation needs 5 verified executions.

## The doors

The ledger API, under `/ledger/v1`:

- GET /contract — this contract
- POST /claims — post a claim with its warrant (run)
- GET /claims?as_of= — claims as recorded on a date
- GET /claims/{id} · GET /claims/{id}/versions
- GET /restatements?since= — what changed since a cursor
- POST /subscriptions · GET /subscriptions · DELETE /subscriptions/{id} — webhooks for events out
- GET /events?kind=&since_seq= · GET /events/catalogue
- GET /export — the ledger as JSON lines
- GET /principals/{principal}/record
- GET /methods · POST /methods — the method interface
- GET /aggregates · POST /aggregates/export

The MCP server (`aughor.mcp.server`) adds `read_contract`, `post_claim`, `read_claims`, `read_restatements`; the same policy and audit as every other tool; no raw query tool, by design.

What no door offers: a write path around the warrant; anything that runs inside the platform's process; anything that grades itself.

## How an agent is scored

an agent's score is a count of what became of its entries, never a model's opinion.

- **observation**: restated or held on re-check
- **hypothesis**: supported · refuted · abandoned
- **finding**: survived a challenge and a person's verdict
- **prediction**: inside its band at settle
- **action**: verification passed and outcome inside expectation
- **departure**: opened and not marked wrong

Reference classes counted today: answers re-checked, stated causes challenged, predictions scored; a hit rate is shown from n = 30. Interval coverage by method, metric and author (get /record/calibration). The cost measure is cost per warranted claim.

## Refusals

| Code | Meaning |
|---|---|
| `AGENT_LEVEL_DENIED` | the policy's level is below what the tool or route needs |
| `AGENT_TOOL_DENIED` | the tool is not on the organisation's allowlist |
| `AGENT_CONNECTION_DENIED` | the connection is not on the organisation's allowlist |
| `AGENT_POLICY_NOT_SELF_SET` | an agent tried to set its own policy |
| `CLAIM_REFUSED` | the ledger's door said no: a tier without its warrant, a model-authored fact, a stated confidence, a claim with no warrant at all, or a restatement of another author's claim |
| `SERVICE_KEY_REFUSED` | a service header was presented and did not match a minted, unrevoked key |
