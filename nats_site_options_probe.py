#!/usr/bin/env python3
"""
Standalone NATs v5 site/options probe.

This tests whether NATs can return join options by site id without a tracking
code. It is intentionally not wired into Django, so it can run with only API
credentials and a site id.

Examples:
  python scripts/nats_site_options_probe.py \
	--base-url https://your-nats-domain.example \
	--api-username your_api_user \
	--api-key your_api_key \
	--site-id 2

  NATS_BASE_URL=https://your-nats-domain.example \
  NATS_API_USERNAME=your_api_user \
  NATS_API_KEY=your_api_key \
  NATS_SITE_ID=2 \
  python scripts/nats_site_options_probe.py

WARNING: Do not commit filled-in secrets or paste unredacted output into public
places. This script redacts credentials in its own output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.parse import urljoin

import requests


DEFAULT_PATHS = ("v1/site/options", "site/options")
DEFAULT_TIMEOUT_SECONDS = 30


def _env(name: str, default: str = "") -> str:
	return (os.environ.get(name) or default).strip()


def _redact(value: str) -> str:
	value = str(value or "")
	if not value:
		return ""
	if len(value) <= 8:
		return "[set]"
	return f"{value[:4]}...{value[-4:]}"


def _build_api_url(base_url: str, path: str) -> str:
	base = str(base_url or "").strip().rstrip("/")
	if base.endswith("/api"):
		base = base[:-4]
	return urljoin(f"{base}/api/", path.strip().lstrip("/"))


def _json_or_text(response: requests.Response) -> Any:
	try:
		return response.json()
	except ValueError:
		return {"raw_text": response.text}


def _option_items(raw: Any) -> list[dict[str, Any]]:
	if not isinstance(raw, dict):
		return []
	candidates: list[Any] = [
		raw.get("options"),
		raw.get("full_options"),
		raw.get("join_options"),
	]
	data = raw.get("data")
	if isinstance(data, dict):
		candidates.extend(
			[
				data.get("options"),
				data.get("full_options"),
				data.get("join_options"),
				data.get("data"),
			]
		)
	candidates.append(data)

	for candidate in candidates:
		if isinstance(candidate, list):
			return [item for item in candidate if isinstance(item, dict)]
		if isinstance(candidate, dict):
			items = []
			for key, value in candidate.items():
				if not isinstance(value, dict):
					continue
				item = dict(value)
				item.setdefault("optionid", key)
				items.append(item)
			if items:
				return items
	return []


def _summary(raw: Any) -> dict[str, Any]:
	options = _option_items(raw)
	site = raw.get("site") if isinstance(raw, dict) else None
	return {
		"success_field": raw.get("success") if isinstance(raw, dict) else None,
		"total_count": raw.get("total_count") if isinstance(raw, dict) else None,
		"count_field": raw.get("count") if isinstance(raw, dict) else None,
		"site": {
			"siteid": site.get("siteid"),
			"name": site.get("name"),
			"site": site.get("site"),
		}
		if isinstance(site, dict)
		else None,
		"options_found": len(options),
		"sample_options": [
			{
				"optionid": item.get("optionid"),
				"siteid": item.get("siteid"),
				"deleted": item.get("deleted"),
				"enabled": item.get("enabled"),
				"name": (item.get("details") or {}).get("name")
				if isinstance(item.get("details"), dict)
				else item.get("name"),
			}
			for item in options[:5]
		],
	}


def _parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Probe NATs GET /site/options without a tracking code.",
	)
	parser.add_argument("--base-url", default=_env("NATS_BASE_URL"))
	parser.add_argument("--api-username", default=_env("NATS_API_USERNAME"))
	parser.add_argument("--api-key", default=_env("NATS_API_KEY"))
	parser.add_argument("--site-id", default=_env("NATS_SITE_ID"))
	parser.add_argument(
		"--path",
		action="append",
		dest="paths",
		help=(
			"Endpoint path to try, relative to /api. Can be passed more than "
			"once. Defaults to v1/site/options, then site/options."
		),
	)
	parser.add_argument(
		"--timeout",
		type=int,
		default=int(_env("NATS_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
	)
	parser.add_argument("--deleted", default=_env("NATS_OPTIONS_DELETED", "1"))
	parser.add_argument("--special", default=_env("NATS_OPTIONS_SPECIAL", "0"))
	parser.add_argument("--formatted", default=_env("NATS_OPTIONS_FORMATTED", "0"))
	parser.add_argument(
		"--show-tour-customized",
		default=_env("NATS_OPTIONS_SHOW_TOUR_CUSTOMIZED", "1"),
	)
	parser.add_argument(
		"--option-type-id",
		default=_env("NATS_OPTIONS_OPTION_TYPE_ID", "0"),
	)
	parser.add_argument("--start", default=_env("NATS_OPTIONS_START", "0"))
	parser.add_argument("--count", default=_env("NATS_OPTIONS_COUNT", "100"))
	parser.add_argument(
		"--print-raw",
		action="store_true",
		help="Print the full parsed response JSON for each attempted path.",
	)
	return parser.parse_args()


def main() -> int:
	args = _parse_args()
	missing = [
		name
		for name, value in (
			("--base-url or NATS_BASE_URL", args.base_url),
			("--api-username or NATS_API_USERNAME", args.api_username),
			("--api-key or NATS_API_KEY", args.api_key),
			("--site-id or NATS_SITE_ID", args.site_id),
		)
		if not str(value or "").strip()
	]
	if missing:
		print("Missing required values:", ", ".join(missing), file=sys.stderr)
		return 2

	paths = tuple(args.paths or DEFAULT_PATHS)
	params = {
		"siteid": str(args.site_id),
		"deleted": str(args.deleted),
		"special": str(args.special),
		"formatted": str(args.formatted),
		"show_tour_customized": str(args.show_tour_customized),
		"option_type_id": str(args.option_type_id),
		"start": str(args.start),
		"count": str(args.count),
	}
	headers = {
		"api-key": str(args.api_key),
		"api-username": str(args.api_username),
	}

	print("=== NATs site/options probe ===")
	print(
		json.dumps(
			{
				"base_url": args.base_url.rstrip("/"),
				"paths": paths,
				"params": params,
				"headers": {
					"api-key": _redact(headers["api-key"]),
					"api-username": _redact(headers["api-username"]),
				},
				"sends_tracking_code": False,
			},
			indent=2,
			sort_keys=True,
		)
	)

	last_error = ""
	for path in paths:
		url = _build_api_url(args.base_url, path)
		request = requests.Request("GET", url, params=params, headers=headers)
		prepared = request.prepare()

		print(f"\n=== GET {path} ===")
		print(f"Prepared URL: {prepared.url}")
		try:
			response = requests.Session().send(prepared, timeout=args.timeout)
		except requests.RequestException as exc: 
			last_error = str(exc)
			print(f"Request failed: {exc}")
			continue

		raw = _json_or_text(response)
		success = response.ok and not (
			isinstance(raw, dict) and raw.get("success") is False
		)
		print(
			json.dumps(
				{
					"http_status": response.status_code,
					"reason": response.reason,
					"response_summary": _summary(raw),
					"treated_as_success": success,
				},
				indent=2,
				sort_keys=True,
			)
		)
		if args.print_raw:
			print("=== RAW RESPONSE ===")
			print(json.dumps(raw, indent=2, sort_keys=True))

		if success:
			return 0

		if isinstance(raw, dict):
			last_error = str(raw.get("message") or raw.get("error") or "")
		if response.status_code != 404:
			break

	if last_error:
		print(f"\nNo attempted path succeeded. Last error: {last_error}", file=sys.stderr)
	else:
		print("\nNo attempted path succeeded.", file=sys.stderr)
	return 1


if __name__ == "__main__":
	raise SystemExit(main())
