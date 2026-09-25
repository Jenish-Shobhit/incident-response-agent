"""Comparing two strings that are supposed to be numbers.

Metrics arrive as captured strings, and they are not written in one style::

    "12.4s" vs "85ms"         different units
    "182 / 200" vs "~60"      a ratio against an approximation
    "63 sessions" vs "0"      a baseline of zero
    "27%"   vs "<0.3%"        a bound, not a value

The naive version of this function is the most dangerous line of code in the project.
``float("12.4s".rstrip("s"))`` is 12.4 and ``float("85ms".rstrip("ms"))`` is 85, so 12.4
against 85 reports writes getting **85% faster** at the exact moment they are 146 times
slower -- and that number is the single strongest piece of evidence for the root cause.
A confident, precise, inverted answer is worse than no answer at all, because the
investigator has been told not to second-guess the arithmetic.

So: normalise to a base unit first, refuse across unit families, and when the strings
cannot honestly be compared say so and hand back the raw text instead of a number.
``comparable: False`` is a successful outcome, not a failure.
"""

import re

# Multiplier into each family's base unit. Suffixes are matched longest first across
# every family (SUFFIXES below): "ms" must win over "m" or everything is out by 60,000,
# and "sessions" must win over "s" or a count of sessions reads as a duration.
UNITS = [
    ("duration", "s", [("ms", 0.001), ("us", 1e-6), ("ns", 1e-9), ("s", 1.0),
                       ("m", 60.0), ("h", 3600.0)]),
    ("percent", "%", [("%", 1.0)]),
    ("count", "", [("threads", 1.0), ("sessions", 1.0), ("connections", 1.0), ("conns", 1.0),
                   ("requests", 1.0), ("reqs", 1.0), ("errors", 1.0), ("rps", 1.0),
                   ("qps", 1.0), ("", 1.0)]),
    ("bytes", "B", [("kb", 1e3), ("mb", 1e6), ("gb", 1e9), ("tb", 1e12), ("b", 1.0)]),
]

SUFFIXES = sorted(
    ((suffix, family, base, mult) for family, base, suffixes in UNITS
     for suffix, mult in suffixes if suffix),
    key=lambda t: -len(t[0]),
)

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def parse_metric(raw):
    """One metric string -> a dict describing what could be understood about it.

    Never raises.  ``ok`` is False whenever the string does not reduce to exactly one
    number in one recognised unit -- which includes "182 / 200", "n/a", "high" and "".
    """
    text = (raw or "").strip()
    out = {
        "raw": text,
        "ok": False,
        "value": None,
        "unit": None,
        "family": None,
        "approximate": False,
        "reason": "",
    }

    if not text:
        out["reason"] = "empty"
        return out

    # "~60" and "<0.3%" and ">= 200" are bounds or estimates. They can still be compared,
    # but the answer must be labelled so nobody quotes it as exact.
    if re.match(r"^\s*[~<>≤≥]=?", text):
        out["approximate"] = True

    numbers = NUMBER.findall(text)
    if not numbers:
        out["reason"] = f"no number in {text!r}"
        return out
    if len(numbers) > 1:
        # "182 / 200" is a pair, not a quantity. Refusing here is what stops a ratio of
        # saturated-against-baseline being invented out of two unrelated numbers.
        out["reason"] = f"more than one number in {text!r} - not a single quantity"
        return out

    value = float(numbers[0])
    tail = text[text.index(numbers[0]) + len(numbers[0]):].strip().lower()
    tail = tail.strip("()[]").strip()

    for suffix, family, base, mult in SUFFIXES:
        if tail.startswith(suffix):
            out.update(ok=True, value=value * mult, unit=base, family=family)
            return out

    if tail == "":
        out.update(ok=True, value=value, unit="", family="count")
        return out

    out["reason"] = f"unrecognised unit {tail!r} in {text!r}"
    return out


def compare_metric(value_raw, baseline_raw, name="", note=""):
    """Compare a metric against its baseline, honestly.

    Returns a dict the model is shown verbatim.  When ``comparable`` is False the
    ``reason`` tells the investigator what to do instead, and both raw strings are
    included so it can quote them rather than compute with them.
    """
    v = parse_metric(value_raw)
    b = parse_metric(baseline_raw)

    result = {
        "name": name,
        "value_raw": value_raw,
        "baseline_raw": baseline_raw,
        "note": note,
        "comparable": False,
        "approximate": v["approximate"] or b["approximate"],
        "delta": None,
        "ratio": None,
        "direction": None,
        "reason": "",
    }

    if not v["ok"] or not b["ok"]:
        broken = v if not v["ok"] else b
        result["reason"] = (
            f"{broken['reason']} - quote value_raw and baseline_raw verbatim "
            "and compute nothing"
        )
        return result

    if v["family"] != b["family"]:
        result["reason"] = (
            f"value is a {v['family']} and baseline is a {b['family']} - "
            "these are not the same kind of quantity, so no comparison is meaningful"
        )
        return result

    result["comparable"] = True
    result["delta"] = round(v["value"] - b["value"], 6)
    result["direction"] = (
        "higher" if v["value"] > b["value"]
        else "lower" if v["value"] < b["value"]
        else "unchanged"
    )

    if b["value"] == 0:
        result["reason"] = "baseline is zero; any non-zero value is a regression"
        return result

    ratio = v["value"] / b["value"]
    result["ratio"] = round(ratio, 4) if ratio < 10 else round(ratio, 1)
    result["reason"] = f"value is {result['ratio']}x baseline"
    return result
