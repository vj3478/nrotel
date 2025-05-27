import os
import csv
import json
import asyncio
import aiohttp
import argparse
import re
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
from tqdm import tqdm
import logging
from typing import Optional, List, Dict, Any
import ssl
import certifi

# Custom exceptions
class RateLimitError(Exception):
    pass

class GraphQLError(Exception):
    pass

# Configuration
API_KEY = os.getenv("NEW_RELIC_API_KEY", "REPLACE_ME")
ACCOUNT_IDS = [12345678, 87654321]  # Replace with actual account IDs
MAPPER_FILE = "span_to_metric_mapper.json"
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
LOGS_DIR = Path("logs")

# Query Configuration
BLOCK_KEYWORDS = ["DROP TABLE", "DELETE FROM", "eval(", "customBlockedMetric"]
SKIP_KEYWORDS = ["facet case", "complexJoin", "unsupportedFunction"]

# API Configuration
API_BASE_URL = "https://api.newrelic.com/graphql"
API_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
BATCH_SIZE = 25  # Number of queries to validate in one batch
MAX_RESULTS = 1000  # Maximum number of results to process
MAX_LOG_AGE_DAYS = 7  # Maximum age of log files to keep
MAX_TOTAL_RETRY_TIME = 300  # 5 minutes maximum retry time

def setup_logger() -> logging.Logger:
    """Configure and return a logger instance with proper error handling."""
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        process_id = os.getpid()
        log_file = LOGS_DIR / f"dashboard_updater_{timestamp}_{process_id}.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(__name__)
    except Exception as e:
        print(f"Failed to setup logger: {e}")
        # Fallback to basic logging
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)

logger = setup_logger()

def log_error(error: Exception, context: Optional[str] = None) -> None:
    """Log an error with context information."""
    error_msg = f"Error: {str(error)}"
    if context:
        error_msg += f" | Context: {context}"
    logger.error(error_msg, exc_info=True)

def cleanup_old_logs() -> None:
    """Clean up old log files."""
    try:
        current_time = datetime.now()
        for log_file in LOGS_DIR.glob("*.log"):
            file_age = current_time - datetime.fromtimestamp(log_file.stat().st_mtime)
            if file_age.days > MAX_LOG_AGE_DAYS:
                log_file.unlink()
                logger.info(f"Cleaned up old log file: {log_file}")
    except Exception as e:
        log_error(e, "Error cleaning up old logs")

def validate_mapper(mapper: Dict[str, str]) -> Dict[str, str]:
    """Validate mapper file format."""
    if not isinstance(mapper, dict):
        raise ValueError("Mapper must be a dictionary")
    for old, new in mapper.items():
        if not isinstance(old, str) or not isinstance(new, str):
            raise ValueError("Mapper keys and values must be strings")
    return mapper

def validate_inputs(mode: str, single_guid: Optional[str] = None) -> None:
    """Validate input parameters with comprehensive checks."""
    if mode not in ["download", "validate", "update"]:
        raise ValueError(f"Invalid mode: {mode}")
        
    if single_guid and not re.match(r'^[A-Za-z0-9-]+$', single_guid):
        raise ValueError(f"Invalid GUID format: {single_guid}")
        
    if not API_KEY or API_KEY == "REPLACE_ME":
        raise ValueError("NEW_RELIC_API_KEY environment variable not set")
        
    if not ACCOUNT_IDS or ACCOUNT_IDS == [12345678, 87654321]:
        raise ValueError("ACCOUNT_IDS not properly configured")
        
    if not Path(MAPPER_FILE).exists():
        raise ValueError(f"Mapper file not found: {MAPPER_FILE}")
        
    # Validate directories
    for directory in [DATA_DIR, OUTPUT_DIR, LOGS_DIR]:
        try:
            directory.mkdir(exist_ok=True)
            if not os.access(directory, os.W_OK):
                raise ValueError(f"Cannot write to directory: {directory}")
        except Exception as e:
            raise ValueError(f"Directory error for {directory}: {e}")

