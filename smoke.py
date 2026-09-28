import sys, time, json
sys.path.insert(0, __import__('pathlib').Path(__file__).resolve().parent.as_posix())
from python.controlplane.org import build, SCENARIOS
from python.controlplane.plane import ControlPlane
from python.controlplane.providers import get_provider

cp = ControlPlane(build(), get_provider())
print("provider:", cp.provider.name, "live:", cp.provider.live)
print("=" * 78)
for s in SCENARIOS:
    r = cp.turn(s["systemId"], s["message"], amount_inr=s.get("amountInr"))
    cap, d, risk = r["capability"], r["decision"], r["risk"]
    print(f"\n▸ {s['label']}  [{s['systemId']}]")
    print(f"  {s['note']}")
    print(f"  declared={cap['declaredAction']:<8} effective={cap['effectiveAction']:<8} "
          f"radius={cap['blastRadius']:<5} mismatch={cap['capabilityMismatch']}")
    print(f"  price={risk['price']:<4} band={risk['band']} labels={risk['labels']} dominant={risk['dominant']}")
    print(f"  ROUTE = {d['action'].upper()}  ({d['reason'][:88]})")
    print(f"  governance={r['governance']['status']}  decision={r['decisionLatencyMs']}ms  "
          f"verification={r['verificationStatus']}")
    ran = [x for x in r["detectors"] if x["status"] in ("completed","completed_async")]
    for x in ran:
        print(f"     {x['detectorId']:<10} {x['status']:<10} score={x['score']} :: {(x['evidence'] or [''])[0][:70]}")
    for x in r["detectors"]:
        if x["status"] not in ("completed","completed_async"):
            print(f"     {x['detectorId']:<10} {x['status']}")
print("\n" + "=" * 78)
time.sleep(1.2)
f = cp.fleet()
print("FLEET")
for s in f["systems"]:
    print(f"  {s['status']:<10} {s['systemId']:<19} price·exp={s['exposure']:<5} "
          f"₹{s['spendInr']:.2f}/{s['budgetInr']} ({s['budgetUsedPct']}%) "
          f"review={s['reviewUsedPct']}% complete={s['completeness']} :: {s['statusReason']}")
print(f"\n  completeness  {f['completenessLabel']}")
print(f"  decision p50  {f['decisionLatencyP50']}ms   p95 {f['decisionLatencyP95']}ms")
print(f"  verification  backlog={f['verificationBacklog']} stale={f['staleExposure']} health={f['governanceHealth']}")
print(f"  routes        {f['routes']}")
print(f"\nRECOMMENDATIONS ({len(cp.recommendations)})")
for rec in cp.recommendations[-4:]:
    print(f"  {rec['ruleId']} v{rec['ruleVersion']} [{rec['severity']}] {rec['systemId']}")
    print(f"     {rec['text'][:100]}")
    print(f"     evidence={json.dumps(rec['evidence'])}")
