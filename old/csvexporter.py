# newrelic_dashboard_updater/utils/csv_exporter.py

import csv
from pathlib import Path
from newrelic_dashboard_updater.utils.logger import logger

def export_results_to_csv(results, filename="output/validated_results.csv"):
    Path("output").mkdir(exist_ok=True)

    with open(filename, mode='w', newline='') as f:
        fieldnames = ["dashboard_guid", "page_name", "widget_name", "original_query", "result"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for dashboard in results:
            guid = dashboard["dashboard_guid"]
            data = dashboard["result"]
            for page in data.get("pages", []):
                for widget in page.get("widgets", []):
                    cfg = widget.get("rawConfiguration", {})
                    name = cfg.get("title") or cfg.get("name", "")
                    orig = cfg.get("nrqlQueries", [{}])[0].get("query", "")
                    result = widget.get("validation", "NA")

                    writer.writerow({
                        "dashboard_guid": guid,
                        "page_name": page.get("name", ""),
                        "widget_name": name,
                        "original_query": orig,
                        "result": result
                    })
    logger.info(f"Saved CSV: {filename}")


def export_detailed_csv(results):
    Path("output").mkdir(exist_ok=True)

    dashboards_by_account = {}

    for dashboard in results:
        guid = dashboard["dashboard_guid"]
        data = dashboard["result"]
        account_name = data.get("permissions", [{}])[0].get("accountName", "unknown")
        dashboards_by_account.setdefault(account_name, []).append((guid, data))

    for account_name, dashboards in dashboards_by_account.items():
        safe_name = account_name.replace("/", "_").replace(" ", "_")
        filename = f"output/{safe_name}_detailed_nrql_validation.csv"
        with open(filename, mode='w', newline='') as f:
            fieldnames = [
                "account_name", "dashboard_name", "dashboard_guid", "dashboard_visibility",
                "page_name", "page_guid", "widget_title", "widget_id", "layout", "variables",
                "old_query", "new_query", "validation_result"
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for guid, data in dashboards:
                dashboard_name = data.get("name", "")
                visibility = "private" if data.get("permissions", []) else "public"
                dashboard_variables = data.get("variables", [])

                for page in data.get("pages", []):
                    page_name = page.get("name", "")
                    page_guid = page.get("guid", "")
                    for widget in page.get("widgets", []):
                        cfg = widget.get("rawConfiguration", {})
                        name = cfg.get("title") or cfg.get("name", "")
                        old = cfg.get("nrqlQueries", [{}])[0].get("query", "")
                        new = widget.get("validation", "NA")
                        validation = "NA" if new == "NA" else ("failed" if new == "failed" else "success")
                        layout = cfg.get("layout", {}) or widget.get("layout", {})
                        layout_str = f"row={layout.get('row', '')}, col={layout.get('column', '')}, width={layout.get('width', '')}, height={layout.get('height', '')}"

                        writer.writerow({
                            "account_name": account_name,
                            "dashboard_name": dashboard_name,
                            "dashboard_guid": guid,
                            "dashboard_visibility": visibility,
                            "page_name": page_name,
                            "page_guid": page_guid,
                            "widget_title": name,
                            "widget_id": widget.get("id", ""),
                            "layout": layout_str,
                            "variables": str(dashboard_variables),
                            "old_query": old,
                            "new_query": new if new not in ["NA", "failed"] else "",
                            "validation_result": validation
                        })
        logger.info(f"Saved detailed CSV: {filename}")
