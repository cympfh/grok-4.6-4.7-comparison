import argparse
import asyncio
import json
import os
import re
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from xai_sdk import AsyncClient
from xai_sdk.chat import user

load_dotenv()

PROJECT_DIR = Path(__file__).parent
BENCH_DIR = PROJECT_DIR / "benchmarks"
SANDBOX_RUNNER = PROJECT_DIR / "terminal_sandbox.py"
SECRETS_PATH = Path("/home/box/agent-data/box-secrets.json")

MODEL_EFFORTS = {
    "grok-4.6": ["high", "xhigh"],
    "grok-4.7": ["high", "xhigh"],
}

INPUT_USD_PER_MTOK = 2.0
OUTPUT_USD_PER_MTOK = 6.0
ESCALATION_THRESHOLD = 0.95
MAX_RETRIES = 5
RETRY_BASE_SEC = 4.0
RETRYABLE_MARKERS = (
    "UNAVAILABLE",
    "RESOURCE_EXHAUSTED",
    "DEADLINE_EXCEEDED",
    "INTERNAL",
    "temporarily unavailable",
    "Service temporarily unavailable",
)


DATASETS = {
    "translator-ja-en": {
        "file": "translator-ja-en.jsonl",
        "prompt": "次の日本語を自然な英語に翻訳し、翻訳文だけを出力してください。日本語: {input}",
        "score": "overlap",
    },
    "arithmetic": {
        "file": "arithmetic.jsonl",
        "prompt": "次の式を計算し、答えの数値だけを出力してください。式: {input}",
        "score": "numeric",
    },
    "differential": {
        "file": "differential.jsonl",
        "prompt": (
            "Solve the following calculus / differential-equation problem. "
            "Output only the final answer (a number or a short closed form). "
            "Problem: {input}"
        ),
        "score": "differential",
    },
    "terminal": {
        "file": "terminal.jsonl",
        "prompt": "{input}",
        "score": "terminal",
    },
}

# Extra samples appended once if every combo scores >= 0.95 on a dataset.
ESCALATION_SAMPLES: dict[str, list[dict]] = {
    "translator-ja-en": [
        {
            "input": "彼は、昨日会議で決まった方針について、関係各所へ丁寧に説明して回った。",
            "expected": "He went around carefully explaining to the relevant parties the policy that had been decided at yesterday's meeting.",
        },
        {
            "input": "雨が上がったと思ったら、またすぐに降り始めた。",
            "expected": "Just when I thought the rain had stopped, it started raining again.",
        },
        {
            "input": "この問題は一見簡単そうだが、実は落とし穴がある。",
            "expected": "This problem looks easy at first glance, but there is actually a pitfall.",
        },
    ],
    "arithmetic": [
        {"input": "7^6 - 5^8 + 3^9", "expected": "-253293"},
        {"input": "1 + 1/(1 + 1/(1 + 1/2))", "expected": "1.6"},
        {"input": "(13^3 - 11^3) / (13 - 11)", "expected": "433"},
        {"input": "2^20 / 2^10 - 3^5", "expected": "781"},
        {"input": "(9/4 + 7/6) * (18/5) - 11/10", "expected": "11.2"},
    ],
    "differential": [
        {
            "input": "y''' = 0, y(0)=1, y'(0)=2, y''(0)=6. Find y(1). Output only the number.",
            "expected": "6",
        },
        {
            "input": "Evaluate the definite integral of sin(x) from 0 to pi/2. Output only the number.",
            "expected": "1",
        },
        {
            "input": "y' = -y, y(0)=8. Find y(ln 2). Output only the number.",
            "expected": "4",
        },
        {
            "input": "d/dx (e^{2x}) at x=0. Output only the number.",
            "expected": "2",
        },
    ],
    "terminal": [
        {
            "id": "files-01-20",
            "input": (
                "Create files named n01.txt through n20.txt. nNN.txt must contain only the integer N "
                "(optional trailing newline). Output ONLY a bash script inside a ```bash fenced block."
            ),
            "check": {"files": {f"n{i:02d}.txt": str(i) for i in range(1, 21)}},
        },
        {
            "id": "pipeline-uniq",
            "input": (
                "Create raw.txt with lines: apple, banana, apple, cherry, banana, apple "
                "(one word per line). Write the unique words sorted alphabetically to unique.txt. "
                "Output ONLY a bash script inside a ```bash fenced block."
            ),
            "check": {
                "files": {
                    "raw.txt": "apple\nbanana\napple\ncherry\nbanana\napple",
                    "unique.txt": "apple\nbanana\ncherry",
                }
            },
        },
        {
            "id": "bc-fraction",
            "input": (
                "Using bc or python3, compute 22/7 rounded to 4 decimal places and write it to piapprox.txt "
                "(exactly 3.1429). Output ONLY a bash script inside a ```bash fenced block."
            ),
            "check": {"files": {"piapprox.txt": "3.1429"}},
        },
    ],
}

