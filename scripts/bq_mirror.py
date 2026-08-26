"""Mirror a BigQuery dataset into your own project with free copy jobs.

The live-data pilot needs an externally-updated database that Aughor's catalog
can actually see. Public datasets live in projects we cannot run jobs in, so the
catalog is blind to them; this script is the daily ETL that lands a copy in a
project Aughor is connected to. It is deliberately NOT part of the platform —
it plays the role of the customer's pipeline.

Copy jobs move tables without scanning bytes, so a run costs nothing against
the query free tier. Each table is truncated and replaced, which also makes the
run idempotent.

Usage:
  python scripts/bq_mirror.py --project MY_PROJECT \
      --credentials ~/.config/aughor/bq-sa.json \
      [--source bigquery-public-data.thelook_ecommerce] [--dest thelook]

The credentials flag is optional; without it the client uses Application
Default Credentials. The service account needs BigQuery Data Editor in the
destination project (writing) on top of Job User (running the copy jobs).
"""

from __future__ import annotations

import argparse
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True, help="destination (and billing) project id")
    ap.add_argument("--source", default="bigquery-public-data.thelook_ecommerce",
                    help="source dataset as project.dataset")
    ap.add_argument("--dest", default="thelook", help="destination dataset name")
    ap.add_argument("--credentials", default=None,
                    help="path to a service-account JSON; omit to use ADC")
    ap.add_argument("--location", default="US",
                    help="destination dataset location; must match the source")
    args = ap.parse_args()

    from google.cloud import bigquery

    if args.credentials:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            args.credentials, scopes=["https://www.googleapis.com/auth/bigquery"])
        client = bigquery.Client(project=args.project, credentials=creds)
    else:
        client = bigquery.Client(project=args.project)

    dest_ref = f"{args.project}.{args.dest}"
    dataset = bigquery.Dataset(dest_ref)
    dataset.location = args.location
    client.create_dataset(dataset, exists_ok=True)

    tables = list(client.list_tables(args.source))
    if not tables:
        print(f"source {args.source} has no tables", file=sys.stderr)
        return 1

    started = time.time()
    total_rows = 0
    for t in tables:
        src = f"{args.source}.{t.table_id}"
        dst = f"{dest_ref}.{t.table_id}"
        job = client.copy_table(
            src, dst,
            job_config=bigquery.CopyJobConfig(write_disposition="WRITE_TRUNCATE"),
        )
        job.result()
        rows = client.get_table(dst).num_rows
        total_rows += rows
        print(f"  {t.table_id}: {rows:,} rows")

    print(f"mirrored {len(tables)} tables, {total_rows:,} rows "
          f"into {dest_ref} in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
