import json
import os
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET


def _mresult(metric: dict) -> dict:
    """All eval fields (status, aiResultReason, errorReason, data) live inside metric['result']."""
    return metric.get("result") or {}


def analyze(run: dict) -> dict:
    test_cases = run.get("testCasesResults", [])
    metrics_agg: dict[str, dict] = {}
    partial_failures = []  # test cases where at least one metric failed

    for tc in test_cases:
        metrics_list = tc.get("metricsResults", [])
        tc_has_fail = False

        for metric in metrics_list:
            mtype = metric.get("type", "unknown")
            if mtype not in metrics_agg:
                metrics_agg[mtype] = {"passed": 0, "failed": 0}
            if _mresult(metric).get("status", "").lower() in ("passed", "pass"):
                metrics_agg[mtype]["passed"] += 1
            else:
                metrics_agg[mtype]["failed"] += 1
                tc_has_fail = True

        if tc_has_fail:
            partial_failures.append(tc)

    total = len(test_cases)
    duration = _duration_seconds(run.get("startTime"), run.get("endTime"))

    # Per-metric pass rates (matches Copilot Studio's own summary view)
    metric_rates = {
        mtype: round(c["passed"] / (c["passed"] + c["failed"]) * 100, 1)
        for mtype, c in metrics_agg.items()
        if (c["passed"] + c["failed"]) > 0
    }

    return {
        "run_id": run.get("id"),
        "agent_id": run.get("cdsBotId"),
        "state": run.get("state"),
        "start_time": run.get("startTime"),
        "end_time": run.get("endTime"),
        "duration_seconds": duration,
        "total": total,
        "metrics_by_type": metrics_agg,
        "metric_rates": metric_rates,
        "partial_failures": partial_failures,
        "partial_failure_count": len(partial_failures),
    }


def _duration_seconds(start: Optional[str], end: Optional[str]) -> Optional[float]:
    if not start or not end:
        return None
    try:
        t0 = datetime.fromisoformat(start)
        t1 = datetime.fromisoformat(end)
        return round((t1 - t0).total_seconds(), 1)
    except ValueError:
        return None


def print_results(run: dict, test_set_name: str = "") -> bool:
    stats = analyze(run)
    divider = "=" * 60
    thin = "-" * 60

    print(f"\n{divider}")
    print("EVALUATION RESULTS")
    print(divider)
    if test_set_name:
        print(f"Test Set : {test_set_name}")
    print(f"Run ID   : {stats['run_id']}")
    print(f"Agent    : {stats['agent_id']}")
    print(f"State    : {stats['state']}")
    print(f"Started  : {stats['start_time']}")
    print(f"Ended    : {stats['end_time']}")
    if stats["duration_seconds"] is not None:
        print(f"Duration : {stats['duration_seconds']}s")
    print(divider)

    test_cases = run.get("testCasesResults", [])
    for i, tc in enumerate(test_cases, 1):
        tc_id = tc.get("testCaseId", "unknown")

        print(f"\n  Test Case {i}  (id: {tc_id})")
        for metric in tc.get("metricsResults", []):
            mtype = metric.get("type", "unknown")
            res = _mresult(metric)
            m_status = res.get("status", "")
            reason = res.get("aiResultReason") or ""
            data = res.get("data") or {}
            error = res.get("errorReason") or ""
            m_pass = m_status.lower() in ("passed", "pass")
            bullet = "+" if m_pass else "-"

            print(f"    [{bullet}] {mtype:<32} {m_status}")
            for k, v in data.items():
                print(f"        {k.capitalize():<14}: {v}")
            if reason and not m_pass:
                for chunk in _wrap(reason, 54):
                    print(f"        Reason : {chunk}")
            if error:
                print(f"        Error  : {error}")

    # Metric-type breakdown table
    if stats["metrics_by_type"]:
        print(f"\n{thin}")
        print("METRICS BREAKDOWN")
        print(thin)
        col = max(len(t) for t in stats["metrics_by_type"]) + 2
        print(f"  {'Metric':<{col}}  {'Passed':>6}  {'Failed':>6}  {'Rate':>8}")
        print(f"  {'-'*col}  {'------':>6}  {'------':>6}  {'--------':>8}")
        for mtype, counts in sorted(stats["metrics_by_type"].items()):
            p, f = counts["passed"], counts["failed"]
            t = p + f
            rate = f"{p/t*100:.0f}%" if t > 0 else "n/a"
            print(f"  {mtype:<{col}}  {p:>6}  {f:>6}  {rate:>8}")

    # Failures section with AI reasons
    if stats["partial_failures"]:
        print(f"\n{thin}")
        print(f"FAILURE DETAILS  ({stats['partial_failure_count']} test case(s) with at least one metric failing)")
        print(thin)
        for tc in stats["partial_failures"]:
            tc_id = tc.get("testCaseId", "unknown")
            print(f"\n  Test Case: {tc_id}")
            for metric in tc.get("metricsResults", []):
                res = _mresult(metric)
                if res.get("status", "").lower() not in ("passed", "pass"):
                    mtype = metric.get("type", "unknown")
                    reason = res.get("aiResultReason") or ""
                    error = res.get("errorReason") or ""
                    print(f"    [{mtype}]")
                    if reason:
                        for chunk in _wrap(reason, 54):
                            print(f"      {chunk}")
                    elif not error:
                        print(f"      (no AI reason provided)")
                    if error:
                        print(f"      Error: {error}")

    # Summary matching Copilot Studio's per-metric view
    print(f"\n{divider}")
    print("SUMMARY")
    print(divider)
    for mtype, rate in stats["metric_rates"].items():
        counts = stats["metrics_by_type"][mtype]
        p, total_m = counts["passed"], counts["passed"] + counts["failed"]
        print(f"  {mtype:<20} : {p}/{total_m} passed  ({rate:.0f}%)")
    print(divider)

    # All metrics must reach 100% for a "green" run; caller uses this for exit code
    all_green = all(r == 100.0 for r in stats["metric_rates"].values())
    return all_green


