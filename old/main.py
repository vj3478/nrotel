import argparse
import asyncio
from newrelic_dashboard_updater.graphql.dashboard_fetcher import fetch_dashboard_guids, fetch_dashboards_json_async
from newrelic_dashboard_updater.graphql.query_validator import process_dashboard_widgets, write_dashboard_summary_csv
from newrelic_dashboard_updater.utils.logger import setup_logger
from newrelic_dashboard_updater.utils.mapper_loader import load_mapper
from newrelic_dashboard_updater.utils.csv_exporter import export_results_to_csv, export_detailed_csv
from newrelic_dashboard_updater.utils.file_ops import load_dashboard_json
from newrelic_dashboard_updater.config import ACCOUNT_IDS, API_KEY

logger = setup_logger()

def parse_args():
    parser = argparse.ArgumentParser(description="New Relic Dashboard Updater")
    parser.add_argument("--mode", choices=["download", "validate", "update", "validate-only", "dry-run"], required=True, help="Execution mode")
    parser.add_argument("--guid", help="Run for a single dashboard GUID")
    return parser.parse_args()

async def validate_and_update_dashboards(guids, mode):
    results = []
    summary = []
    mapping_rules = load_mapper("mapping_rules.json")

    for guid in guids:
        logger.info(f"Processing dashboard: {guid}")
        dashboard = load_dashboard_json(guid)
        if not dashboard:
            continue

        summary_result = await process_dashboard_widgets(dashboard, mapping_rules, mode=mode)
        summary.append(summary_result)
        results.append({"dashboard_guid": guid, "result": dashboard})

    write_dashboard_summary_csv(summary)
    return results

async def main():
    args = parse_args()
    mode = args.mode
    single_guid = args.guid

    if mode == "download":
        if single_guid:
            logger.info(f"Downloading single dashboard {single_guid}")
            await fetch_dashboards_json_async(API_KEY, [single_guid], mode="download")
        else:
            guids = await fetch_dashboard_guids(API_KEY, ACCOUNT_IDS)
            await fetch_dashboards_json_async(API_KEY, guids, mode="download")

    elif mode in ["validate", "update", "validate-only", "dry-run"]:
        if single_guid:
            logger.info(f"Running mode '{mode}' for dashboard {single_guid}")
            await fetch_dashboards_json_async(API_KEY, [single_guid], mode="validate")
            run_mode = "validate" if mode in ["validate-only", "dry-run"] else mode
            results = await validate_and_update_dashboards([single_guid], mode=run_mode)
        else:
            guids = await fetch_dashboard_guids(API_KEY, ACCOUNT_IDS)
            await fetch_dashboards_json_async(API_KEY, guids, mode="validate")
            run_mode = "validate" if mode in ["validate-only", "dry-run"] else mode
            results = await validate_and_update_dashboards(guids, mode=run_mode)

        if mode == "dry-run":
            logger.info("Dry run complete. No dashboard queries were updated.")

        export_results_to_csv(results)
        export_detailed_csv(results)

if __name__ == "__main__":
    asyncio.run(main())
