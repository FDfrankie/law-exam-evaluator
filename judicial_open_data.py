"""Discover and download official Judicial Yuan open-data resources."""

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import RAW_DATA_DIR


BASE_URL = "https://opendata.judicial.gov.tw"
DEFAULT_CATEGORIES = ("051", "052", "053", "054")
USER_AGENT = "LawExamData/1.0 (Judicial Yuan open-data client)"
REQUEST_TIMEOUT = (10, 120)
DOWNLOAD_DIR = RAW_DATA_DIR / "judicial_open_data"
MANIFEST_PATH = RAW_DATA_DIR / "judicial_open_data_manifest.sqlite3"
MOJ_LAW_RESOURCE = {
    "file_set_id": "moj-ch-law-json",
    "dataset_id": "moj-national-laws",
    "category_no": "MOJ",
    "category_name": "Chinese statutes",
    "title": "Taiwan national laws",
    "resource_format": "ZIP",
    "description": "Official bulk JSON export; ZIP includes schema.csv.",
    "download_url": "https://law.moj.gov.tw/api/ch/law/json",
}
MOJ_ORDER_RESOURCE = {
    "file_set_id": "moj-ch-order-json",
    "dataset_id": "moj-national-orders",
    "category_no": "MOJ",
    "category_name": "Orders",
    "title": "Taiwan national orders",
    "resource_format": "ZIP",
    "description": "Official bulk JSON export; ZIP includes schema.csv.",
    "download_url": "https://law.moj.gov.tw/api/ch/order/json",
}