FORBIDDEN_SCRIPT_PATTERNS = [
    r"\bsudo\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bssh\b",
    r"\bscp\b",
    r"\bnc\b",
    r"\bnmap\b",
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+/\*",
    r"/etc\b",
    r"/home\b",
    r"/root\b",
    r"/usr\b",
    r"/var\b",
    r"/proc\b",
    r"/sys\b",
    r"/dev\b",
    r"\.\./",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bmkfs\b",
    r"\bdd\b",
]


@dataclass
class SampleResult:
    latency: float
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    total_tokens: int
    output_tokens_billed: int
    cost_usd: float
    score: float
    error: Optional[str] = None
    usage_fields: dict[str, Any] = field(default_factory=dict)


_USAGE_INSPECTED = False
_USAGE_NOTE = ""


def load_api_key() -> None:
    if os.getenv("XAI_API_KEY"):
        return
    if not SECRETS_PATH.exists():
        return
    data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    key = (data.get("card") or {}).get("XAI_API_KEY")
    if key:
        os.environ["XAI_API_KEY"] = key


def load_dataset(name: str) -> list[dict]:
    path = BENCH_DIR / DATASETS[name]["file"]
    samples = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def append_samples(name: str, extra: list[dict]) -> None:
    path = BENCH_DIR / DATASETS[name]["file"]
    with path.open("a", encoding="utf-8") as f:
        for sample in extra:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def normalize_expr(s: str) -> str:
    s = s.strip().lower()
    s = s.replace("**", "^")
    s = re.sub(r"\s+", "", s)
    s = s.replace("{", "").replace("}", "")
    s = s.replace("\\", "")
    return s