def load_mapper() -> Dict[str, str]:
    """Load mapping rules from JSON file."""
    if Path(MAPPER_FILE).exists():
        with open(MAPPER_FILE) as f:
            return validate_mapper(json.load(f))
    return {}

def escape_query(query: str) -> str:
    """Properly escape a query for GraphQL."""
    # First escape quotes
    query = query.replace('"', '\\"')
    query = query.replace("'", "\\'")
    # Then escape backslashes
    query = query.replace("\\", "\\\\")
    # Finally normalize whitespace
    query = re.sub(r'\s+', ' ', query).strip()
    return query

def get_query_from_widget(widget: Dict[str, Any]) -> Optional[str]:
    """Safely extract query from widget configuration."""
    cfg = widget.get("rawConfiguration", {})
    query_block = cfg.get("nrqlQueries", [])
    if not query_block or not isinstance(query_block, list):
        return None
    return query_block[0].get("query") if query_block else None

def validate_widget_for_update(widget: Dict[str, Any]) -> bool:
    """Validate widget has all required fields for update."""
    required_fields = ["id", "rawConfiguration", "layout", "visualization"]
    missing_fields = [field for field in required_fields if not widget.get(field)]
    
    if missing_fields:
        logger.warning(f"Widget missing required fields: {missing_fields}")
        return False
        
    if not widget["rawConfiguration"].get("nrqlQueries"):
        logger.warning("Widget missing nrqlQueries configuration")
        return False
        
    return True

def apply_mapping(query: str, mapping: Dict[str, str]) -> str:
    """Apply mapping rules to queries."""
    for old, new in mapping.items():
        query = query.replace(old, new)
    return query

def replace_variables(query: str, config: Dict[str, Any]) -> str:
    """Replace dashboard variables in queries."""
    variables = config.get("variables", {})
    for key, val in variables.items():
        try:
            if isinstance(val, dict):
                val = val.get("value")
                if val is None:
                    val = val.get("defaultValues", [])
                if val is None:
                    logger.warning(f"No usable value found for variable {key}")
                    continue
            if isinstance(val, list):
                val = ", ".join(f"'{v}'" if not isinstance(v, (int, float)) else str(v) for v in val)
            else:
                val = f"'{val}'" if isinstance(val, str) else str(val)
            query = query.replace(f"{{{key}}}", val)
        except Exception as e:
            logger.warning(f"Failed to resolve variable {{{key}}}: {e}")
            continue
    return query

def normalize_query(query: str) -> str:
    """Normalize query formatting."""
    return re.sub(r"\s+", " ", query.replace("\\", "\\\\").strip())

def has_span_query(dashboard_json: Dict[str, Any]) -> bool:
    """Check if dashboard contains span queries."""
    for page in dashboard_json.get("pages", []):
        for widget in page.get("widgets", []):
            query = get_query_from_widget(widget)
            if query and "from span" in query.lower():
                return True
    return False

def validate_api_key(api_key: str) -> bool:
    """Validate API key format and presence."""
    if not api_key or api_key == "REPLACE_ME":
        logger.error("Invalid API key. Please set a valid API key.")
        return False
    return True

async def create_session() -> aiohttp.ClientSession:
    """Create an aiohttp session with proper configuration."""
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)
    return aiohttp.ClientSession(
        timeout=timeout,
        headers={
            "Api-Key": API_KEY,
            "Content-Type": "application/json"
        },
        trust_env=True
    )

