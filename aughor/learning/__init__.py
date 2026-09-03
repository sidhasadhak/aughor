"""MI-3 — the dataset plane: graded experience becomes a versioned, provenanced corpus.

§7's law generalised: a capability ships when something consumes it; **data ships when
something GRADES it**. MI-1 made guard verdicts durable and MI-2 made a graded run's
evidence survive retention. This is where those rows become something a trainer can read:
content-addressed snapshots, versioned dataset nodes with clone lineage, and a lineage
table that walks a dataset back to the runs and verdicts that fed it.

Schema ported from TangleML (§4.5 — PORT the schema, REFUSE the runtime), which is worth
restating because the shape is not obvious:

* **`dataset_data`** is content-addressed and separate from `dataset_node`. Two dataset
  versions with identical bytes reference ONE blob, and purging bytes (a retention or
  privacy act) leaves the node and its lineage standing — provenance outlives the payload,
  which is exactly what an auditor needs and what a naive `datasets(id, blob)` table
  cannot give.
* **`dataset_node`** carries `parent_id`, so a filtered or re-graded corpus records what it
  was cloned FROM rather than pretending to be new.
* **`dataset_lineage`** is the answer to "what produced this row" — the question MI-4 must
  answer about any adapter it promotes, and the reason the whole arc is auditable.
"""