def _parse_numeric_token(token: str) -> Optional[float]:
    token = token.strip().replace(",", "")
    if not token:
        return None
    frac = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)", token)
    if frac:
        den = float(frac.group(2))
        if den == 0:
            return None
        return float(frac.group(1)) / den
    if re.fullmatch(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", token, re.I):
        return float(token)
    return None


def extract_number(s: str) -> Optional[float]:
    text = (s or "").replace(",", "").strip()
    if not text:
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        direct = _parse_numeric_token(lines[-1])
        if direct is not None:
            return direct
        boxed = re.search(r"(-?\d+(?:\.\d+)?(?:\s*/\s*-?\d+(?:\.\d+)?)?)\s*$", lines[-1])
        if boxed:
            parsed = _parse_numeric_token(boxed.group(1))
            if parsed is not None:
                return parsed
    matches = re.findall(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", text, flags=re.I)
    if not matches:
        return None
    return float(matches[-1])


def score_numeric(output: str, expected: str) -> float:
    got = extract_number(output)
    want = extract_number(expected)
    if got is None or want is None:
        return 0.0
    return 1.0 if abs(got - want) < 1e-6 else 0.0


def score_exact(output: str, expected: str) -> float:
    return 1.0 if normalize(output) == normalize(expected) else 0.0


def score_overlap(output: str, expected: str) -> float:
    got_words = normalize(output).split()
    want_words = normalize(expected).split()
    if not got_words or not want_words:
        return 0.0
    got_set, want_set = set(got_words), set(want_words)
    overlap = len(got_set & want_set)
    precision = overlap / len(got_set)
    recall = overlap / len(want_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def score_differential(output: str, expected: str) -> float:
    if score_numeric(output, expected) == 1.0:
        return 1.0
    if normalize_expr(output) == normalize_expr(expected):
        return 1.0
    # last line closed form vs expected
    lines = [ln.strip() for ln in (output or "").splitlines() if ln.strip()]
    if lines and normalize_expr(lines[-1]) == normalize_expr(expected):
        return 1.0
    return 0.0


def extract_bash_script(output: str) -> Optional[str]:
    match = re.search(r"```(?:bash|sh)\s*\n(.*?)```", output or "", flags=re.S | re.I)
    if match:
        return match.group(1)
    return None


def script_is_forbidden(script: str) -> Optional[str]:
    for pat in FORBIDDEN_SCRIPT_PATTERNS:
        if re.search(pat, script, flags=re.I):
            return f"forbidden pattern: {pat}"
    # reject absolute paths except /bin /usr/bin shebang-like that we still block via /usr
    if re.search(r"(?<![A-Za-z0-9_])/tmp\b", script):
        return "forbidden path: /tmp"
    return None


def _norm_text(s: str) -> str:
    return (s or "").replace("\r\n", "\n").strip()


def score_terminal(output: str, sample: dict) -> float:
    script = extract_bash_script(output)
    if not script:
        return 0.0
    reason = script_is_forbidden(script)
    if reason:
        return 0.0
    check = sample.get("check") or {}
    expected_files: dict[str, str] = check.get("files") or {}
    expected_stdout = check.get("stdout")
    absent = check.get("absent") or []

    with tempfile.TemporaryDirectory(prefix="gcmp-term-") as tmp:
        script_path = Path(tmp) / "script.sh"
        script_path.write_text(script, encoding="utf-8")
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": tmp,
            "TMPDIR": tmp,
            "LANG": "C.UTF-8",
        }
        try:
            proc = subprocess.Popen(
                [sys.executable, str(SANDBOX_RUNNER), "bash", str(script_path)],
                cwd=tmp,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, _stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                return 0.0
        except Exception:
            return 0.0

        if expected_stdout is not None:
            if _norm_text(stdout) != _norm_text(expected_stdout):
                return 0.0

        tmp_path = Path(tmp)
        for rel, want in expected_files.items():
            if ".." in Path(rel).parts:
                return 0.0
            target = (tmp_path / rel).resolve()
            try:
                target.relative_to(tmp_path.resolve())
            except ValueError:
                return 0.0
            if not target.is_file():
                return 0.0
            got = target.read_text(encoding="utf-8", errors="replace")
            if _norm_text(got) != _norm_text(want):
                return 0.0
        for rel in absent:
            if (tmp_path / rel).exists():
                return 0.0
    return 1.0


SCORERS = {
    "numeric": score_numeric,
    "arithmetic": score_numeric,
    "exact": score_exact,
    "overlap": score_overlap,
    "differential": score_differential,
    "terminal": score_terminal,
}


def _usage_mapping(usage: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if usage is None:
        return fields
    if isinstance(usage, dict):
        return dict(usage)
    for name in dir(usage):
        if name.startswith("_"):
            continue
        try:
            val = getattr(usage, name)
        except Exception:
            continue
        if callable(val):
            continue
        fields[name] = val
    # protobuf-style extra
    for name in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "reasoning_tokens",
        "input_tokens",
        "output_tokens",
        "cached_prompt_text_tokens",
        "prompt_text_tokens",
        "completion_text_tokens",
        "num_sources_used",
    ):
        if hasattr(usage, name) and name not in fields:
            try:
                fields[name] = getattr(usage, name)
            except Exception:
                pass
    details = getattr(usage, "completion_tokens_details", None)
    if details is not None:
        r = getattr(details, "reasoning_tokens", None)
        if r is not None:
            fields.setdefault("reasoning_tokens", r)
            fields["completion_tokens_details.reasoning_tokens"] = r
    return fields


def parse_usage(usage: Any) -> tuple[int, int, int, int, int, dict[str, Any]]:
    """Return prompt, completion, reasoning, total, output_billed, raw fields.

    Reasoning tokens are billed as output. If total ~= prompt + completion,
    reasoning is treated as a subset of completion and is not added again.
    """
    global _USAGE_INSPECTED, _USAGE_NOTE
    fields = _usage_mapping(usage)

    def _as_int(keys: list[str]) -> Optional[int]:
        for k in keys:
            if k in fields and fields[k] is not None:
                try:
                    return int(fields[k])
                except (TypeError, ValueError):
                    continue
        return None

    prompt = _as_int(["prompt_tokens", "input_tokens", "prompt_text_tokens"]) or 0
    completion = _as_int(["completion_tokens", "output_tokens", "completion_text_tokens"]) or 0
    reasoning = _as_int(["reasoning_tokens", "completion_tokens_details.reasoning_tokens"]) or 0
    total = _as_int(["total_tokens"])
    if total is None:
        total = prompt + completion

    if abs(total - (prompt + completion)) <= 1:
        output_billed = completion
        note = (
            "total ≈ prompt + completion; reasoning treated as subset of completion "
            "(not double-counted)"
        )
    else:
        output_billed = completion + reasoning
        note = (
            "total != prompt + completion; reasoning added to output tokens for billing"
        )

    if not _USAGE_INSPECTED:
        printable = {}
        for k, v in fields.items():
            if isinstance(v, (int, float, str, bool)) or v is None:
                printable[k] = v
            else:
                printable[k] = type(v).__name__
        print("[usage] fields:", sorted(printable.keys()), flush=True)
        print("[usage] sample:", printable, flush=True)
        print("[usage] billing:", note, flush=True)
        _USAGE_INSPECTED = True
        _USAGE_NOTE = note

    return prompt, completion, reasoning, total, output_billed, fields


def is_retryable_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(m.lower() in text.lower() for m in RETRYABLE_MARKERS)


def compute_cost_usd(prompt_tokens: int, output_tokens_billed: int) -> float:
    return (
        prompt_tokens * INPUT_USD_PER_MTOK / 1_000_000.0
        + output_tokens_billed * OUTPUT_USD_PER_MTOK / 1_000_000.0
    )


def score_sample(dataset_name: str, output: str, sample: dict) -> float:
    kind = DATASETS[dataset_name]["score"]
    if kind == "terminal":
        return score_terminal(output, sample)
    expected = sample.get("expected", "")
    return SCORERS[kind](output, expected)


async def run_sample(
    client: AsyncClient,
    model: str,
    effort: str,
    dataset_name: str,
    sample: dict,
    semaphore: asyncio.Semaphore,
) -> SampleResult:
    prompt = DATASETS[dataset_name]["prompt"].format(input=sample["input"])
    async with semaphore:
        start = time.monotonic()
        response = None
        last_error = None
        for attempt in range(MAX_RETRIES):
            chat = client.chat.create(model=model, reasoning_effort=effort)
            chat.append(user(prompt))
            try:
                response = await chat.sample()
                last_error = None
                break
            except Exception as e:
                last_error = e
                if is_retryable_error(e) and attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_SEC * (2 ** attempt)
                    print(
                        f"  [retry] {model}/{effort} attempt={attempt + 1}/{MAX_RETRIES} "
                        f"wait={delay:.0f}s ({type(e).__name__})",
                        flush=True,
                    )
                    await asyncio.sleep(delay)
                    continue
                return SampleResult(
                    latency=time.monotonic() - start,
                    prompt_tokens=0,
                    completion_tokens=0,
                    reasoning_tokens=0,
                    total_tokens=0,
                    output_tokens_billed=0,
                    cost_usd=0.0,
                    score=0.0,
                    error=f"{type(e).__name__}: {e}",
                )
        if response is None:
            return SampleResult(
                latency=time.monotonic() - start,
                prompt_tokens=0,
                completion_tokens=0,
                reasoning_tokens=0,
                total_tokens=0,
                output_tokens_billed=0,
                cost_usd=0.0,
                score=0.0,
                error=(
                    f"{type(last_error).__name__}: {last_error}"
                    if last_error
                    else "empty response"
                ),
            )
        latency = time.monotonic() - start

    output = response.content or ""
    usage = getattr(response, "usage", None)
    prompt_t, completion_t, reasoning_t, total_t, billed, fields = parse_usage(usage)
    score = score_sample(dataset_name, output, sample)
    cost = compute_cost_usd(prompt_t, billed)
    return SampleResult(
        latency=latency,
        prompt_tokens=prompt_t,
        completion_tokens=completion_t,
        reasoning_tokens=reasoning_t,
        total_tokens=total_t,
        output_tokens_billed=billed,
        cost_usd=cost,
        score=score,
        usage_fields=fields,
    )


async def run_combo(
    client: AsyncClient,
    model: str,
    effort: str,
    dataset_name: str,
    samples: list[dict],
    concurrency: int,
) -> list[SampleResult]:
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        run_sample(client, model, effort, dataset_name, sample, semaphore)
        for sample in samples
    ]
    return await asyncio.gather(*tasks)


def summarize(results: list[SampleResult]) -> dict:
    ok = [r for r in results if r.error is None]
    errors = len(results) - len(ok)
    error_examples = [r.error for r in results if r.error][:5]
    if not ok:
        return {
            "n": len(results),
            "errors": errors,
            "error_examples": error_examples,
            "avg_latency": 0.0,
            "avg_score": 0.0,
            "avg_prompt_tokens": 0.0,
            "avg_completion_tokens": 0.0,
            "avg_reasoning_tokens": 0.0,
            "avg_total_tokens": 0.0,
            "avg_tokens": 0.0,
            "total_cost_usd": 0.0,
            "avg_cost_usd": 0.0,
        }
    total_cost = sum(r.cost_usd for r in ok)
    avg_total = statistics.mean(r.total_tokens for r in ok)
    return {
        "n": len(results),
        "errors": errors,
        "error_examples": error_examples,
        "avg_latency": statistics.mean(r.latency for r in ok),
        "avg_score": statistics.mean(r.score for r in ok),
        "avg_prompt_tokens": statistics.mean(r.prompt_tokens for r in ok),
        "avg_completion_tokens": statistics.mean(r.completion_tokens for r in ok),
        "avg_reasoning_tokens": statistics.mean(r.reasoning_tokens for r in ok),
        "avg_total_tokens": avg_total,
        "avg_tokens": avg_total,
        "total_cost_usd": total_cost,
        "avg_cost_usd": statistics.mean(r.cost_usd for r in ok),
    }


def print_table(rows: list[dict]) -> None:
    headers = [
        "dataset",
        "model",
        "effort",
        "n",
        "errors",
        "avg_latency",
        "avg_score",
        "avg_prompt",
        "avg_completion",
        "avg_reasoning",
        "avg_total",
        "total_cost",
        "avg_cost",
    ]
    formatted_rows = [
        {
            "dataset": r["dataset"],
            "model": r["model"],
            "effort": r["effort"],
            "n": str(r["n"]),
            "errors": str(r["errors"]),
            "avg_latency": f"{r['avg_latency']:.2f}s",
            "avg_score": f"{r['avg_score']:.3f}",
            "avg_prompt": f"{r['avg_prompt_tokens']:.0f}",
            "avg_completion": f"{r['avg_completion_tokens']:.0f}",
            "avg_reasoning": f"{r['avg_reasoning_tokens']:.0f}",
            "avg_total": f"{r['avg_total_tokens']:.0f}",
            "total_cost": f"{r['total_cost_usd']:.6f}",
            "avg_cost": f"{r['avg_cost_usd']:.6f}",
        }
        for r in rows
    ]
    widths = {
        h: max(len(h), *(len(r[h]) for r in formatted_rows)) if formatted_rows else len(h)
        for h in headers
    }

    def fmt_row(values: list[str]) -> str:
        return " | ".join(v.ljust(widths[h]) for h, v in zip(headers, values))

    print()
    print(fmt_row(headers))
    print("-+-".join("-" * widths[h] for h in headers))
    for r in formatted_rows:
        print(fmt_row([r[h] for h in headers]))


async def run_dataset_all_combos(
    client: AsyncClient,
    dataset_name: str,
    samples: list[dict],
    models: list[str],
    concurrency: int,
    checkpoint_path: Path | None = None,
    all_rows_ref: list[dict] | None = None,
) -> list[dict]:
    rows = []
    for model in models:
        for effort in MODEL_EFFORTS[model]:
            print(f"[running] dataset={dataset_name} model={model} effort={effort} n={len(samples)}", flush=True)
            results = await run_combo(client, model, effort, dataset_name, samples, concurrency)
            summary = summarize(results)
            row = {"dataset": dataset_name, "model": model, "effort": effort, **summary}
            rows.append(row)
            print(
                f"  -> avg_latency={summary['avg_latency']:.2f}s avg_score={summary['avg_score']:.3f} "
                f"avg_total={summary['avg_total_tokens']:.0f} avg_reasoning={summary['avg_reasoning_tokens']:.0f} "
                f"total_cost=${summary['total_cost_usd']:.6f} errors={summary['errors']}",
                flush=True,
            )
            if summary["error_examples"]:
                print(f"  -> errors: {summary['error_examples']}", flush=True)
            if checkpoint_path is not None and all_rows_ref is not None:
                merged = [r for r in all_rows_ref if r.get("dataset") != dataset_name] + rows
                checkpoint_path.write_text(
                    json.dumps({"rows": merged, "partial": True}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
    return rows


async def main_async(args: argparse.Namespace) -> None:
    load_api_key()
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise SystemExit("環境変数 XAI_API_KEY が設定されていません")

    client = AsyncClient(api_key=api_key, timeout=3600)

    rows: list[dict] = []
    escalations: list[dict] = []

    for dataset_name in args.datasets:
        samples = load_dataset(dataset_name)
        if args.limit is not None:
            samples = samples[: args.limit]
        out_path = Path(args.output) if args.output else None
        dataset_rows = await run_dataset_all_combos(
            client, dataset_name, samples, args.models, args.concurrency, out_path, rows
        )
        rows.extend(dataset_rows)

        if args.no_escalate or args.limit is not None:
            continue
        if not dataset_rows:
            continue
        if all(r["avg_score"] >= ESCALATION_THRESHOLD and r["errors"] == 0 for r in dataset_rows):
            extra = ESCALATION_SAMPLES.get(dataset_name) or []
            if not extra:
                continue
            print(
                f"[escalate] {dataset_name}: all combos >= {ESCALATION_THRESHOLD}; "
                f"adding {len(extra)} harder samples and re-running",
                flush=True,
            )
            append_samples(dataset_name, extra)
            samples = load_dataset(dataset_name)
            escalations.append(
                {
                    "dataset": dataset_name,
                    "added": len(extra),
                    "reason": f"all combos avg_score >= {ESCALATION_THRESHOLD}",
                    "added_inputs": [s.get("id") or s.get("input") for s in extra],
                }
            )
            # drop previous rows for this dataset and replace with rerun
            rows = [r for r in rows if r["dataset"] != dataset_name]
            dataset_rows = await run_dataset_all_combos(
                client, dataset_name, samples, args.models, args.concurrency, out_path, rows
            )
            rows.extend(dataset_rows)

    print_table(rows)
    if escalations:
        print("\nEscalations:", json.dumps(escalations, ensure_ascii=False, indent=2))
    if _USAGE_NOTE:
        print(f"\nUsage billing note: {_USAGE_NOTE}")

    if args.output:
        payload = {
            "meta": {
                "pricing_usd_per_mtok": {
                    "input": INPUT_USD_PER_MTOK,
                    "output": OUTPUT_USD_PER_MTOK,
                },
                "reasoning_billing": _USAGE_NOTE,
                "escalations": escalations,
                "models": args.models,
                "efforts": ["high", "xhigh"],
            },
            "rows": rows,
        }
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n結果を {args.output} に保存しました")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grok 4.6 / 4.7 の性能・速度・コスト比較ベンチマーク")
    parser.add_argument("--datasets", nargs="+", default=list(DATASETS.keys()), choices=list(DATASETS.keys()))
    parser.add_argument("--models", nargs="+", default=list(MODEL_EFFORTS.keys()), choices=list(MODEL_EFFORTS.keys()))
    parser.add_argument("--limit", type=int, default=None, help="各データセットから使うサンプル数")
    parser.add_argument("--concurrency", type=int, default=3, help="同時リクエスト数")
    parser.add_argument("--output", type=str, default=None, help="結果をJSONで保存するパス")
    parser.add_argument("--no-escalate", action="store_true", help="高スコア時の難易度引き上げをしない")
    return parser.parse_args()


def main():
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
