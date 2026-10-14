"""uif command line.

  uif synth  --out synthetic --n 12          make labeled synthetic documents
  uif run    synthetic/merchant --source merchant --system portal
  uif run    synthetic/internal --source internal --system case_mgmt
  uif eval   synthetic                       score the pipeline against labels
  uif review                                 show the open review queue
  uif sql    "select * from mart_underwriting_variance"
  uif step   extract --doc-id <id>           run one step (what ECS tasks call)
  uif handoff status|check                   agent-handoff requests waiting / response sanity
  uif reguard                                after a guard change: re-guard stored docs, purge stale requests
  uif handoff answer --with bedrock          answer pending requests with Bedrock (parity runs in AWS dev)
  uif parity diff --labels synthetic         agent vs Bedrock on the same requests -> Gate C report

--llm picks the extractor: rules (offline baseline), handoff (Claude Code / Copilot agent fills
requests; see AGENT_EXTRACT.md), anthropic (Claude Messages API or your gateway), ollama, bedrock.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

LLM_KINDS = ["rules", "handoff", "anthropic", "ollama", "bedrock"]


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
    bad = waiting = 0
    for r in runs:
        last = r.results[-1]
        flag = "WAIT" if r.pending else ("ok  " if r.ok else "ERR ")
        bad += not r.ok
        waiting += r.pending
        print(f"{flag} {r.doc_id}  {r.file_name:<40} {last.step:<9} {last.detail or ''}")
        if args.verbose:
            for s in r.results:
                print(f"      {s.step:<9} ok={s.ok} {s.detail or ''}")
    print(f"\n{len(runs)} document(s), {bad} with errors, {waiting} waiting for an agent")
    if waiting:
        print("Next: have your agent follow AGENT_EXTRACT.md, then rerun this command with --force.")
    return 1 if bad else 0


def _read(ctx, path: str) -> bytes:
    return ctx.store.get_bytes(path[6:]) if path.startswith("store:") else Path(path).read_bytes()


def _write(ctx, path: str, data: bytes) -> str:
    if path.startswith("store:"):
        return ctx.store.put_bytes(path[6:], data)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)
    return str(Path(path).resolve())


def bundle_guard(ctx):
    """Bundles are checked with the deterministic regex/Luhn guard in every runtime. Comprehend (the
    AWS guard) also flags names such as "A. Customer", which would refuse every synthetic request;
    the import check exists to stop card numbers and IDs, which the regex guard owns."""
    from uif.providers.local import RegexGuard

    return RegexGuard(ctx.cfg["guard"]["token_salt"])


def cmd_handoff(args) -> int:
    from uif.providers import handoff as ho

    ctx = _ctx(args)
    store = ctx.store
    if args.action == "status":
        s = ho.status(store)
        print(json.dumps({k: len(v) for k, v in s.items()}))
        for rid in s["pending"]:
            print(f"pending  {store.uri(f'handoff/requests/{rid}.json')}")
        return 0
    if args.action == "check":
        problems = ho.check(store)
        for p in problems:
            print(f"PROBLEM {p}")
        print("responses look well-formed" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if args.action == "export":
        where = _write(ctx, args.out, ho.export_bundle(store, args.what))
        print(f"exported {args.what} -> {where}")
        return 0
    if args.action == "import":
        data = _read(ctx, args.path)
        if args.to:  # unpack a bundle into a plain folder (e.g. evals/golden/answers/bedrock)
            import io
            import zipfile

            dest = Path(args.to)
            dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = [n for n in z.namelist() if n.endswith(".json") and n != "manifest.json"]
                for n in names:
                    (dest / n.split("/", 1)[1]).write_bytes(z.read(n))
            print(f"unpacked {len(names)} file(s) -> {dest}")
            return 0
        res = ho.import_bundle(store, data, guard=bundle_guard(ctx))
        print(json.dumps(res))
        return 1 if res["refused"] else 0
    # answer: fill requests with a provider (Bedrock in AWS dev, Claude API, or rules)
    from uif.providers import build_llm

    if args.bundle:
        res = ho.import_bundle(store, _read(ctx, args.bundle), guard=bundle_guard(ctx))
        print(f"imported {res['loaded']} request(s); refused {len(res['refused'])}")
        if res["refused"]:
            return 1
    provider = build_llm(ctx.cfg, args.with_, store)
    summary = ho.answer_pending(store, provider, ctx.registry, label=args.with_, overwrite=args.overwrite,
                                limit=args.limit)
    print(json.dumps(summary, indent=1))
    if args.out:
        print(f"exported responses -> {_write(ctx, args.out, ho.export_bundle(store, 'responses'))}")
    return 1 if summary["failed"] else 0


def cmd_parity(args) -> int:
    from uif import parity

    ctx = _ctx(args)
    requests = parity.load_dir(args.requests)
    a, b = parity.load_dir(args.a), parity.load_dir(args.b)
    report = parity.diff(requests, a, b, ctx.registry)
    names = tuple(args.names.split(",")) if args.names else (Path(args.a).name, Path(args.b).name)
    evals = None
    if args.labels:
        evals = (parity.replay_eval(args.a, args.labels), parity.replay_eval(args.b, args.labels))
        for e in evals:
            e.pop("documents_detail", None)
        report["evals"] = {names[0]: evals[0], names[1]: evals[1]}
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str))
    md = parity.render_markdown(report, names, evals, show_quotes=not args.no_quotes)
    if args.report:
        Path(args.report).write_text(md)
        print(f"report -> {args.report}")
    print(md if not args.report else md.split("## Fields")[0])
    from uif.evals import gate as eval_gate

    failures = parity.gate(report) + ([f"{n}: {f}" for n, e in zip(names, evals) for f in eval_gate(e)] if evals else [])
    return 1 if failures else 0


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
    if args.formats:
        from uif.synth_formats import generate_formats

        print(json.dumps(generate_formats(args.out), indent=2))
        return 0
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


def cmd_reguard(args) -> int:
    """Re-run the guard over every stored document and purge handoff files it would now change.
    Run this after any change to guard patterns, then rerun the pipeline with --force."""
    from uif.providers.handoff import purge_unsafe
    from uif.steps import guard

    ctx = _ctx(args)
    doc_ids = [k.split("/")[-1][:-5] for k in ctx.store.list("envelope/") if k.endswith(".json")]
    changed = 0
    for doc_id in doc_ids:
        if not ctx.store.exists(ctx.key("normalized", doc_id=doc_id)):
            continue
        before = ctx.store.get_bytes(ctx.key("guarded", doc_id=doc_id)) if ctx.store.exists(
            ctx.key("guarded", doc_id=doc_id)) else b""
        guard.run(ctx, doc_id)
        changed += ctx.store.get_bytes(ctx.key("guarded", doc_id=doc_id)) != before
    purged = purge_unsafe(ctx.store, ctx.providers.guard)
    print(f"re-guarded {len(doc_ids)} document(s), {changed} changed; purged {len(purged)} handoff request(s)")
    if changed or purged:
        print("Next: rerun the pipeline with --force so extraction and publish use the re-guarded text.")
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
    r.add_argument("--llm", choices=LLM_KINDS)
    r.add_argument("--force", action="store_true", help="reprocess duplicates")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("step", help="run one step for one document")
    s.add_argument("name")
    s.add_argument("--doc-id")
    s.add_argument("--llm", choices=LLM_KINDS)
    s.set_defaults(fn=cmd_step)

    g = sub.add_parser("synth", help="generate labeled synthetic documents")
    g.add_argument("--out", default="synthetic")
    g.add_argument("--n", type=int, default=12)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--formats", action="store_true", help="one labeled sample per file format (samples/formats)")
    g.set_defaults(fn=cmd_synth)

    e = sub.add_parser("eval", help="score against golden labels")
    e.add_argument("path", nargs="?", default="synthetic")
    e.add_argument("--llm", choices=LLM_KINDS)
    e.add_argument("--no-run", action="store_true", help="score what is already processed")
    e.set_defaults(fn=cmd_eval)

    v = sub.add_parser("review", help="open review queue")
    v.add_argument("--limit", type=int, default=50)
    v.set_defaults(fn=cmd_review)

    h = sub.add_parser("handoff", help="agent handoff: status, check, export, import, answer")
    h.add_argument("action", choices=["status", "check", "export", "import", "answer"])
    h.add_argument("what", nargs="?", choices=["requests", "responses"], help="export: which files")
    h.add_argument("--out", help="export/answer: bundle path (local path or store:<key>)")
    h.add_argument("--path", help="import: bundle path (local path or store:<key>)")
    h.add_argument("--to", help="import: unpack into this folder instead of the store")
    h.add_argument("--with", dest="with_", default="bedrock", choices=["bedrock", "anthropic", "rules", "ollama"],
                   help="answer: which provider answers the requests")
    h.add_argument("--bundle", help="answer: import this request bundle first (local path or store:<key>)")
    h.add_argument("--overwrite", action="store_true", help="answer: re-answer requests that already have answers")
    h.add_argument("--limit", type=int)
    h.set_defaults(fn=cmd_handoff)

    pr = sub.add_parser("parity", help="diff two answer sets on the same requests; score both on labels")
    pr.add_argument("action", choices=["diff"])
    pr.add_argument("--requests", default="evals/golden/requests")
    pr.add_argument("--a", default="evals/golden/answers/claude-code")
    pr.add_argument("--b", default="evals/golden/answers/bedrock")
    pr.add_argument("--names", help="display names, e.g. claude-code,bedrock")
    pr.add_argument("--labels", help="golden folder (e.g. synthetic) to score both sides against labels")
    pr.add_argument("--report", help="write the markdown report here")
    pr.add_argument("--json", help="write the full JSON report here")
    pr.add_argument("--no-quotes", action="store_true", help="omit evidence quotes (real data)")
    pr.set_defaults(fn=cmd_parity)

    rg = sub.add_parser("reguard", help="re-run the guard over stored docs after a guard change")
    rg.set_defaults(fn=cmd_reguard)

    q = sub.add_parser("sql", help="query the local warehouse")
    q.add_argument("query")
    q.set_defaults(fn=cmd_sql)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