async def graphql_query(session: aiohttp.ClientSession, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Make GraphQL API calls with proper error handling and rate limiting."""
    total_retry_time = 0
    
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(
                API_BASE_URL,
                json=payload,
                timeout=API_TIMEOUT
            ) as resp:
                if resp.status == 401:
                    logger.error("Authentication failed. Please check your API key.")
                    return None
                elif resp.status == 403:
                    logger.error("Access forbidden. Please check your API key permissions.")
                    return None
                elif resp.status == 429:  # Rate limit exceeded
                    retry_after = int(resp.headers.get('Retry-After', RETRY_DELAY))
                    if total_retry_time + retry_after > MAX_TOTAL_RETRY_TIME:
                        raise TimeoutError("Maximum retry time exceeded")
                    total_retry_time += retry_after
                    logger.warning(f"Rate limit exceeded. Waiting {retry_after} seconds...")
                    await asyncio.sleep(retry_after)
                    continue
                elif resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"GraphQL error {resp.status}: {error_text}")
                    return None
                
                data = await resp.json()
                if "errors" in data:
                    logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
                    return None
                    
                return data
                
        except asyncio.TimeoutError:
            logger.warning(f"Timeout on attempt {attempt + 1}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
            continue
        except aiohttp.ClientError as e:
            logger.error(f"Network error: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
            continue
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
            continue
    
    return None

async def fetch_dashboard_guids(session: aiohttp.ClientSession) -> List[str]:
    """Get list of dashboard GUIDs with improved error handling."""
    if not session or session.closed:
        raise ValueError("Invalid or closed session")
        
    payload = {
        "query": """
        query {
          actor {
            accounts {
              id
              dashboards {
                list {
                  guid
                  name
                }
              }
            }
          }
        }"""
    }
    
    try:
        data = await graphql_query(session, payload)
        if not data or "data" not in data or "actor" not in data["data"]:
            logger.error("Invalid response format from GraphQL API")
            return []
            
        guids = []
        for acct in data["data"]["actor"]["accounts"]:
            if acct["id"] in ACCOUNT_IDS:
                for d in acct["dashboards"]["list"]:
                    guids.append(d["guid"])
        return guids
    except Exception as e:
        logger.error(f"Error fetching dashboard GUIDs: {str(e)}")
        return []

async def fetch_dashboard(guid: str, session: aiohttp.ClientSession) -> Optional[Dict[str, Any]]:
    """Get dashboard details with improved error handling."""
    if not session or session.closed:
        raise ValueError("Invalid or closed session")
        
    payload = {
        "query": f"""
        query {{
          actor {{
            entity(guid: \"{guid}\") {{
              ... on DashboardEntity {{
                guid
                name
                pages {{
                  name
                  guid
                  widgets {{
                    id
                    rawConfiguration
                    layout {{ row column width height }}
                    visualization {{ id }}
                  }}
                }}
                permissions {{ accountId accountName }}
                variables {{ name value defaultValues }}
              }}
            }}
          }}
        }}"""
    }
    
    try:
        data = await graphql_query(session, payload)
        if not data or "data" not in data or "actor" not in data["data"]:
            logger.error(f"Invalid response format for dashboard {guid}")
            return None
        return data["data"]["actor"]["entity"]
    except Exception as e:
        logger.error(f"Error fetching dashboard {guid}: {str(e)}")
        return None

async def validate_batch(batch: List[Dict[str, Any]], session: aiohttp.ClientSession) -> List[str]:
    """Validate a batch of queries with improved error handling."""
    if not session or session.closed:
        raise ValueError("Invalid or closed session")
        
    if len(batch) > BATCH_SIZE:
        logger.warning(f"Batch size {len(batch)} exceeds maximum {BATCH_SIZE}. Processing first {BATCH_SIZE} queries.")
        skipped = len(batch) - BATCH_SIZE
        if skipped > 0:
            logger.warning(f"Skipping {skipped} queries due to batch size limit")
        batch = batch[:BATCH_SIZE]

    query_parts = []
    for i, b in enumerate(batch):
        try:
            query = escape_query(b["query"])
            account_id = b["accountId"]
            query_parts.append(f'''
            q{i}: actor {{
                account(id: {account_id}) {{
                    nrql(query: "{query}") {{
                        results
                    }}
                }}
            }}''')
        except Exception as e:
            logger.error(f"Error processing query in batch {i}: {str(e)}")
            continue

    if not query_parts:
        logger.error("No valid queries in batch")
        return ["failed"] * len(batch)

    full_query = "query {\n" + "\n".join(query_parts) + "\n}"

    try:
        data = await graphql_query(session, {"query": full_query})
        if data is None:
            return ["failed"] * len(batch)

        error_paths = {e["path"][0] for e in data.get("errors", [])} if "errors" in data else set()
        return ["failed" if f"q{i}" in error_paths else "success" for i in range(len(batch))]
    except Exception as e:
        logger.error(f"Error validating batch: {str(e)}")
        return ["failed"] * len(batch)

UPDATE_VARIABLES_MUTATION = """
mutation($dashboardId: EntityGuid!, $variables: [DashboardVariableInput!]!) {
  dashboardUpdateVariables(dashboardId: $dashboardId, variables: $variables) {
    variables {
      name
      defaultValues
    }
  }
}
"""

UPDATE_WIDGETS_MUTATION = """
mutation($dashboardId: EntityGuid!, $widgets: [DashboardWidgetInput!]!) {
    dashboardUpdateWidgets(dashboardId: $dashboardId, widgets: $widgets) {
        widgets {
            id
            rawConfiguration
        }
    }
}
"""

async def update_dashboard_variables(dashboard_guid: str, variables_list: List[Dict[str, Any]], session: aiohttp.ClientSession) -> bool:
    """Update dashboard variables."""
    payload = {
        "query": UPDATE_VARIABLES_MUTATION,
        "variables": {
            "dashboardId": dashboard_guid,
            "variables": variables_list
        }
    }
    data = await graphql_query(session, payload)
    if not data or "errors" in data:
        logger.error(f"❌ Failed to update variables for {dashboard_guid}")
        if data:
            logger.error(f"❌ Response: {json.dumps(data, indent=2)}")
        return False
    logger.info(f"✅ Updated variables for {dashboard_guid}")
    return True

async def update_dashboard_widgets(guid: str, widgets: List[Dict[str, Any]], session: aiohttp.ClientSession) -> bool:
    """Update dashboard widgets using GraphQL mutation."""
    payload = {
        "query": UPDATE_WIDGETS_MUTATION,
        "variables": {
            "dashboardId": guid,
            "widgets": widgets
        }
    }
    
    try:
        data = await graphql_query(session, payload)
        if not data or "errors" in data:
            logger.error(f"❌ Failed to update widgets for {guid}")
            if data:
                logger.error(f"❌ Response: {json.dumps(data, indent=2)}")
            return False
        logger.info(f"✅ Updated widgets for {guid}")
        return True
    except Exception as e:
        log_error(e, f"Error updating widgets for {guid}")
        return False

async def run(mode: str, single_guid: Optional[str] = None, session: Optional[aiohttp.ClientSession] = None) -> None:
    """Main execution function with improved resource management."""
    if not session:
        raise ValueError("Session is required")
        
    try:
        validate_inputs(mode, single_guid)
        
        DATA_DIR.mkdir(exist_ok=True)
        OUTPUT_DIR.mkdir(exist_ok=True)
        mapper = validate_mapper(load_mapper())

        guids = [single_guid] if single_guid else await fetch_dashboard_guids(session)
        logger.info(f"Found {len(guids)} dashboards.")

        results = []
        summary = []
        query_result_counter = Counter()
        processed_count = 0

        with tqdm(total=len(guids), desc="Processing dashboards") as pbar:
            for guid in guids:
                try:
                    if processed_count >= MAX_RESULTS:
                        logger.warning(f"Reached maximum results limit of {MAX_RESULTS}")
                        break

                    dashboard = await fetch_dashboard(guid, session)
                    if not dashboard:
                        logger.warning(f"Failed to fetch dashboard {guid}")
                        continue

                    permissions = dashboard.get("permissions", [])
                    if not permissions:
                        logger.warning(f"Skipping {guid} - no permissions")
                        dashboard["no_permissions"] = True
                        results.append({"dashboard_guid": guid, "result": dashboard})
                        continue

                    if not has_span_query(dashboard):
                        logger.info(f"Skipping {guid} - no span queries")
                        continue

                    if mode == "download":
                        with open(f"data/{guid}.json", "w") as f:
                            json.dump(dashboard, f, indent=2)
                        logger.info(f"Downloaded {guid}")
                        continue

                    dashboard_name = dashboard.get("name", "unnamed")
                    account_id = permissions[0].get("accountId", 0)
                    variables = {"variables": {v["name"]: v.get("value") or v.get("defaultValues", []) 
                                            for v in dashboard.get("variables", [])}}

                    count_total = 0
                    count_valid = 0
                    count_fail = 0
                    batch = []

                    for page in dashboard.get("pages", []):
                        for widget in page.get("widgets", []):
                            query = get_query_from_widget(widget)
                            if not query or "from span" not in query.lower():
                                continue
                            query_lower = query.lower()

                            if any(k in query_lower for k in BLOCK_KEYWORDS):
                                widget["validation"] = "NA"
                                widget["transformed"] = ""
                                count_fail += 1
                                query_result_counter["blocked"] += 1
                                continue

                            if any(k in query_lower for k in SKIP_KEYWORDS):
                                widget["validation"] = "skipping"
                                widget["transformed"] = ""
                                query_result_counter["skipped"] += 1
                                continue

                            mapped = apply_mapping(query, mapper)
                            transformed = normalize_query(replace_variables(mapped, variables)) if mode == "validate" else normalize_query(mapped)
                            
                            account_ids = widget.get("rawConfiguration", {}).get("nrqlQueries", [{}])[0].get("accountIds", [account_id])
                            if not isinstance(account_ids, list):
                                account_ids = [account_ids]

                            for aid in account_ids:
                                batch.append({
                                    "query": transformed,
                                    "accountId": aid,
                                    "widget": widget,
                                    "page": page,
                                    "original": query,
                                    "accountIds": account_ids
                                })

                            count_total += 1

                    if not batch:
                        continue

                    statuses = await validate_batch(batch, session)
                    for b, result in zip(batch, statuses):
                        b["widget"]["validation"] = result
                        b["widget"]["transformed"] = b["query"]
                        if result == "success":
                            count_valid += 1
                            query_result_counter["success"] += 1
                        elif result == "failed":
                            count_fail += 1
                            query_result_counter["failed"] += 1

                    if mode == "update" and count_valid == count_total and count_fail == 0:
                        updated_widgets = []
                        for page in dashboard.get("pages", []):
                            for widget in page.get("widgets", []):
                                if widget.get("validation") == "success" and validate_widget_for_update(widget):
                                    updated_widgets.append({
                                        "id": widget["id"],
                                        "rawConfiguration": widget["rawConfiguration"],
                                        "layout": widget["layout"],
                                        "visualization": widget["visualization"]
                                    })
                        if updated_widgets:
                            for attempt in range(MAX_RETRIES):
                                try:
                                    await update_dashboard_widgets(dashboard["guid"], updated_widgets, session)
                                    break
                                except Exception as e:
                                    log_error(e, f"Attempt {attempt+1} failed to update widgets for {dashboard['guid']}")
                                    await asyncio.sleep(RETRY_DELAY)

                        variables_list = []
                        for v in dashboard.get("variables", []):
                            vals = v.get("defaultValues") or ([v["value"]] if v.get("value") else [])
                            if vals:
                                variables_list.append({"name": v["name"], "defaultValues": vals})
                        if variables_list:
                            await update_dashboard_variables(dashboard["guid"], variables_list, session)

                    summary.append({
                        "dashboard_guid": guid,
                        "dashboard_name": dashboard_name,
                        "validated": count_valid,
                        "failed": count_fail,
                        "skipped": count_total - count_valid - count_fail,
                        "total": count_total
                    })
                    results.append({"dashboard_guid": guid, "result": dashboard})
                    logger.info(f"Validated {guid} — Valid: {count_valid}, Failed: {count_fail}, Total: {count_total}")
                    processed_count += 1

                except Exception as e:
                    log_error(e, f"Error processing dashboard {guid}")
                finally:
                    pbar.update(1)

        if mode in ["validate", "update"]:
            logger.info("--- Validation Summary ---")
            for key, val in query_result_counter.items():
                logger.info(f"{key.capitalize():<10}: {val}")
            logger.info("--------------------------")

        try:
            OUTPUT_DIR.mkdir(exist_ok=True)
            if not os.access(OUTPUT_DIR, os.W_OK):
                raise PermissionError(f"Cannot write to output directory: {OUTPUT_DIR}")
                
            with open("output/validated_results.csv", "w", newline='') as f:
                fieldnames = [
                    "dashboard_guid", "dashboard_name", "page_name", "page_guid",
                    "widget_id", "widget_name", "widget_title", "layout", "visualization_id",
                    "original_query", "new_query", "result", "has_permissions", "variables_used"
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for dash in results:
                    guid = dash["dashboard_guid"]
                    dashboard_data = dash["result"]
                    has_permissions = "no_permissions" not in dashboard_data
                    if not has_permissions:
                        writer.writerow({
                            "dashboard_guid": guid,
                            "page_name": "",
                            "widget_name": "",
                            "original_query": "",
                            "new_query": "",
                            "result": "skipped",
                            "has_permissions": "no"
                        })
                        continue
                    for page in dashboard_data.get("pages", []):
                        for widget in page.get("widgets", []):
                            cfg = widget.get("rawConfiguration", {})
                            orig = cfg.get("nrqlQueries", [{}])[0].get("query", "")
                            new = normalize_query(widget.get("transformed", "")) if widget.get("validation") == "success" else ""
                            writer.writerow({
                                "dashboard_guid": guid,
                                "dashboard_name": dashboard_data.get("name", ""),
                                "page_name": page.get("name", ""),
                                "page_guid": page.get("guid", ""),
                                "widget_id": widget.get("id", ""),
                                "widget_name": cfg.get("title") or cfg.get("name", "") or widget.get("id", "unknown"),
                                "widget_title": cfg.get("title", ""),
                                "layout": json.dumps(widget.get("layout", {})),
                                "visualization_id": widget.get("visualization", {}).get("id", ""),
                                "original_query": orig,
                                "new_query": new,
                                "result": widget.get("validation", "NA"),
                                "has_permissions": "yes",
                                "variables_used": json.dumps(dashboard_data.get("variables", []))
                            })
        except Exception as e:
            log_error(e, "Error writing CSV file")
            raise

    except Exception as e:
        log_error(e, "Main execution")
        raise

async def main() -> None:
    """Main entry point with improved resource management."""
    session = None
    try:
        if not validate_api_key(API_KEY):
            return
            
        cleanup_old_logs()
        
        parser = argparse.ArgumentParser(description="New Relic Dashboard Span-to-Metric Validator")
        parser.add_argument("--mode", required=True, choices=["download", "validate", "update"], 
                          help="Mode: download, validate, or update")
        parser.add_argument("--confirm", action="store_true", 
                          help="Required to apply updates in --mode update")
        parser.add_argument("--guid", help="Optional: dashboard GUID to process only one dashboard")
        args = parser.parse_args()

        if args.mode == "update" and not args.confirm:
            logger.warning("⚠️ This will modify live New Relic dashboards.")
            logger.warning("Use --confirm to proceed with --mode update")
            return

        session = await create_session()
        await run(args.mode, single_guid=args.guid, session=session)
    except Exception as e:
        logger.error(f"Main execution error: {str(e)}")
    finally:
        if session and not session.closed:
            await session.close()

if __name__ == "__main__":
    asyncio.run(main())
