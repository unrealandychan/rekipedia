#!/usr/bin/env python3
"""
rekipedia Benchmark: Extraction Accuracy

Verifies that known code snapshots produce the expected symbols.
Usage:
    python benchmarks/run_extraction.py [--verbose]

Exit code 0 = all benchmarks pass, 1 = failures.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def run_extraction_benchmark(verbose: bool = False) -> dict:
    """Run extraction accuracy benchmarks. Returns results dict."""
    from rekipedia.extractors.python_extractor import PythonExtractor
    from rekipedia.extractors.typescript_extractor import TypeScriptExtractor

    baselines_path = Path(__file__).parent / "baselines.json"
    baselines = json.loads(baselines_path.read_text())
    fixtures_dir = Path(__file__).parent / "fixtures"

    results = {}
    all_passed = True

    # Python web app benchmark
    py_fixture = fixtures_dir / "python_web_app" / "app.py"
    extractor = PythonExtractor()
    result = extractor.extract(py_fixture, fixtures_dir / "python_web_app")
    symbol_names = {s.name for s in result.symbols}
    expected = set(baselines["benchmarks"]["extraction"]["python_web_app"]["expected_symbols"])
    passed = expected.issubset(symbol_names)
    results["python_web_app"] = {
        "passed": passed,
        "expected": sorted(expected),
        "found": sorted(symbol_names),
        "missing": sorted(expected - symbol_names),
    }
    if not passed:
        all_passed = False
    if verbose:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  Python web app: {status}")
        if not passed:
            print(f"    Missing: {results['python_web_app']['missing']}")

    # TypeScript React benchmark
    ts_fixture = fixtures_dir / "typescript_react" / "App.tsx"
    ts_extractor = TypeScriptExtractor()
    ts_result = ts_extractor.extract(ts_fixture, fixtures_dir / "typescript_react")
    ts_names = {s.name for s in ts_result.symbols}
    ts_expected = set(baselines["benchmarks"]["extraction"]["typescript_react"]["expected_symbols"])
    ts_passed = ts_expected.issubset(ts_names)
    results["typescript_react"] = {
        "passed": ts_passed,
        "expected": sorted(ts_expected),
        "found": sorted(ts_names),
        "missing": sorted(ts_expected - ts_names),
    }
    if not ts_passed:
        all_passed = False
    if verbose:
        status = "✅ PASS" if ts_passed else "❌ FAIL"
        print(f"  TypeScript React: {status}")
        if not ts_passed:
            print(f"    Missing: {results['typescript_react']['missing']}")

    results["all_passed"] = all_passed
    return results


def run_performance_benchmark(verbose: bool = False) -> dict:
    """Benchmark extraction speed using the Python fixture."""
    import time

    from rekipedia.extractors.python_extractor import PythonExtractor

    fixtures_dir = Path(__file__).parent / "fixtures"
    py_fixture = fixtures_dir / "python_web_app" / "app.py"
    extractor = PythonExtractor()
    repo_root = fixtures_dir / "python_web_app"

    start = time.perf_counter()
    ITERS = 100
    total_symbols = 0
    for _ in range(ITERS):
        res = extractor.extract(py_fixture, repo_root)
        total_symbols += len(res.symbols)
    elapsed = time.perf_counter() - start
    symbols_per_second = total_symbols / elapsed

    baselines_path = Path(__file__).parent / "baselines.json"
    baselines = json.loads(baselines_path.read_text())
    threshold = baselines["benchmarks"]["performance"]["thresholds"]["symbols_per_second"]
    passed = symbols_per_second >= threshold

    result = {
        "passed": passed,
        "symbols_per_second": round(symbols_per_second, 1),
        "threshold": threshold,
        "elapsed_sec": round(elapsed, 3),
    }
    if verbose:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  Performance: {status} ({symbols_per_second:.0f} symbols/sec, threshold={threshold})")

    return result


def main():
    parser = argparse.ArgumentParser(description="rekipedia benchmark suite")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    args = parser.parse_args()

    if args.verbose:
        print("🔍 rekipedia Benchmark Suite")
        print("=" * 40)
        print("Extraction accuracy:")

    extraction = run_extraction_benchmark(verbose=args.verbose)

    if args.verbose:
        print("Performance:")

    performance = run_performance_benchmark(verbose=args.verbose)

    all_passed = extraction["all_passed"] and performance["passed"]

    if args.json:
        print(json.dumps({"extraction": extraction, "performance": performance, "all_passed": all_passed}, indent=2))
    elif args.verbose:
        print("=" * 40)
        overall = "✅ ALL BENCHMARKS PASS" if all_passed else "❌ SOME BENCHMARKS FAILED"
        print(overall)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