def print_overall_summary(rows: list[tuple[str, dict]]) -> None:
    """Print a single cross-test-set summary table after parallel runs."""
    divider = "=" * 60
    print(f"\n{divider}")
    print("OVERALL SUMMARY")
    print(divider)

    # Collect all metric types seen across all test sets
    all_metrics: list[str] = []
    for _, stats in rows:
        for m in stats["metric_rates"]:
            if m not in all_metrics:
                all_metrics.append(m)

    name_col = max(len(name) for name, _ in rows) + 2
    metric_col = 10  # "XX/YY (ZZ%)"

    header = f"  {'Test Set':<{name_col}}"
    for m in all_metrics:
        header += f"  {m:>{metric_col}}"
    print(header)
    print("  " + "-" * (name_col + (metric_col + 2) * len(all_metrics)))

    for name, stats in rows:
        row = f"  {name:<{name_col}}"
        for m in all_metrics:
            counts = stats["metrics_by_type"].get(m)
            if counts:
                p = counts["passed"]
                t = counts["passed"] + counts["failed"]
                rate = int(p / t * 100) if t else 0
                cell = f"{p}/{t} ({rate}%)"
            else:
                cell = "n/a"
            row += f"  {cell:>{metric_col}}"
        print(row)

    print(divider + "\n")


def _wrap(text: str, width: int) -> list[str]:
    words, line, lines = text.split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > width and line:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    return lines or [""]


def write_json(run: dict, stats: dict, path: str) -> None:
    _ensure_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({**stats, "raw_run": run}, f, indent=2)


def write_junit_xml(run: dict, stats: dict, path: str, test_set_name: str = "") -> None:
    duration = str(stats.get("duration_seconds") or 0)
    total = stats["total"]
    # Count total metric-level failures for JUnit attributes
    failed = sum(c["failed"] for c in stats["metrics_by_type"].values())
    suite_name = test_set_name or run.get("cdsBotId", "CopilotStudio")

    testsuites = ET.Element("testsuites", {
        "name": "Copilot Studio Evals",
        "tests": str(total),
        "failures": str(failed),
        "time": duration,
    })
    testsuite = ET.SubElement(testsuites, "testsuite", {
        "name": suite_name,
        "tests": str(total),
        "failures": str(failed),
        "time": duration,
    })

    for i, tc in enumerate(run.get("testCasesResults", []), 1):
        metrics = tc.get("metricsResults", [])
        if not metrics:
            case_el = ET.SubElement(testsuite, "testcase", {
                "name": f"Test Case {i}",
                "classname": suite_name,
                "time": "0",
            })
            if tc.get("state", "").lower() not in ("passed", "pass"):
                ET.SubElement(case_el, "failure", {"message": tc.get("state", "Failed")})
        else:
            for metric in metrics:
                mtype = metric.get("type", "unknown")
                res = _mresult(metric)
                m_status = res.get("status", "")
                m_pass = m_status.lower() in ("passed", "pass")
                reason = res.get("aiResultReason") or ""
                error = res.get("errorReason") or ""

                case_el = ET.SubElement(testsuite, "testcase", {
                    "name": f"Test Case {i} [{mtype}]",
                    "classname": suite_name,
                    "time": "0",
                })
                if not m_pass:
                    msg = (reason or error or m_status or "Failed")[:200]
                    fail_el = ET.SubElement(case_el, "failure", {"message": msg})
                    fail_el.text = reason or error or ""

    _ensure_dir(path)
    tree = ET.ElementTree(testsuites)
    ET.indent(tree, space="  ")
    with open(path, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
