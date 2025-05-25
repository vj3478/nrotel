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
