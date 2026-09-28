"""Score the adjudicator against its labelled set.

    python -m python.controlplane.judge_eval            # deterministic judge
    python -m python.controlplane.judge_eval --live     # whatever CONTROLPLANE_PROVIDER is

Two numbers matter, and they are reported separately because they trade off
against each other and a single accuracy figure hides the trade:

**catch rate** — of the cases where something really is wrong, how many did it
flag? A miss here is an answer a person acts on.

**false-alarm rate** — of the cases where nothing is wrong, how many did it flag
anyway? Every false alarm costs a model call, a warning the reader learns to
ignore, and eventually the reviewer's attention. For a checker this is the
expensive error, which is why the set is weighted towards clean cases.

Nothing here is a mock. The same `adjudicate()` the request path calls, with the
same prompt, the same exemplars and the same domain calibration.
"""
from __future__ import annotations

import sys
from typing import Any

from .adjudicator import adjudicate
from .judge_cases import CASES, Case

CLEAN_VERDICTS = ("supported", "not_a_claim")


def _pick(adj: Any, needle: str):
    """The verdict on the claim the case is about."""
    if not needle:
        return None
    low = needle.lower()
    for v in adj.verdicts:
        if low in v.claim.lower():
            return v
    return None


def run(judge: Any, cases: list[Case] | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in (cases or CASES):
        adj = adjudicate(case.answer, case.sources, judge,
                         question=case.question, domain=case.domain)
        # An answer whose every sentence our own deterministic extractor decided
        # needs no source never reaches the judge at all. That is not a failure
        # to judge — it is the correct judgement reached for free, and scoring it
        # as a miss would punish the system for its own cost discipline.
        filtered = not adj.ran and adj.reason == "no checkable claim"

        got_verdict = ""
        if case.expect_verdict:
            v = _pick(adj, case.decisive)
            got_verdict = ("not_a_claim (filtered before the call)" if filtered
                           else v.verdict if v else "(no verdict on that claim)")
        got_suff = ("complete (no claim to check)" if filtered
                    else adj.sufficiency.verdict or "(none)")

        verdict_ok = (not case.expect_verdict) or got_verdict.split(" ")[0] == \
            case.expect_verdict
        suff_ok = got_suff.split(" ")[0] == case.expect_sufficiency

        # Did the judge raise an alarm of any kind on this case?
        alarmed = (not filtered) and bool(
            [x for x in adj.verdicts
             if x.needs_evidence and x.verdict not in CLEAN_VERDICTS]
            or adj.sufficiency.flagged)
        should_alarm = "positive" in case.tags

        rows.append({
            "id": case.id, "domain": case.domain, "tags": case.tags,
            "ran": adj.ran, "error": adj.error, "filtered": filtered,
            "expectVerdict": case.expect_verdict, "gotVerdict": got_verdict,
            "expectSufficiency": case.expect_sufficiency, "gotSufficiency": got_suff,
            "verdictOk": verdict_ok, "sufficiencyOk": suff_ok,
            "ok": verdict_ok and suff_ok,
            "alarmed": alarmed, "shouldAlarm": should_alarm,
            "alarmOk": alarmed == should_alarm,
            "tokens": adj.tokens, "latencyMs": round(adj.latency_ms, 1),
            "why": case.why,
        })

    positives = [r for r in rows if r["shouldAlarm"]]
    negatives = [r for r in rows if not r["shouldAlarm"]]
    graded = [r for r in rows if r["expectVerdict"]]

    matrix: dict[str, dict[str, int]] = {}
    for r in graded:
        matrix.setdefault(r["expectVerdict"], {})
        key = r["gotVerdict"]
        matrix[r["expectVerdict"]][key] = matrix[r["expectVerdict"]].get(key, 0) + 1

    def share(subset: list[dict[str, Any]], key: str) -> float:
        return round(sum(1 for r in subset if r[key]) / len(subset), 4) if subset else 0.0

    return {
        "judge": getattr(judge, "judge_model", "") or getattr(judge, "name", "?"),
        "cases": len(rows),
        "exactAgreement": share(rows, "ok"),
        "verdictAgreement": share(graded, "verdictOk"),
        "sufficiencyAgreement": share(rows, "sufficiencyOk"),
        "catchRate": share(positives, "alarmed"),
        "falseAlarmRate": round(
            sum(1 for r in negatives if r["alarmed"]) / len(negatives), 4)
        if negatives else 0.0,
        "positives": len(positives), "negatives": len(negatives),
        "tokens": sum(r["tokens"] for r in rows),
        "confusion": matrix,
        "rows": rows,
    }


def _provider(live: bool) -> Any:
    if not live:
        from .providers.offline import OfflineProvider
        return OfflineProvider()
    from .providers import get_provider
    return get_provider()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    live = "--live" in argv
    report = run(_provider(live))

    print(f"\n  adjudicator evaluation · judge = {report['judge']}"
          f" · {report['cases']} labelled cases\n")
    for r in report["rows"]:
        mark = "ok  " if r["ok"] else "MISS"
        print(f"  [{mark}] {r['id']:<26} "
              f"verdict {r['gotVerdict'] or '-':<14} "
              f"sufficiency {r['gotSufficiency']}")
        if not r["ok"]:
            print(f"         expected verdict {r['expectVerdict'] or '-'} / "
                  f"sufficiency {r['expectSufficiency']}")
            print(f"         {r['why']}")

    print(f"\n  catch rate            {report['catchRate'] * 100:5.1f}%  "
          f"({report['positives']} cases where something really is wrong)")
    print(f"  false alarm rate      {report['falseAlarmRate'] * 100:5.1f}%  "
          f"({report['negatives']} clean cases — this is the expensive error)")
    print(f"  claim verdict         {report['verdictAgreement'] * 100:5.1f}%  "
          f"agreement with the labels")
    print(f"  sufficiency           {report['sufficiencyAgreement'] * 100:5.1f}%  "
          f"agreement with the labels")
    print(f"  exact, both charges   {report['exactAgreement'] * 100:5.1f}%")
    print(f"  tokens spent          {report['tokens']}\n")

    for expected, got in sorted(report["confusion"].items()):
        print(f"    labelled {expected:<13} -> " +
              ", ".join(f"{k} x{v}" for k, v in sorted(got.items())))
    print()
    return 0


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