def open_manifest() -> sqlite3.Connection:
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(MANIFEST_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS resources (
            file_set_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            category_no TEXT NOT NULL,
            category_name TEXT NOT NULL,
            title TEXT NOT NULL,
            resource_format TEXT NOT NULL,
            description TEXT NOT NULL,
            download_url TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'catalogued',
            local_path TEXT,
            byte_count INTEGER,
            sha256 TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            error TEXT
        )
        """
    )
    connection.commit()
    return connection


def fetch_json(session: requests.Session, url: str) -> Any:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_catalog(session: requests.Session, categories: tuple[str, ...]) -> list[dict[str, str]]:
    known_categories = fetch_json(session, f"{BASE_URL}/data/api/rest/categories")
    names = {
        str(item["categoryNo"]): str(item["categoryName"])
        for item in known_categories
        if "categoryNo" in item and "categoryName" in item
    }

    resources: list[dict[str, str]] = []
    for category_no in categories:
        if category_no not in names:
            raise ValueError(f"Unknown Judicial Yuan category: {category_no}")

        url = f"{BASE_URL}/data/api/rest/categories/{quote(category_no)}/resources"
        datasets = fetch_json(session, url)
        for dataset in datasets:
            for fileset in dataset.get("filesets", []):
                file_set_id = str(fileset.get("fileSetId", "")).strip()
                if not file_set_id:
                    continue
                resources.append(
                    {
                        "file_set_id": file_set_id,
                        "dataset_id": str(dataset.get("datasetId", "")),
                        "category_no": category_no,
                        "category_name": str(dataset.get("categoryName", names[category_no])),
                        "title": str(dataset.get("title", "")),
                        "resource_format": str(fileset.get("resourceFormat", "UNKNOWN")).upper(),
                        "description": str(fileset.get("resourceDescription", "")),
                        "download_url": f"{BASE_URL}/api/FilesetLists/{quote(file_set_id)}/file",
                    }
                )

    return resources


def save_catalog(connection: sqlite3.Connection, resources: list[dict[str, str]]) -> None:
    connection.executemany(
        """
        INSERT INTO resources (
            file_set_id, dataset_id, category_no, category_name, title,
            resource_format, description, download_url
        ) VALUES (
            :file_set_id, :dataset_id, :category_no, :category_name, :title,
            :resource_format, :description, :download_url
        )
        ON CONFLICT(file_set_id) DO UPDATE SET
            dataset_id = excluded.dataset_id,
            category_no = excluded.category_no,
            category_name = excluded.category_name,
            title = excluded.title,
            resource_format = excluded.resource_format,
            description = excluded.description,
            download_url = excluded.download_url,
            updated_at = CURRENT_TIMESTAMP
        """,
        resources,
    )
    connection.commit()


def get_downloaded_ids(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT file_set_id FROM resources WHERE status = 'downloaded'"
    )
    return {row[0] for row in rows}


def download_resource(
    session: requests.Session,
    connection: sqlite3.Connection,
    resource: dict[str, str],
) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "".join(char for char in resource["resource_format"].lower() if char.isalnum())
    target = DOWNLOAD_DIR / f"{resource['file_set_id']}.{suffix or 'bin'}"
    partial = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    byte_count = 0

    try:
        with session.get(
            resource["download_url"],
            stream=True,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                raise ValueError("The download endpoint returned HTML instead of a data file")

            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)
                        digest.update(chunk)
                        byte_count += len(chunk)

        if byte_count == 0:
            raise ValueError("The downloaded resource is empty")

        partial.replace(target)
        connection.execute(
            """
            UPDATE resources
            SET status = 'downloaded', local_path = ?, byte_count = ?, sha256 = ?,
                updated_at = CURRENT_TIMESTAMP, error = NULL
            WHERE file_set_id = ?
            """,
            (str(target), byte_count, digest.hexdigest(), resource["file_set_id"]),
        )
        connection.commit()
        return target
    except Exception as error:
        partial.unlink(missing_ok=True)
        connection.execute(
            "UPDATE resources SET status = 'error', updated_at = CURRENT_TIMESTAMP, error = ? WHERE file_set_id = ?",
            (str(error)[:1000], resource["file_set_id"]),
        )
        connection.commit()
        raise


def summarize(resources: list[dict[str, str]]) -> None:
    counts: dict[tuple[str, str], int] = {}
    for resource in resources:
        key = (resource["category_name"], resource["resource_format"])
        counts[key] = counts.get(key, 0) + 1

    print(f"Catalogued resources: {len(resources)}")
    for (category, resource_format), count in sorted(counts.items()):
        print(f"{category} | {resource_format}: {count}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory and download public Judicial Yuan datasets."
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=list(DEFAULT_CATEGORIES),
        help="Judicial Yuan category numbers (default: 051 052 053 054).",
    )
    parser.add_argument(
        "--download-limit",
        type=int,
        default=0,
        help="Download at most this many resources; 0 lists only, -1 downloads all.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.5,
        help="Pause between resource downloads to reduce load on the source.",
    )
    parser.add_argument(
        "--show-resources",
        action="store_true",
        help="Print each resource and its format after cataloguing.",
    )
    parser.add_argument(
        "--include-laws",
        action="store_true",
        help="Include the Ministry of Justice bulk exports of Chinese laws and orders.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.download_limit < -1:
        raise ValueError("--download-limit must be -1, 0, or a positive integer")
    if args.delay_seconds < 0:
        raise ValueError("--delay-seconds cannot be negative")

    session = requests.Session()
    session.verify = os.getenv("LEGAL_SSL_VERIFY", "true").lower() in ("true", "1", "yes")
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    connection = open_manifest()

    try:
        resources = get_catalog(session, tuple(args.categories))
        if args.include_laws:
            resources.extend((MOJ_LAW_RESOURCE, MOJ_ORDER_RESOURCE))
        save_catalog(connection, resources)
        summarize(resources)

        if args.show_resources:
            for resource in resources:
                print(
                    f"{resource['file_set_id']} | {resource['resource_format']} | "
                    f"{resource['category_name']} | {resource['title']} | {resource['description']}"
                )

        if args.download_limit == 0:
            print(f"Manifest: {MANIFEST_PATH}")
            print("No files downloaded. Pass --download-limit N to download a small batch, or -1 for all.")
            return 0

        downloaded_ids = get_downloaded_ids(connection)
        pending = [resource for resource in resources if resource["file_set_id"] not in downloaded_ids]
        if args.download_limit > 0:
            pending = pending[: args.download_limit]

        for index, resource in enumerate(pending, start=1):
            try:
                target = download_resource(session, connection, resource)
                print(f"[{index}/{len(pending)}] Saved {resource['file_set_id']} to {target}")
            except Exception as error:
                print(f"[{index}/{len(pending)}] Failed {resource['file_set_id']}: {error}", file=sys.stderr)
            if index < len(pending):
                time.sleep(args.delay_seconds)

        print(f"Manifest: {MANIFEST_PATH}")
        print(f"Download directory: {DOWNLOAD_DIR}")
        return 0
    finally:
        connection.close()
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())