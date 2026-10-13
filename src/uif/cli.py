"""uif command line.

  uif synth  --out synthetic --n 12          make labeled synthetic documents
  uif run    synthetic/merchant --source merchant --system portal
  uif run    synthetic/internal --source internal --system case_mgmt
  uif eval   synthetic                       score the pipeline against labels
  uif review                                 show the open review queue
  uif sql    "select * from mart_underwriting_variance"
  uif step   extract --doc-id <id>           run one step (what ECS tasks call)
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _ctx(args) -> "Context":  # noqa: F821
    from uif.context import Context

    overrides = {}
    if getattr(args, "llm", None):
        overrides["llm.kind"] = args.llm
    return Context.from_config(getattr(args, "runtime", None), overrides)


def cmd_run(args) -> int:
    from uif.runner import process_path

    ctx = _ctx(args)
    runs = process_path(ctx, args.path, args.source, args.system, args.submitter, args.force)
    bad = 0
    for r in runs:
        last = r.results[-1]
        flag = "ok " if r.ok else "ERR"
        bad += not r.ok
        print(f"{flag} {r.doc_id}  {r.file_name:<40} {last.step:<9} {last.detail or ''}")
        if args.verbose:
            for s in r.results:
                print(f"      {s.step:<9} ok={s.ok} {s.detail or ''}")
    print(f"\n{len(runs)} document(s), {bad} with errors")
    return 1 if bad else 0


def cmd_step(args) -> int:
    from uif.steps import STEPS

    doc_id = args.doc_id or os.environ.get("DOC_ID")
    if not doc_id:
        print("doc id required (--doc-id or DOC_ID)", file=sys.stderr)
        return 2
    res = STEPS[args.name](_ctx(args), doc_id)
    print(res.model_dump_json())
    return 0 if res.ok or res.halt else 1


def cmd_synth(args) -> int:
    from uif.synth import generate

    summary = generate(args.out, n=args.n, seed=args.seed)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_eval(args) -> int:
    from uif.evals import evaluate, gate

    ctx = _ctx(args)
    report = evaluate(ctx, args.path, run_pipeline=not args.no_run)
    print(json.dumps(report, indent=2))
    failures = gate(report)
    for f in failures:
        print(f"GATE FAILED: {f}", file=sys.stderr)
    return 1 if failures else 0


def cmd_review(args) -> int:
    ctx = _ctx(args)
    rows = ctx.providers.warehouse.query(
        "select task_id, file_name, doc_type, reason from v_review_queue limit ?", [args.limit])
    for r in rows:
        print(" | ".join(str(x) for x in r))
    print(f"{len(rows)} open task(s) shown")
    return 0


def cmd_sql(args) -> int:
    ctx = _ctx(args)
    con = ctx.providers.warehouse.con
    cur = con.execute(args.query)
    cols = [d[0] for d in cur.description]
    print(" | ".join(cols))
    for row in cur.fetchall():
        print(" | ".join("" if v is None else str(v) for v in row))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="uif", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runtime", choices=["local", "aws"], default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="process a file or folder")
    r.add_argument("path")
    r.add_argument("--source", required=True, choices=["merchant", "external", "internal"])
    r.add_argument("--system", default="manual")
    r.add_argument("--submitter")
    r.add_argument("--llm", choices=["rules", "ollama", "bedrock"])
    r.add_argument("--force", action="store_true", help="reprocess duplicates")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("step", help="run one step for one document")
    s.add_argument("name")
    s.add_argument("--doc-id")
    s.add_argument("--llm", choices=["rules", "ollama", "bedrock"])
    s.set_defaults(fn=cmd_step)

    g = sub.add_parser("synth", help="generate labeled synthetic documents")
    g.add_argument("--out", default="synthetic")
    g.add_argument("--n", type=int, default=12)
    g.add_argument("--seed", type=int, default=7)
    g.set_defaults(fn=cmd_synth)

    e = sub.add_parser("eval", help="score against golden labels")
    e.add_argument("path", nargs="?", default="synthetic")
    e.add_argument("--llm", choices=["rules", "ollama", "bedrock"])
    e.add_argument("--no-run", action="store_true", help="score what is already processed")
    e.set_defaults(fn=cmd_eval)

    v = sub.add_parser("review", help="open review queue")
    v.add_argument("--limit", type=int, default=50)
    v.set_defaults(fn=cmd_review)

    q = sub.add_parser("sql", help="query the local warehouse")
    q.add_argument("query")
    q.set_defaults(fn=cmd_sql)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
