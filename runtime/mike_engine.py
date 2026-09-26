#!/usr/bin/env python3
"""Mike 1.0: offline dossier validation, deterministic metrics and Markdown rendering.

No web calls, models, credentials, publishing, or automatic trust determination.
Evidence judgments and review receipts are inputs: validate them against actual
retrieval and reviewer logs. This program cannot authenticate an LLM receipt.
Python 3.10+; standard library only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

VERSION = "1.0.0"
SCHEMA = "mike-dossier/1.0"
RUBRIC = "mike-nci/1.0"
FACTOR_NAMES = [
    "Timing and sequencing", "Emotion-laden presentation", "Repeated source wording",
    "Material context gaps", "Oversimplification", "Us-versus-them framing",
    "Appeals to authority", "Urgency cues", "Hyperbole and novelty claims",
    "Documented incentives", "Documented exclusion of relevant responses",
    "False dichotomies", "Popularity as evidence", "Repeated emotional cues",
    "Selective statistical presentation", "Reasoning gaps", "Outrage framing",
    "Headline and presentation framing", "Claimed behavioral shifts",
    "Historical analogies",
]
LEGACY_NAMES = [
    "Timing Optimization", "Emotional Manipulation", "Uniform Messaging",
    "Missing Information", "Simplistic Narrative", "Tribal Division",
    "Authority Overload", "Call for Urgent Action", "Novelty / Hyperbole",
    "Financial or Political Gain", "Suppression of Dissent", "False Dilemma",
    "Bandwagon Effect", "Emotional Repetition", "Cherry-Picked Data",
    "Logical Fallacies", "Manufactured Outrage", "Framing Techniques",
    "Rapid Behavior Shifts", "Historical Parallels",
]
HYPOTHESES = {
    "H1": "Mostly organic event and mostly organic coverage",
    "H2": "Real event, but selectively framed for political or financial advantage",
    "H3": "Real event, but amplified by coordinated influence actors",
    "H4": "False or misleading event introduced intentionally",
    "H5": "Algorithm-driven outrage without central coordination",
    "H6": "Distraction from another issue",
    "H7": "Mixed environment: true facts plus manipulative packaging",
    "H8": "Insufficient evidence",
}
POLITICAL_TOPICS = {"politics", "elections", "governance", "legislation", "public-policy",
                    "political-campaigns", "ballot-measures"}
FACT_STATUSES = {"confirmed", "unconfirmed", "disputed", "interpretation"}


def utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Timestamp must be a nonempty ISO-8601 string with timezone")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def payload_hash(dossier: dict) -> str:
    """Hash all analyst inputs; the review itself is excluded to avoid recursion."""
    payload = {k: v for k, v in dossier.items() if k != "review"}
    return text_hash(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":"), allow_nan=False))


def canonical_url(value: str, synthetic: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A source URL is required")
    p = urlsplit(value.strip())
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise ValueError("Use a public http(s) URL without credentials")
    host = p.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local/private source URLs are not supported")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise ValueError("Nonpublic IP addresses are not supported")
    if not synthetic and (host.endswith((".example", ".test", ".invalid")) or
                          host in {"example.com", "example.net", "example.org"} or
                          host.endswith((".example.com", ".example.net", ".example.org"))):
        raise ValueError("Reserved example domains require synthetic mode")
    port = p.port  # raises on invalid ports
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and (p.scheme, port) not in {("http", 80), ("https", 443)}:
        netloc += f":{port}"
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and
             k.lower() not in {"fbclid", "gclid", "msclkid"}]
    return urlunsplit((p.scheme, netloc, p.path or "/", urlencode(sorted(query)), ""))


def band(score: int) -> str:
    if type(score) is not int or not 0 <= score <= 100:
        raise ValueError("Index must be an integer in [0, 100]")
    return "Low" if score <= 25 else "Moderate" if score <= 50 else "Strong" if score <= 75 else "Very strong"


def _validate(d: object, *, now: datetime | None = None) -> dict:
    """Validate structure and evidence references, not real-world truth or intent."""
    errors: list[dict] = []
    warnings: list[dict] = []
    blockers: list[str] = []
    def err(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})
    def warn(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})
    if not isinstance(d, dict):
        return {"engine_version": VERSION, "valid": False, "errors": [{"code": "ROOT", "message": "Dossier must be an object"}],
                "warnings": [], "release": "blocked", "nci": {"score": None, "state": "not_assessed"}}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    def timestamp(value: object, name: str, limit: datetime | None = None,
                  optional: bool = False) -> datetime | None:
        if value is None and optional:
            return None
        try:
            t = utc(value)
        except (ValueError, TypeError, AttributeError):
            err("TIMESTAMP", f"{name}: valid ISO-8601 timezone-aware timestamp required")
            return None
        if t > (limit or now):
            err("FUTURE_TIMESTAMP", f"{name}: timestamp is after the applicable cutoff")
        return t
    def obj(parent: dict, key: str) -> dict:
        value = parent.get(key)
        if not isinstance(value, dict):
            err("OBJECT", f"{key} must be an object")
            return {}
        return value
    def rows(parent: dict, key: str) -> list[dict]:
        value = parent.get(key)
        if not isinstance(value, list):
            err("ARRAY", f"{key} must be an array")
            return []
        if any(not isinstance(r, dict) for r in value):
            err("ROW", f"Every {key} entry must be an object")
        return [r for r in value if isinstance(r, dict)]
    def nonempty(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())
    def indexed(items: list[dict], what: str) -> dict:
        out = {}
        for item in items:
            key = item.get("id")
            if not isinstance(key, str) or not key:
                err("ID", f"{what} requires a nonempty string id")
            elif key in out:
                err("DUPLICATE_ID", f"Duplicate {what} id: {key}")
            else:
                out[key] = item
        return out
    if d.get("schema_version") != SCHEMA:
        err("SCHEMA_VERSION", f"Expected {SCHEMA}")
    if d.get("rubric_version") != RUBRIC:
        err("RUBRIC_VERSION", f"Expected {RUBRIC}")
    if d.get("mode") not in {"live", "synthetic"}:
        err("MODE", "mode must be live or synthetic")
    synthetic = d.get("mode") == "synthetic"
    if synthetic:
        warn("SYNTHETIC", "Fictional test input; never present as real-news research")
    event = obj(d, "event")
    for key in ("id", "title", "scope_description"):
        if not nonempty(event.get(key)):
            err("EVENT_FIELD", f"event.{key} is required")
    cutoff = timestamp(event.get("as_of"), "event.as_of")
    start = timestamp(event.get("window_start"), "event.window_start", cutoff)
    end = timestamp(event.get("window_end"), "event.window_end", cutoff)
    if start and end and start > end:
        err("WINDOW", "window_start is after window_end")
    topics = event.get("topics")
    if not isinstance(topics, list) or any(not isinstance(t, str) for t in topics):
        err("TOPICS", "event.topics must be an array of strings")
        topics = []
    if type(event.get("political_content")) is not bool:
        err("POLITICAL_SCOPE", "event.political_content must be explicitly true or false")
    political = event.get("political_content") is not False or bool(set(topics) & POLITICAL_TOPICS)
    if set(topics) & POLITICAL_TOPICS and event.get("political_content") is False:
        err("POLITICAL_SCOPE", "Political topic cannot be marked nonpolitical")
    analyst = obj(d, "analyst_run")
    for key in ("run_id", "agent_id", "record_ref"):
        if not nonempty(analyst.get(key)):
            err("ANALYST_RECEIPT", f"analyst_run.{key} is required")
    analyst_time = timestamp(analyst.get("completed_at"), "analyst_run.completed_at")
    if analyst_time and cutoff and analyst_time < cutoff:
        err("ANALYST_TIME", "Analyst completion precedes dossier cutoff")
    source_rows = rows(d, "sources")
    sources = indexed(source_rows, "source")
    seen_url: dict[str, str] = {}
    seen_text: dict[str, str] = {}
    usable_sources: set[str] = set()
    origin_ids: set[str] = set()
    for sid, s in sources.items():
        for key in ("title", "publisher", "origin_id", "origin_basis", "capture_ref"):
            if not nonempty(s.get(key)):
                err("SOURCE_FIELD", f"{sid}.{key} is required")
        if s.get("role") not in {"primary", "independent", "context", "social", "syndicated"}:
            err("SOURCE_ROLE", f"Invalid role for {sid}")
        availability = s.get("availability")
        if availability not in {"full_text", "excerpt", "metadata_only", "unavailable"}:
            err("AVAILABILITY", f"Invalid availability for {sid}")
        try:
            cu = canonical_url(s.get("url"), synthetic)
            if cu in seen_url:
                err("DUPLICATE_URL", f"{sid} duplicates {seen_url[cu]}; keep one source record")
            seen_url[cu] = sid
        except (ValueError, TypeError, AttributeError):
            err("SOURCE_URL", f"{sid} needs a valid public URL (example URLs only in synthetic mode)")
        rt = timestamp(s.get("retrieved_at"), f"{sid}.retrieved_at", cutoff)
        pt = timestamp(s.get("published_at"), f"{sid}.published_at", cutoff, optional=True)
        if rt and pt and pt > rt:
            err("SOURCE_DATE_ORDER", f"{sid} publication is after retrieval")
        if s.get("published_at") is None:
            warn("UNKNOWN_PUBLICATION", f"{sid}: publication time unknown, not inferred from retrieval")
        text = s.get("text")
        if not isinstance(text, str):
            err("SOURCE_TEXT", f"{sid}.text must be a string, including empty for inaccessible text")
            text = ""
        if s.get("sha256") != text_hash(text):
            err("SOURCE_HASH", f"{sid} capture hash does not match text")
        if availability in {"full_text", "excerpt"}:
            if not text.strip():
                err("SOURCE_TEXT", f"{sid} has no inspectable text")
            else:
                usable_sources.add(sid)
                if nonempty(s.get("origin_id")):
                    origin_ids.add(s["origin_id"])
                digest = text_hash(text)
                if digest in seen_text and s.get("origin_id") != sources[seen_text[digest]].get("origin_id"):
                    err("COPIED_CONTENT_ORIGIN", f"{sid} has identical text to {seen_text[digest]} but a different origin id")
                seen_text[digest] = sid
        else:
            warn("LIMITED_SOURCE", f"{sid} is {availability}; cannot support scored observations")
    evidence_rows = rows(d, "evidence")
    evidence = indexed(evidence_rows, "evidence")
    usable_evidence: set[str] = set()
    for eid, e in evidence.items():
        sid = e.get("source_id")
        if not isinstance(sid, str) or sid not in sources:
            err("EVIDENCE_SOURCE", f"{eid} references an unknown source")
            continue
        if not nonempty(e.get("locator")) or not nonempty(e.get("excerpt")):
            err("EVIDENCE_SPAN", f"{eid} needs a precise locator and exact excerpt")
            continue
        if e["excerpt"] not in str(sources[sid].get("text", "")):
            err("QUOTE_MISMATCH", f"{eid} excerpt is not in the captured text")
        elif sid not in usable_sources:
            err("UNREAD_EVIDENCE", f"{eid} references metadata-only or inaccessible content")
        else:
            usable_evidence.add(eid)
    def refs(value: object, where: str, require: bool = False) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            err("REFERENCES", f"{where} must be an array of evidence ids")
            return []
        if len(set(value)) != len(value):
            err("DUPLICATE_REFERENCE", f"{where} repeats an evidence id")
        for eid in value:
            if eid not in usable_evidence:
                err("UNUSABLE_REFERENCE", f"{where}: {eid} is not usable evidence")
        if require and not value:
            err("MISSING_EVIDENCE", f"{where} needs source evidence")
        return value
    claim_rows = rows(d, "claims")
    claims = indexed(claim_rows, "claim")
    material = 0
    evidence_linked = 0
    for cid, c in claims.items():
        if not nonempty(c.get("text")) or not nonempty(c.get("assessment")):
            err("CLAIM_TEXT", f"{cid} requires text and an assessment")
        if c.get("kind") not in {"event_fact", "presentation_observation", "interpretation"}:
            err("CLAIM_KIND", f"Invalid kind for {cid}")
        if c.get("status") not in FACT_STATUSES:
            err("CLAIM_STATUS", f"Invalid status for {cid}")
        if c.get("kind") == "interpretation" and c.get("status") != "interpretation":
            err("INTERPRETATION_STATUS", f"{cid}: an interpretation cannot be confirmed as a fact")
        support = refs(c.get("evidence_ids"), f"{cid}.evidence_ids", c.get("status") == "confirmed")
        contrary = refs(c.get("counterevidence_ids"), f"{cid}.counterevidence_ids", c.get("status") == "disputed")
        timestamp(c.get("as_of"), f"{cid}.as_of", cutoff)
        basis = c.get("verification_basis")
        if basis not in {"primary_record", "independent_corroboration", "direct_text", "unverified", "interpretation"}:
            err("VERIFICATION_BASIS", f"Invalid verification basis for {cid}")
        valid_support = [eid for eid in support if eid in usable_evidence]
        if c.get("status") == "confirmed":
            source_set = {evidence[eid]["source_id"] for eid in valid_support}
            if basis == "primary_record" and not any(sources[s]["role"] == "primary" for s in source_set):
                err("PRIMARY_SUPPORT", f"{cid}: no primary record linked")
            elif basis == "independent_corroboration" and len({sources[s].get("origin_id") for s in source_set}) < 2:
                err("INDEPENDENCE", f"{cid}: independent corroboration needs distinct documented origins")
            elif basis == "direct_text" and c.get("kind") != "presentation_observation":
                err("DIRECT_TEXT_SCOPE", f"{cid}: a statement in text confirms wording, not the underlying event")
            elif basis in {"unverified", "interpretation"}:
                err("CONFIRMED_BASIS", f"{cid}: confirmed status lacks an eligible basis")
        if c.get("kind") == "event_fact":
            material += 1
            if any(e in usable_evidence for e in support + contrary):
                evidence_linked += 1
    factor_rows = rows(d, "factors")
    factors: dict[int, dict] = {}
    assessed = 0
    subtotal = 0
    overlaps: dict[str, list[int]] = {}
    for f in factor_rows:
        fid = f.get("id")
        if type(fid) is not int or not 1 <= fid <= 20:
            err("FACTOR_ID", "Factor ids must be integers 1 through 20")
            continue
        if fid in factors:
            err("DUPLICATE_FACTOR", f"Duplicate factor {fid}")
            continue
        factors[fid] = f
        status = f.get("status")
        if status not in {"assessed", "unknown", "not_applicable", "descriptive_only"}:
            err("FACTOR_STATUS", f"Invalid status for factor {fid}")
        if not nonempty(f.get("reason")) or not nonempty(f.get("alternative_explanation")):
            err("FACTOR_REASON", f"Factor {fid} needs a rationale and an alternative explanation/check")
        score = f.get("score")
        if political and (score is not None or status == "assessed"):
            err("POLITICAL_NUMERIC", f"Factor {fid}: use descriptive observations, not political ratings")
        elif status == "assessed":
            if type(score) is not int or not 0 <= score <= 5:
                err("FACTOR_RANGE", f"Factor {fid} must have an integer score 0–5")
            else:
                assessed += 1
                subtotal += score
        elif score is not None:
            err("UNASSESSED_NUMBER", f"Factor {fid}: unknown/not-applicable/descriptive states require null")
        refs(f.get("evidence_ids"), f"factor {fid}.evidence_ids", status in {"assessed", "descriptive_only"})
        refs(f.get("counterevidence_ids"), f"factor {fid}.counterevidence_ids")
        groups = f.get("observation_groups")
        if not isinstance(groups, list) or any(not isinstance(x, str) or not x for x in groups):
            err("OBSERVATION_GROUP", f"Factor {fid} observation_groups must be a string array")
            groups = []
        if status == "assessed" and type(score) is int and score > 0 and not groups:
            err("OBSERVATION_GROUP", f"Factor {fid}: positive score needs an observation group")
        for group in groups:
            overlaps.setdefault(group, []).append(fid)
    if set(factors) != set(range(1, 21)):
        err("FACTOR_COMPLETENESS", "Include exactly one explicit state for each of the 20 factors")
    for group, ids in overlaps.items():
        if len(ids) > 1:
            warn("CORRELATED_FACTORS", f"Observation {group} appears in factors {ids}; do not treat as independent proof")
    hypotheses = indexed(rows(d, "hypotheses"), "hypothesis")
    if set(hypotheses) != set(HYPOTHESES):
        err("HYPOTHESES", "Include H1–H8, with unavailable evidence explicitly noted")
    for hid, h in hypotheses.items():
        if any(k in h for k in ("probability", "percent", "score", "rank", "winner")):
            err("HYPOTHESIS_PROBABILITY", "Hypotheses overlap; no numeric probabilities, rankings or winner fields")
        for key in ("assessment", "unresolved"):
            if not nonempty(h.get(key)):
                err("HYPOTHESIS_TEXT", f"{hid}.{key} is required")
        refs(h.get("evidence_for"), f"{hid}.evidence_for")
        refs(h.get("evidence_against"), f"{hid}.evidence_against")
    for item in rows(d, "timeline"):
        timestamp(item.get("at"), "timeline.at", cutoff)
        if not nonempty(item.get("description")):
            err("TIMELINE_TEXT", "Timeline description is required")
        refs(item.get("evidence_ids"), "timeline.evidence_ids", True)
    watchlist = d.get("watchlist")
    if not isinstance(watchlist, list) or any(not isinstance(x, str) for x in watchlist):
        err("WATCHLIST", "watchlist must be an array of strings")
    scope = obj(d, "scope_review")
    if scope.get("status") not in {"complete", "partial"}:
        err("SCOPE_STATUS", "scope_review.status must be complete or partial")
    if scope.get("scope_mode") not in {"cross_source", "single_source"}:
        err("SCOPE_MODE", "scope_mode must be cross_source or single_source")
    for key in ("corpus_note", "source_sufficiency_reason", "selection_method", "independence_check"):
        if not nonempty(scope.get(key)):
            err("SCOPE_NOTE", f"scope_review.{key} is required")
    for key in ("limitations", "material_gaps"):
        if not isinstance(scope.get(key), list) or any(not isinstance(x, str) for x in scope.get(key, [])):
            err("SCOPE_ARRAY", f"scope_review.{key} must be a string array")
    if scope.get("status") != "complete" or scope.get("material_gaps"):
        blockers.append("Research coverage is partial or material evidence gaps remain")
    if not usable_sources:
        blockers.append("No inspectable sources")
    if scope.get("scope_mode") == "cross_source" and len(origin_ids) < 2:
        blockers.append("Cross-source comparison has fewer than two documented source origins")
    if not material:
        blockers.append("No material event claims recorded")
    if material and evidence_linked < material:
        blockers.append("Some material claims have no inspected evidence record")
    review = obj(d, "review")
    mode = review.get("mode")
    if mode not in {"independent", "self_review", "none"}:
        err("REVIEW_MODE", "Review mode must be independent, self_review, or none")
    review_valid = False
    digest = None
    try:
        digest = payload_hash(d)
    except (TypeError, ValueError, OverflowError):
        err("NONFINITE_JSON", "Payload must be finite, JSON-serializable data")
    if mode != "none":
        for key in ("run_id", "agent_id", "record_ref", "input_sha256"):
            if not nonempty(review.get(key)):
                err("REVIEW_RECEIPT", f"review.{key} is required")
        review_time = timestamp(review.get("completed_at"), "review.completed_at")
        if review_time and analyst_time and review_time < analyst_time:
            err("REVIEW_TIME", "Review completion precedes analyst completion")
        if review.get("input_sha256") != digest:
            err("STALE_REVIEW", "Review does not cover the current analyst payload")
        if mode == "independent" and (review.get("agent_id") == analyst.get("agent_id") or
                                      review.get("run_id") == analyst.get("run_id")):
            err("FAKE_INDEPENDENCE", "Independent review requires a separate agent/context and run")
        if review.get("status") not in {"accepted", "changes_requested"}:
            err("REVIEW_STATUS", "Executed review must be accepted or changes_requested")
        findings = indexed(rows(review, "findings"), "finding")
        for fid, finding in findings.items():
            if finding.get("severity") not in {"blocker", "major", "minor"}:
                err("FINDING_SEVERITY", f"Invalid severity for {fid}")
            if type(finding.get("resolved")) is not bool or not nonempty(finding.get("issue")):
                err("FINDING", f"Finding {fid} needs issue and boolean resolved")
            if finding.get("resolved") and not nonempty(finding.get("resolution")):
                err("FINDING_RESOLUTION", f"Resolved finding {fid} needs an actual resolution")
            if not finding.get("resolved") and finding.get("severity") in {"blocker", "major"}:
                blockers.append(f"Unresolved reviewer finding {fid}")
        review_valid = (mode == "independent" and review.get("status") == "accepted" and
                        review.get("input_sha256") == digest and
                        review.get("agent_id") != analyst.get("agent_id") and
                        review.get("run_id") != analyst.get("run_id"))
    if not review_valid:
        blockers.append("Independent review has not accepted the current payload")
    if not political and assessed < 20:
        blockers.append("One or more factors remain unassessed; no normalized total")
    release = "blocked" if errors else "preliminary" if blockers else "reviewed"
    score = subtotal if release == "reviewed" and not political and assessed == 20 else None
    pct = lambda num, den: round(100 * num / den, 1) if den else None
    return {
        "engine_version": VERSION, "schema_version": SCHEMA, "rubric_version": RUBRIC,
        "valid": not errors, "mode": d.get("mode"), "payload_sha256": digest,
        "errors": errors, "warnings": warnings, "release": release,
        "release_reasons": list(dict.fromkeys(blockers)),
        "political_content": political,
        "review": {"mode": mode, "receipt_matches_payload": review_valid,
                   "receipt_authenticity": "Must be checked against actual tool/provider logs; not authenticated by this program"},
        "nci": {"state": "not_applicable" if political else "available" if score is not None else "not_assessed",
                "score": score, "maximum": 100, "band": band(score) if score is not None else None,
                "meaning": "Uncalibrated observed narrative-pressure rubric index for the inspected nonpolitical corpus; not a probability of falsehood, intent, or coordination",
                "political_rule": "Political coverage uses sourced descriptive evidence, not actor/choice ratings or narrative verdict percentages"},
        "metrics": {
            "material_claims": material, "evidence_linked_material_claims": evidence_linked,
            "material_claim_evidence_coverage_percent": pct(evidence_linked, material) if not errors else None,
            "assessed_factors": assessed, "factor_assessment_coverage_percent": pct(assessed, 20) if not errors and not political else None,
            "inspected_sources": len(usable_sources), "documented_origin_groups": len(origin_ids),
            "evidence_coverage_meaning": "Share of listed material claims with inspected evidence links; not share proved true, accuracy, or confidence",
        },
    }


def validate(d: object, *, now: datetime | None = None) -> dict:
    """Fail closed on malformed nested input; no unsafe numeric fallback."""
    try:
        return _validate(d, now=now)
    except (TypeError, KeyError, AttributeError, ValueError, OverflowError, RecursionError) as exc:
        return {
            "engine_version": VERSION, "valid": False,
            "errors": [{"code": "MALFORMED_STRUCTURE", "message": f"Malformed dossier structure ({type(exc).__name__}); no result released"}],
            "warnings": [], "release": "blocked", "release_reasons": ["Malformed input"],
            "nci": {"score": None, "state": "not_assessed"},
        }


def md(value: object) -> str:
    """Keep arbitrary input in literal prose, not active Markdown/HTML."""
    s = str(value).replace("\n", " ").replace("\r", " ")
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for char in ("\\", "`", "*", "_", "[", "]", "|", "#"):
        s = s.replace(char, "\\" + char)
    return s


def render(d: dict, result: dict) -> str:
    title = d.get("event", {}).get("title", "Untitled event")
    lines = [f"# Mike — {md(title)}", "", "*your Bull shhhh detector*", ""]
    if d.get("mode") == "synthetic":
        lines += ["**SYNTHETIC EXAMPLE — fictional evidence and simulated review receipts, not real news.**", ""]
    lines += [f"**Report state:** {md(result.get('release'))}",
              f"**Evidence cutoff:** {md(d.get('event', {}).get('as_of', 'unknown'))}", ""]
    if not result.get("valid"):
        lines += ["## Input issues", "The dossier has not passed validation; no assessment or score is released."]
        lines += [f"- {md(e['code'])}: {md(e['message'])}" for e in result.get("errors", [])]
        return "\n".join(lines) + "\n"
    m, n = result["metrics"], result["nci"]
    if result["political_content"]:
        lines += ["**Coverage mode:** Sourced factual and presentation analysis; no political actor, political choice, or intent rating.", ""]
    else:
        lines += [f"**Observed narrative-pressure index:** {n['score']}/100 — {n['band']}" if n["score"] is not None
                  else "**Observed narrative-pressure index:** Not assessed — no numeric verdict.",
                  "This is a rubric index, not a percentage chance of deception or falsehood.", ""]
    coverage = m["material_claim_evidence_coverage_percent"]
    lines += [f"**Material-claim evidence coverage:** {coverage}% ({m['evidence_linked_material_claims']}/{m['material_claims']})" if coverage is not None
              else "**Material-claim evidence coverage:** Not available.",
              "Coverage measures linked evidence, not truth or model confidence.",
              f"**Sources inspected:** {m['inspected_sources']} · **Documented origin groups:** {m['documented_origin_groups']}",
              f"**Review mode:** {md(result['review']['mode'])}; receipt identity requires actual execution logs.", ""]
    if result["release_reasons"]:
        lines += ["## What remains unresolved"] + [f"- {md(x)}" for x in result["release_reasons"]] + [""]
    evidence = {e["id"]: e for e in d["evidence"]}
    def links(eids: list[str]) -> str:
        sids = sorted({evidence[eid]["source_id"] for eid in eids if eid in evidence})
        return " ".join(f"[{md(sid)}](#source-{re.sub('[^a-zA-Z0-9-]', '-', sid).lower()})" for sid in sids)
    lines += ["## What the record says", "", "| Claim | Status | Assessment | Sources |", "|---|---|---|---|"]
    for c in d["claims"]:
        lines.append(f"| {md(c['text'])} | {md(c['status'])} | {md(c['assessment'])} | {links(c['evidence_ids'] + c['counterevidence_ids'])} |")
    lines += ["", "## Timeline", ""]
    for item in sorted(d["timeline"], key=lambda x: utc(x["at"])):
        lines.append(f"- {md(item['at'])}: {md(item['description'])} {links(item['evidence_ids'])}")
    lines += ["", "## Presentation and context observations", "", "| Dimension | Finding | Evidence |", "|---|---|---|"]
    for f in sorted(d["factors"], key=lambda x: x["id"]):
        label = FACTOR_NAMES[f["id"]-1]
        prefix = f"{f['score']}/5. " if n["score"] is not None else f"{f['status']}. "
        lines.append(f"| {label} | {md(prefix + f['reason'])} Alternative/check: {md(f['alternative_explanation'])} | {links(f['evidence_ids'] + f['counterevidence_ids'])} |")
    lines += ["", "## Competing explanations", "The hypotheses can overlap. No probabilities or winning explanation are assigned automatically.", ""]
    for h in d["hypotheses"]:
        lines += [f"### {h['id']} — {md(HYPOTHESES[h['id']])}",
                  f"{md(h['assessment'])} {links(h['evidence_for'] + h['evidence_against'])}",
                  f"Unresolved: {md(h['unresolved'])}", ""]
    lines += ["## Independent review record", ""]
    for f in d["review"].get("findings", []):
        lines.append(f"- {md(f['id'])}: {md(f['issue'])} Resolution: {md(f.get('resolution', 'unresolved'))}")
    if not d["review"].get("findings"):
        lines.append("No findings recorded. An empty list is not proof that a separate review executed.")
    lines += ["", "## What would change the analysis", ""] + [f"- {md(x)}" for x in d["watchlist"]]
    lines += ["", "## Scope and limitations", md(d["scope_review"]["corpus_note"]), ""]
    lines += [f"- {md(x)}" for x in d["scope_review"]["limitations"]]
    lines += [f"- {md(w['message'])}" for w in result["warnings"] if w["code"] != "SYNTHETIC"]
    lines += ["", "## Sources", ""]
    for s in d["sources"]:
        anchor = re.sub("[^a-zA-Z0-9-]", "-", s["id"]).lower()
        safe_url = canonical_url(s["url"], d["mode"] == "synthetic").replace("(", "%28").replace(")", "%29")
        lines += [f"### Source {anchor.removeprefix('source-')}",
                  f"[{md(s['title'])}]({safe_url}) — {md(s['publisher'])}",
                  f"Published: {md(s.get('published_at') or 'unknown')}; inspected: {md(s['retrieved_at'])}; availability: {md(s['availability'])}.",
                  f"Origin: {md(s['origin_id'])}. {md(s['origin_basis'])}", ""]
    lines += ["---", f"Rubric {RUBRIC}; engine {VERSION}. No claims of calibrated manipulation-detection accuracy."]
    return "\n".join(lines) + "\n"


def blank_dossier() -> dict:
    """Draft only: intentionally cannot produce a score before research/review."""
    return {"schema_version": SCHEMA, "rubric_version": RUBRIC, "mode": "live",
        "event": {"id": "", "title": "", "as_of": "", "window_start": "", "window_end": "", "topics": [],
                  "scope_description": "", "political_content": None},
        "analyst_run": {"run_id": "", "agent_id": "", "record_ref": "", "completed_at": ""},
        "scope_review": {"status": "partial", "scope_mode": "cross_source", "corpus_note": "",
                         "source_sufficiency_reason": "", "selection_method": "", "independence_check": "",
                         "limitations": [], "material_gaps": ["Research not performed"]},
        "sources": [], "evidence": [], "claims": [], "timeline": [],
        "factors": [{"id": i, "status": "unknown", "score": None, "reason": "Not researched",
                     "evidence_ids": [], "counterevidence_ids": [], "alternative_explanation": "Not evaluated",
                     "observation_groups": []} for i in range(1, 21)],
        "hypotheses": [{"id": h, "assessment": "Not researched; not a conclusion", "evidence_for": [],
                        "evidence_against": [], "unresolved": "Evidence gathering and critique pending"} for h in HYPOTHESES],
        "review": {"mode": "none", "status": "unavailable", "findings": []}, "watchlist": []}


def strict_load(path: Path) -> dict:
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Dossier exceeds the 20 MB local safety limit; split captures, not findings")
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError(f"Duplicate JSON key: {k}")
            out[k] = v
        return out
    def constant(v):
        raise ValueError(f"Nonfinite JSON number: {v}")
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("validate", "hash", "template"))
    p.add_argument("input", nargs="?", type=Path)
    p.add_argument("--json-out", type=Path)
    p.add_argument("--report-out", type=Path)
    p.add_argument("--overwrite", action="store_true", help="Explicitly replace existing output files")
    args = p.parse_args()
    try:
        if args.command != "template" and args.input is None:
            raise ValueError("An input dossier is required")
        outpaths = [x for x in (args.json_out, args.report_out) if x is not None]
        resolved = [x.resolve() for x in outpaths]
        if len(set(resolved)) != len(resolved):
            raise ValueError("Output paths must be distinct")
        for dest in outpaths:
            if args.input and dest.resolve() == args.input.resolve():
                raise ValueError("An output must not overwrite the input dossier")
            if dest.exists() and not args.overwrite:
                raise ValueError(f"Output exists: {dest}; choose a new path or --overwrite")
        if args.command == "template":
            result = blank_dossier()
            content = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
            if args.json_out:
                args.json_out.write_text(content, encoding="utf-8")
            else:
                print(content, end="")
            return 0
        d = strict_load(args.input)
        if args.command == "hash":
            print(payload_hash(d))
            return 0
        result = validate(d)
        content = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.json_out:
            args.json_out.write_text(content, encoding="utf-8")
        if args.report_out:
            args.report_out.write_text(render(d, result), encoding="utf-8")
        print(content, end="")
        return 0 if result["valid"] else 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        print(f"Mike input/output error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
