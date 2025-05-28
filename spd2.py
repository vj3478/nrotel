import requests
import json
import os
import math
import re
import time
import csv
import argparse

# Replace with your actual New Relic API key and Account ID
# It's recommended to use environment variables for sensitive information
NEW_RELIC_API_KEY = os.environ.get("NEW_RELIC_API_KEY", "YOUR_API_KEY") # Replace with your API Key or set environment variable
ACCOUNT_ID = int(os.environ.get("NEW_RELIC_ACCOUNT_ID", 1234567)) # Replace with your Account ID or set environment variable

# --- Configuration ---
# File to load dashboard GUIDs from (created by get_dashboard_guids.py)
DASHBOARD_GUIDS_FILE = "dashboard_guids.json"

# Default file to save the detailed results in CSV format
RESULTS_FILE_NAME = "nrql_validation_update_results.csv"

BATCH_SIZE = 25 # Maximum number of items (validation queries or update payloads) per batch

# List of words that, if present in the modified NRQL query, will cause the update to be skipped.
# Case-insensitive check will be performed.
FORBIDDEN_WORDS = ["DELETE", "DROP", "ALTER"] # Add any other words you want to forbid

# --- Helper function to execute a NerdGraph query or mutation ---
def execute_nerdgraph_request(query, variables=None, account_ids=None):
    """Executes a GraphQL query or mutation against the New Relic NerdGraph API.

    Args:
        query (str): The GraphQL query or mutation string.
        variables (dict, optional): A dictionary of variables for the GraphQL query.
        account_ids (list or int, optional): A single account ID (int) or a list of account IDs (list of int)
                                             to run an NRQL query against. If None, the query is assumed
                                             to be a general NerdGraph query not tied to a specific account
                                             or a single-account query using the default ACCOUNT_ID if needed
                                             by the query string itself.

    Returns:
        dict: The JSON response from the API, or None if an error occurred.
    """
    NERDGRAPH_URL = "https://api.newrelic.com/graphql"
    headers = {
        "Content-Type": "application/json",
        "Api-Key": NEW_RELIC_API_KEY
    }

    # Construct the actor block based on account_ids
    actor_block = "actor {"
    if account_ids is not None:
        if isinstance(account_ids, list):
            # Multi-account NRQL query
            # The query string itself should contain the nrql(...) block
            # e.g., "nrql(accounts: $accountIds, query: \"SELECT ...\") { results }"
            # We assume the passed 'query' string starts within the actor block, after the account part.
            # This requires refactoring the query templates.
            # Let's simplify: if account_ids is provided, assume the *entire* query needs the accounts parameter
            # within the nrql field. This means the passed 'query' should just be the NRQL string.
            # This requires significant changes to how queries are templated and passed.

            # REVISED APPROACH: Keep the query templates as they are (assuming they contain the nrql(...) block).
            # Modify this helper to wrap the query within actor { account { ... } } or actor { ... } based on context.
            # This is also tricky as the query template might already contain `actor { ... }`.

            # Let's try a simpler approach: the caller provides the *full* query string, including `actor { ... }`.
            # The `account_ids` parameter is used *only* to indicate that the query string *might* contain
            # an `nrql` field that should use the `accounts: [...]` parameter instead of `account(id: ...) { nrql(...) }`.
            # This is still not ideal as it requires complex query template management outside this function.

            # Let's revert to the original plan but make execute_nrql_query handle the structure.
            # This helper will remain generic for any GraphQL query/mutation.
            pass # No change needed in the helper for this approach.

    payload = {
        "query": query,
        "variables": variables
    }

    # print("Executing NerdGraph request...")
    # print(f"Query:\n{query}") # Uncomment for debugging
    # print(f"Variables:\n{json.dumps(variables, indent=2)}") # Uncomment for debugging

    try:
        response = requests.post(NERDGRAPH_URL, headers=headers, json=payload)
        response.raise_for_status() # Raise an exception for bad status codes
        result = response.json()
        # print(f"Response:\n{json.dumps(result, indent=2)}") # Uncomment for debugging
        return result
    except requests.exceptions.RequestException as e:
        print(f"Error making NerdGraph API request: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status code: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
        return None

# --- Function to apply dashboard variables to NRQL ---
def apply_dashboard_variables(nrql_query, variables):
    """
    Applies dashboard variables to an NRQL query string, replacing {{ variable_name }}
    (with any spaces between braces and name) with the variable's value enclosed in single quotes.

    Args:
        nrql_query (str): The original NRQL query string possibly containing variables
                          in the format {{ variable_name }}.
        variables (list): A list of variable dictionaries.
                          Each dict should have 'name' and 'value'. Multi-value variables
                          might have 'value' as a list.

    Returns:
        str: The NRQL query string with variables substituted.
    """
    if not nrql_query or not variables:
        return nrql_query

    modified_query = nrql_query

    # Create a dictionary for easier lookup {variable_name: variable_value}
    variable_map = {var.get("name"): var.get("value") for var in variables if var.get("name")}

    # Sort variable names by length in descending order to handle cases
    # where one variable name is a substring of another.
    sorted_variable_names = sorted(variable_map.keys(), key=len, reverse=True)

    for var_name in sorted_variable_names:
        var_value = variable_map[var_name]
        # Define the pattern to look for: {{ variable_name }} with any spaces.
        # The \s* already handles zero or more spaces.
        pattern = re.compile(r"\{\{\s*" + re.escape(var_name) + r"\s*\}\}", re.IGNORECASE)

        replacement_value = ""
        if isinstance(var_value, list):
            # For multi-valued variables, format as a comma-separated, single-quoted string
            # suitable for an 'IN' clause. Escape single quotes within values.
            quoted_values = [f"'{str(val).replace(\"'\", \"\\'\")}'" for val in var_value if val is not None]
            replacement_value = ", ".join(quoted_values)
        elif var_value is not None:
            # For single-valued variables, enclose the value in single quotes.
            # Escape single quotes within the value.
            replacement_value = f"'{str(var_value).replace(\"'\", \"\\'\")}'"
        # If var_value is None, replacement_value remains empty string, effectively removing {{ variable_name }}

        # Use regex to replace all occurrences of the pattern
        modified_query = re.sub(pattern, replacement_value, modified_query)

    return modified_query

# --- Query to fetch dashboard details and variables ---
# We need widget IDs, their configurations (rawConfiguration or configuration)
# to check for NRQL, the dashboard page GUID, and the dashboard variables.
get_dashboard_and_variables_query = """
query ($guid: String!) {
  actor {
    entity(guid: $guid) {
      ... on DashboardEntity {
        name
        owner {
          email
        }
        permissions
        pages {
          guid
          name
          widgets {
            id
            title
            visualization
            layout
            rawConfiguration
            configuration
          }
        }
        variables {
          name
          type
          title
          default
          required
          defaultValues
          source {
            ... on DashboardVariableNrqlQuery {
              query
              accountIds
              isDefault
              results {
                 # ADJUST THESE FIELDS based on your variable query results structure
                 value
                 name
                 id
              }
            }
            ... on DashboardVariableList {
                 values {
                     value
                 }
            }
             ... on DashboardVariableEnum {
                 values {
                     value
                 }
            }
          }
          values {
             value
             values {
                 value
             }
          }
        }
      }
    }
  }
}
"""

# --- Mutation for batch NRQL validation ---
# We will now validate individually by attempting a LIMIT 0 execution.

# --- Mutation for updating widgets in a page ---
update_widgets_mutation = """
mutation ($dashboardPageGuid: String!, $widgets: [DashboardUpdateWidgetInPageInput!]!) {
  dashboardUpdateWidgetsInPage(input: {
    dashboardPageGuid: $dashboardPageGuid,
    widgets: $widgets
  }) {
    dashboard {
      name
    }
    errors {
       description
       type
    }
  }
}
"""
# Note: Verify the exact input type name and its allowed fields for dashboardUpdateWidgetsInPage.


def execute_nrql_query(account_id, api_key, nrql_query, account_ids=None):
    """Executes an NRQL query using the New Relic NerdGraph API, supporting single or multiple accounts.

    Args:
        account_id (int): The default account ID to use if account_ids is None.
        api_key (str): The New Relic API key.
        nrql_query (str): The NRQL query string.
        account_ids (list or int, optional): A single account ID (int) or a list of account IDs (list of int)
                                             to run the NRQL query against. If None, the default account_id is used.

    Returns:
        list: The list of results from the NRQL query, or None if an error occurred.
    """
    url = "https://api.newrelic.com/graphql"
    headers = {
        "Api-Key": api_key,
        "Content-Type": "application/json"
    }

    if account_ids is None:
        # Use single account structure
        query = """
            {
              actor {
                account(id: %d) {
                  nrql(query: "%s") {
                    results
                  }
                }
              }
            }
        """ % (account_id, nrql_query.replace('"', '\\"')) # Escape double quotes in NRQL
    elif isinstance(account_ids, list):
        # Use multi-account structure
        # Ensure account_ids list is not empty
        if not account_ids:
            print("Error: account_ids list is empty for multi-account query.")
            return None
        # Format account IDs for the query string
        accounts_list_str = ", ".join(map(str, account_ids))
        query = """
            {
              actor {
                nrql(accounts: [%s], query: "%s") {
                  results
                }
              }
            }
        """ % (accounts_list_str, nrql_query.replace('"', '\\"')) # Escape double quotes in NRQL
    elif isinstance(account_ids, int):
         # Treat a single integer account_ids as a list with one element for the multi-account structure
         # This is consistent with how the API handles it, although account(id:...) is also valid.
         # Using the multi-account structure for a single ID ensures consistency in the query building logic here.
         query = """
            {
              actor {
                nrql(accounts: [%d], query: "%s") {
                  results
                }
              }
            }
        """ % (account_ids, nrql_query.replace('"', '\\"')) # Escape double quotes in NRQL
    else:
        print(f"Error: Invalid type for account_ids: {type(account_ids)}")
        return None

    try:
        response = requests.post(url, headers=headers, data=json.dumps({"query": query}))
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            print(f"NRQL Query Execution Errors: {data['errors']}")
            return None
        # Handle response structure for single vs multi-account. Multi-account results are directly under nrql.results.
        # Single account results are under actor.account.nrql.results
        if account_ids is None:
             return data.get("data", {}).get("actor", {}).get("account", {}).get("nrql", {}).get("results")
        else:
             return data.get("data", {}).get("actor", {}).get("nrql", {}).get("results")


    except requests.exceptions.RequestException as e:
        print(f"HTTP request failed during NRQL execution: {e}")
        return None
    except KeyError as e:
        print(f"Could not parse NRQL results from response: {e}")
        # Print the full response data for debugging
        # print(f"Response data: {data}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during NRQL execution: {e}")
        return None

def validate_nrql_query(nrql_query, api_key, account_id, account_ids=None):
    """Validates an NRQL query by attempting to execute it with LIMIT 0.

    Args:
        nrql_query (str): The NRQL query string.
        api_key (str): The New Relic API key.
        account_id (int): The default account ID.
        account_ids (list or int, optional): Account(s) to run the validation query against.
                                             If None, uses the default account_id.

    Returns:
        str: "Validation Successful" or an error message.
    """
    if not nrql_query or not isinstance(nrql_query, str):
        return "Validation Failed: Invalid NRQL query provided."

    # Use LIMIT 0 to validate syntax without fetching data
    validation_query = f"SELECT 1 FROM ({nrql_query}) LIMIT 0"

    # Use the execute_nrql_query function to handle single/multi-account structure
    # Errors during execution (even with LIMIT 0) indicate syntax issues or other problems.
    result = execute_nrql_query(account_id, api_key, validation_query, account_ids=account_ids)

    if result is not None:
        # If execute_nrql_query returned results (even an empty list for LIMIT 0), it was syntactically valid.
        # Any API errors would have returned None from execute_nrql_query or printed errors.
        return "Validation Successful"
    else:
        # execute_nrql_query returned None, indicating an error occurred (printed inside that function).
        return "Validation Failed (Execution Error)"


# --- Main Script Logic ---

def main():
    parser = argparse.ArgumentParser(description="Process New Relic dashboards to update NRQL queries in batches.")
    parser.add_argument("--validate-only", action="store_true",
                        help="Only validate the modified NRQL queries and save results, do not perform updates.")
    parser.add_argument("--validate-and-update", action="store_true",
                        help="Validate the modified NRQL queries, compare outputs, and update widgets. This is the default behavior if neither --validate-only nor --validate-and-update is specified.")
    parser.add_argument("--guids-file", default=DASHBOARD_GUIDS_FILE,
                        help=f"Path to the JSON file containing dashboard GUIDs (default: {DASHBOARD_GUIDS_FILE}).")
    parser.add_argument("--output-file", default=RESULTS_FILE_NAME,
                        help=f"Path to the CSV file to save results (default: {RESULTS_FILE_NAME}).")

    args = parser.parse_args()

    dashboard_guids_file = args.guids_file
    results_file = args.output_file

    # Determine the mode based on arguments. If neither is specified, default to validate-and-update.
    validate_only = args.validate_only
    perform_update = args.validate_and_update or (not args.validate_only and not args.validate_and_update)

    all_processed_widgets_details = [] # List to store details for all processed widgets across all dashboards

    # --- Load Dashboard GUIDs from file ---
    dashboard_guids_to_process = []
    try:
        with open(dashboard_guids_file, 'r', encoding='utf-8') as f:
            dashboard_guids_to_process = json.load(f)
        print(f"Successfully loaded {len(dashboard_guids_to_process)} dashboard GUIDs from {dashboard_guids_file}")
    except FileNotFoundError:
        print(f"Error: Dashboard GUIDs file not found at {dashboard_guids_file}. Please run get_dashboard_guids.py first.")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {dashboard_guids_file}. Ensure it contains a valid JSON array.")
        return
    except IOError as e:
        print(f"Error reading dashboard GUIDs from {dashboard_guids_file}: {e}")
        return

    if not dashboard_guids_to_process:
        print("No dashboard GUIDs found in the file. Exiting.")
        return
    else:
        for dashboard_guid in dashboard_guids_to_process:
            print(f"\n--- Processing Dashboard: {dashboard_guid} ---")

            widgets_to_process = [] # Widgets identified for processing (with modified NRQL)
            dashboard_page_guid_to_update = None
            dashboard_variables = [] # Variables for the current dashboard
            dashboard_name = "Unknown Dashboard"
            page_name = "Unknown Page"

            # --- Step 1: Fetch the current dashboard configuration AND variables ---
            print(f"Fetching dashboard data and variables for GUID: {dashboard_guid}")
            # Assuming fetch_dashboard_data uses execute_nerdgraph_request correctly for entity query
            dashboard_data_result = execute_nerdgraph_request(get_dashboard_and_variables_query, {"guid": dashboard_guid})

            if dashboard_data_result and dashboard_data_result.get("data") and dashboard_data_result["data"].get("actor") and dashboard_data_result["data"]["actor"].get("entity"):
                dashboard = dashboard_data_result["data"]["actor"]["entity"]
                dashboard_name = dashboard.get('name', 'Unknown Dashboard')
                dashboard_owner = dashboard.get('owner', {}).get('email', 'Unknown Owner')
                dashboard_permissions = dashboard.get('permissions') # Get dashboard permissions

                # Check if the dashboard is public
                if dashboard_permissions != 'PUBLIC_READ_ONLY' and dashboard_permissions != 'PUBLIC_READ_WRITE':
                    print(f"Skipping dashboard {dashboard_name} ({dashboard_guid}) as it is not public (permissions: {dashboard_permissions}).")
                    continue # Skip to the next dashboard GUID

                print(f"Successfully fetched dashboard: {dashboard_name}")

                # Extract dashboard variables and determine their effective values
                if dashboard.get("variables"):
                    print(f"Found {len(dashboard['variables'])} dashboard variables.")
                    for var in dashboard["variables"]:
                         var_name = var.get("name")
                         if not var_name:
                              continue

                         effective_value = None
                         # Logic to determine effective_value (same as before, verify against your API)
                         if var.get("values"):
                              if var["values"].get("values") is not None and isinstance(var["values"]["values"], list):
                                   effective_value = [v.get("value") for v in var["values"]["values"] if v.get("value") is not None]
                                   if len(effective_value) == 1: effective_value = effective_value[0]
                                   elif len(effective_value) == 0: effective_value = None # Or []?
                              elif var["values"].get("value") is not None:
                                   effective_value = var["values"]["value"]

                         if effective_value is None and var.get("defaultValues"):
                              if isinstance(var["defaultValues"], list) and len(var["defaultValues"]) > 0:
                                   effective_value = [v.get("value") for v in var["defaultValues"] if v.get("value") is not None]
                                   if len(effective_value) == 1: effective_value = effective_value[0]
                                   elif len(effective_value) == 0: effective_value = None # Or []?
                              elif var.get("default") is not None:
                                  effective_value = var["default"]

                         if effective_value is None and var.get("source") and var["source"].get("results"):
                              source_results = var["source"]["results"]
                              if isinstance(source_results, list) and len(source_results) > 0:
                                   first_result = source_results[0]
                                   if first_result.get("value") is not None:
                                       effective_value = first_result["value"]
                                   elif first_result.get(var_name) is not None:
                                        effective_value = first_result[var_name]
                                   else:
                                       if first_result:
                                            keys = list(first_result.keys())
                                            if keys:
                                                 effective_value = first_result[keys[0]]

                         dashboard_variables.append({"name": var_name, "value": effective_value})
                         # print(f"  Variable '{var_name}': Determined Value = {effective_value}")


                # Assuming we are processing the first page of the dashboard
                # Note: This script processes widgets page by page implicitly by getting all widgets and grouping for update.
                # If a dashboard has multiple pages with widgets to update, the current logic will collect all
                # widgets from the first page, then process the next dashboard GUID.
                # To process all pages of a single dashboard before moving to the next GUID, the loop structure needs adjustment.
                # For now, sticking to processing widgets from the first page as per the existing structure.

                if dashboard.get("pages") and len(dashboard["pages"]) > 0:
                    dashboard_page = dashboard["pages"][0] # Processing only the first page
                    dashboard_page_guid_to_update = dashboard_page.get("guid")
                    current_widgets = dashboard_page.get("widgets", [])
                    page_name = dashboard_page.get('name', 'Unknown Page')

                    if not dashboard_page_guid_to_update:
                         print(f"Dashboard page in dashboard {dashboard_guid} has no GUID. Skipping processing for this dashboard's page.")
                    else:
                        print(f"Found {len(current_widgets)} widgets on page '{page_name}' ({dashboard_page_guid_to_update}).")

                        # --- Identify widgets with NRQL and apply variables and replacement ---
                        span_regex = re.compile(r"from\s*Span", re.IGNORECASE)
                        replacement_string = "From Metric"

                        widgets_to_process_for_dashboard = [] # Widgets from this dashboard+page to process

                        for widget in current_widgets:
                            widget_id = widget.get("id")
                            if not widget_id:
                                continue

                            nrql_query = None
                            # Extract NRQL from rawConfiguration or configuration
                            if widget.get("rawConfiguration") and widget["rawConfiguration"].get("nrqlQueries"):
                                if isinstance(widget["rawConfiguration"]["nrqlQueries"], list) and len(widget["rawConfiguration"]["nrqlQueries"]) > 0:
                                    nrql_query = widget["rawConfiguration"]["nrqlQueries"][0].get("query")
                            elif widget.get("configuration"):
                                 for config_type in ["area", "bar", "billboard", "line", "pie", "table", "markdown", "heatMap", "apmSummary", "browserSummary", "mobileSummary", "infrastructureSummary", "logsTable", "entityList", "eventTable", "statusHeatmap", "stackedBar", "universalText", "alertViolations", "tableWithFACET"]:
                                     if widget["configuration"].get(config_type) and widget["configuration"][config_type].get("nrqlQueries"):
                                          if isinstance(widget["configuration"][config_type]["nrqlQueries"], list) and len(widget["configuration"][config_type]["nrqlQueries"]) > 0:
                                               nrql_query = widget["configuration"][config_type]["nrqlQueries"][0].get("query")
                                               break # Found NRQL in one visualization type

                            if nrql_query and isinstance(nrql_query, str):
                                # Apply dashboard variables
                                nrql_with_variables = apply_dashboard_variables(nrql_query, dashboard_variables)

                                # Apply the Span to Metric replacement
                                modified_nrql_query = span_regex.sub(replacement_string, nrql_with_variables)

                                # Only process if the NRQL was actually modified (either by variable substitution or Span to Metric)
                                if modified_nrql_query != nrql_query:
                                     # We need to determine which accounts the original query was targeting
                                     # This is complex. Dashboards can be multi-account via variables or explicit query syntax.
                                     # The API fetch_dashboard_data doesn't seem to directly return accounts targeted by a widget's NRQL.
                                     # For now, we will assume that if the dashboard has variables with accountIds defined,
                                     # those are the intended accounts for multi-account queries in this dashboard.
                                     # If no such variables, default to the script's main ACCOUNT_ID.
                                     # This is an assumption and might need refinement based on how your dashboards are set up.
                                     target_account_ids = None
                                     for var in dashboard.get("variables", []):
                                          if var.get("source") and var["source"].get("accountIds"):
                                               target_account_ids = var["source"]["accountIds"]
                                               break # Assume the first variable with accountIds determines the target accounts

                                     # If no accountIds found in variables, default to the main ACCOUNT_ID
                                     if target_account_ids is None:
                                          target_account_ids = ACCOUNT_ID # Use the default script account ID
                                     elif isinstance(target_account_ids, list) and len(target_account_ids) == 1:
                                          target_account_ids = target_account_ids[0] # If only one account ID, use the single int format

                                     widgets_to_process_for_dashboard.append({
                                         "dashboard_guid": dashboard_guid,
                                         "dashboard_name": dashboard_name,
                                         "dashboard_owner": dashboard_owner,
                                         "page_guid": dashboard_page_guid_to_update,
                                         "page_name": page_name,
                                         "widget_id": widget_id,
                                         "widget_title": widget.get("title"),
                                         "original_nrql": nrql_query,
                                         "modified_nrql": modified_nrql_query, # Query with variables and replacement
                                         "target_account_ids": target_account_ids, # Accounts determined for this widget's query
                                         "layout": widget.get("layout"), # Keep original layout
                                         "visualization": widget.get("visualization"), # Keep original visualization
                                         "configuration": widget.get("configuration"), # Keep original configurations
                                         "rawConfiguration": widget.get("rawConfiguration"), # Keep original rawConfigurations
                                     })


                        print(f"\nIdentified {len(widgets_to_process_for_dashboard)} widgets on page '{page_name}' in dashboard {dashboard_name} requiring processing.")

                        # --- Step 2: Validate and Execute Modified NRQL Queries Individually ---
                        widgets_for_update_payloads = [] # Payloads for widgets with successfully validated and allowed NRQL
                        
                        if not widgets_to_process_for_dashboard:
                            print("No widgets to validate, execute, or update on this page.")
                        else:
                            print(f"Preparing to validate and execute {len(widgets_to_process_for_dashboard)} modified NRQL queries individually.")

                            for widget_data in widgets_to_process_for_dashboard:
                                 widget_id = widget_data['widget_id']
                                 modified_nrql = widget_data['modified_nrql']
                                 original_nrql = widget_data['original_nrql']
                                 target_account_ids = widget_data['target_account_ids']

                                 print(f"\nProcessing widget {widget_id} ('{widget_data.get('widget_title', 'Untitled')}') on page '{page_name}'...")

                                 # --- Check for forbidden words ---
                                 modified_nrql_lower = modified_nrql.lower()
                                 forbidden_word_found = False
                                 found_word = ""
                                 for word in FORBIDDEN_WORDS:
                                      if word.lower() in modified_nrql_lower:
                                           forbidden_word_found = True
                                           found_word = word
                                           break

                                 validation_status = "Skipped (Forbidden Word)" if forbidden_word_found else "Pending Validation"
                                 validation_reason = f"Forbidden word found: '{found_word}'" if forbidden_word_found else ""
                                 update_status = validation_status # Initial status before update attempt
                                 update_errors = ""
                                 old_query_output = None
                                 new_query_output = None
                                 query_output_match = "Not Performed"

                                 if not forbidden_word_found:
                                     # --- Validate new NRQL query ---
                                     print(f"  Validating modified NRQL query...")
                                     validation_result = validate_nrql_query(modified_nrql, NEW_RELIC_API_KEY, ACCOUNT_ID, account_ids=target_account_ids)

                                     if validation_result == "Validation Successful":
                                         validation_status = "Valid"
                                         update_status = "Pending Execution and Update"
                                         print("  Validation Successful.")

                                         # --- Execute old and new queries and compare outputs ---
                                         print("  Executing original and modified NRQL queries for output comparison...")
                                         # Execute original query
                                         print("    Executing original query...")
                                         old_query_output = execute_nrql_query(ACCOUNT_ID, NEW_RELIC_API_KEY, original_nrql, account_ids=target_account_ids)

                                         # Execute modified query
                                         print("    Executing modified query...")
                                         new_query_output = execute_nrql_query(ACCOUNT_ID, NEW_RELIC_API_KEY, modified_nrql, account_ids=target_account_ids)

                                         # Compare outputs
                                         if old_query_output is not None and new_query_output is not None:
                                              # Simple comparison of results - might need more sophisticated logic
                                              # depending on the expected output format (e.g., lists of dicts, order)
                                              # Consider sorting results before comparison if order doesn't matter.
                                              # For simplicity, a direct comparison is used here.
                                              query_output_match = "Match" if old_query_output == new_query_output else "Mismatch"
                                              print(f"  Query output comparison: {query_output_match}")
                                         else:
                                              query_output_match = "Error during execution"
                                              print("  Query output comparison: Error during execution.")

                                         # Prepare the update payload if validation and checks pass and not validate_only
                                         if not validate_only and query_output_match == "Match": # Only update if outputs match (or adjust condition)
                                              # Construct the widget configuration for update
                                              widget_config = {
                                                  "id": widget_id,
                                                  "title": widget_data['widget_title'], # Keep original title or modify as needed
                                                  "rawConfiguration": widget_data['rawConfiguration'], # Include original rawConfiguration
                                                  "configuration": widget_data['configuration'], # Include original configurations
                                                  "layout": widget_data['layout'], # Include original layout
                                                  # Override the NRQL query within the appropriate structure
                                              }
                                              # Need to find where the NRQL query is nested and update it
                                              if widget_config.get("rawConfiguration") and widget_config["rawConfiguration"].get("nrqlQueries"):
                                                   if isinstance(widget_config["rawConfiguration"]["nrqlQueries"], list) and len(widget_config["rawConfiguration"]["nrqlQueries"]) > 0:
                                                        widget_config["rawConfiguration"]["nrqlQueries"][0]["query"] = modified_nrql
                                                        widgets_for_update_payloads.append(widget_config)
                                                        update_status = "Ready for Update Batch"
                                                   else:
                                                        update_status = "Skipped (NRQL Structure Not Found)"
                                                        validation_status = "Invalid" # Consider this invalid for update purposes
                                                        validation_reason = "NRQL query structure not found in rawConfiguration."

                                              elif widget_config.get("configuration"):
                                                   updated = False
                                                   for config_type in ["area", "bar", "billboard", "line", "pie", "table", "markdown", "heatMap", "apmSummary", "browserSummary", "mobileSummary", "infrastructureSummary", "logsTable", "entityList", "eventTable", "statusHeatmap", "stackedBar", "universalText", "alertViolations", "tableWithFACET"]:
                                                        if widget_config["configuration"].get(config_type) and widget_config["configuration"][config_type].get("nrqlQueries"):
                                                             if isinstance(widget_config["configuration"][config_type]["nrqlQueries"], list) and len(widget_config["configuration"][config_type]["nrqlQueries"]) > 0:
                                                                  widget_config["configuration"][config_type]["nrqlQueries"][0]["query"] = modified_nrql
                                                                  widgets_for_update_payloads.append(widget_config)
                                                                  update_status = "Ready for Update Batch"
                                                                  updated = True
                                                                  break # Found and updated NRQL in one visualization type
                                                   if not updated:
                                                        update_status = "Skipped (NRQL Structure Not Found)"
                                                        validation_status = "Invalid" # Consider this invalid for update purposes
                                                        validation_reason = "NRQL query structure not found in configuration."
                                              else:
                                                   update_status = "Skipped (NRQL Structure Not Found)"
                                                   validation_status = "Invalid" # Consider this invalid for update purposes
                                                   validation_reason = "NRQL query structure not found."


                                     else:
                                         validation_status = "Invalid"
                                         validation_reason = validation_result # Store the error message from validation
                                         update_status = "Skipped (Validation Failed)"
                                         print("  Validation Failed.")



                                 # Add this widget's details and results to the overall results list
                                 all_processed_widgets_details.append({
                                      "Dashboard GUID": dashboard_guid,
                                      "Dashboard Name": dashboard_name,
                                      "Dashboard Owner": dashboard_owner,
                                      "Page GUID": dashboard_page_guid_to_update,
                                      "Page Name": page_name,
                                      "Widget ID": widget_id,
                                      "Widget Title": widget_data.get('widget_title', 'Untitled Widget'),
                                      "Original NRQL": original_nrql,
                                      "Modified NRQL": modified_nrql,
                                      "Target Account(s)": str(target_account_ids), # Store as string for CSV
                                      "NRQL Validation Status": validation_status,
                                      "NRQL Validation Reason": validation_reason,
                                      "Old Query Output (Sample)": json.dumps(old_query_output) if old_query_output is not None else str(old_query_output), # Store sample output or indicator
                                      "New Query Output (Sample)": json.dumps(new_query_output) if new_query_output is not None else str(new_query_output), # Store sample output or indicator
                                      "Query Output Match": query_output_match,
                                      "Update Status": update_status, # This is the status before the update attempt (Pending, Skipped, Ready)
                                      "Update Errors": update_errors, # This will be populated after the update mutation if applicable
                                 })

                            # --- Step 3: Batch Update Validated and Allowed Widgets (Conditional) ---
                            # This part remains largely the same, but it now operates on widgets_for_update_payloads
                            # collected from the individual processing step.

                            if perform_update:
                                 # Filter the list to only include widgets that are ready for update
                                 widgets_to_update_in_batch = [
                                     p for p in widgets_for_update_payloads
                                     if any(w['Widget ID'] == p['id'] and w['Update Status'] == 'Ready for Update Batch' for w in all_processed_widgets_details)
                                 ]

                                 if not widgets_to_update_in_batch:
                                     print("\nNo widgets ready for update in this batch after validation and checks. Skipping update process.")
                                 else:
                                     num_widgets_to_update = len(widgets_to_update_in_batch)
                                     num_update_batches = math.ceil(num_widgets_to_update / BATCH_SIZE)

                                     print(f"\nPreparing to update {num_widgets_to_update} widgets on page {dashboard_page_guid_to_update} in {num_update_batches} batches for dashboard {dashboard_name}.")

                                     for i in range(num_update_batches):
                                          start_index = i * BATCH_SIZE
                                          end_index = min(start_index + BATCH_SIZE, num_widgets_to_update)
                                          batch_payloads = widgets_to_update_in_batch[start_index:end_index]

                                          print(f"\nProcessing update batch {i + 1}/{num_update_batches} ({len(batch_payloads)} widgets) for dashboard {dashboard_name}...")

                                          mutation_variables = {
                                              "dashboardPageGuid": dashboard_page_guid_to_update,
                                              "widgets": batch_payloads
                                          }

                                          # Use the generic execute_nerdgraph_request for the mutation
                                          mutation_result = execute_nerdgraph_request(update_widgets_mutation, mutation_variables)

                                          # Update the update status for the corresponding entries in all_processed_widgets_details
                                          if mutation_result:
                                               update_errors_list = []
                                               if mutation_result.get("data") and mutation_result["data"].get("dashboardUpdateWidgetsInPage"):
                                                    update_res = mutation_result["data"]["dashboardUpdateWidgetsInPage"]
                                                    if update_res.get("errors"):
                                                         update_errors_list = update_res['errors']

                                               elif mutation_result.get("errors"):
                                                     update_errors_list = mutation_result['errors']


                                               for widget_payload in batch_payloads:
                                                    widget_id = widget_payload['id']
                                                    # Find the entry in all_processed_widgets_details for this widget
                                                    for entry in all_processed_widgets_details:
                                                        # Need to match on both widget ID and dashboard GUID to be precise
                                                        if entry.get('Widget ID') == widget_id and entry.get('Dashboard GUID') == dashboard_guid and entry.get('Update Status') == 'Ready for Update Batch':
                                                             entry['Update Status'] = "Update Failed" if update_errors_list else "Update Successful"
                                                             # Store errors as a JSON string in the CSV
                                                             entry['Update Errors'] = json.dumps(update_errors_list) if update_errors_list else ""
                                                             # Note: You could store the full response in a dedicated column if needed for debugging
                                                             # entry['Update API Response'] = json.dumps(mutation_result)
                                                             break # Found the entry, move to the next payload
                                          else:
                                               # Handle case where the API request itself failed
                                               for widget_payload in batch_payloads:
                                                    widget_id = widget_payload['id']
                                                    for entry in all_processed_widgets_details:
                                                        if entry.get('Widget ID') == widget_id and entry.get('Dashboard GUID') == dashboard_guid and entry.get('Update Status') == 'Ready for Update Batch':
                                                              entry['Update Status'] = "Update Request Failed"
                                                              entry['Update Errors'] = "Error making API request."
                                                              break

                                          if mutation_result and mutation_result.get("data") and mutation_result["data"].get("dashboardUpdateWidgetsInPage"):
                                               update_result = mutation_result["data"]["dashboardUpdateWidgetsInPage"]
                                               if update_result.get("errors"):
                                                    print(f"Update Batch {i + 1} Errors for dashboard {dashboard_name}:")
                                                    for error in update_result["errors"]:
                                                         print(f"- {error.get('description', 'No description')} (Type: {error.get('type', 'Unknown')})")
                                               elif update_result.get("dashboard"):
                                                    print(f"Update Batch {i + 1} successfully processed for dashboard: {update_result['dashboard'].get('name', 'N/A')}")
                                               else:
                                                    print(f"Update Batch {i + 1} mutation executed, but no clear success or error reported in the data field for dashboard {dashboard_name}.")

                                          elif mutation_result and mutation_result.get("errors"):
                                                print(f"Update Batch {i + 1} Mutation Errors for dashboard {dashboard_name}:")
                                                for error in mutation_result["errors"]:
                                                     print(f"- {error.get('message', 'No message')}")
                                          else:
                                               print(f"Update Batch {i + 1} failed to execute mutation or received an unexpected response for dashboard {dashboard_name}.")

                                          # Optional: Add a small delay between update batches
                                          # time.sleep(1)

                            else:
                                print("\nSkipping update process as --validate-only flag was used.")


                else:
                    print(f"Failed to fetch dashboard data for GUID: {dashboard_guid} or received an unexpected response structure. Skipping this dashboard.")

            else:
                 print(f"Failed to fetch dashboard data for GUID: {dashboard_guid} or received an unexpected response structure. Please check the GUID, Account ID, and API Key.")


    # --- Step 4: Save the collected results to a CSV file ---
    print(f"\n--- Saving Overall Results to CSV ---")
    if not all_processed_widgets_details:
        print("No widgets were processed for update/validation. Nothing to save.")
        return

    try:
        # Add new columns for multi-account and query outputs
        fieldnames = [
            "Dashboard GUID", "Dashboard Name", "Dashboard Owner", "Page GUID", "Page Name",
            "Widget ID", "Widget Title", "Original NRQL", "Modified NRQL",
            "Target Account(s)", # New column
            "NRQL Validation Status", "NRQL Validation Reason",
            "Old Query Output (Sample)", "New Query Output (Sample)", "Query Output Match", # New columns
            "Update Status", "Update Errors"
        ]
        with open(results_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            writer.writerows(all_processed_widgets_details)

        print(f"Successfully saved overall results to {results_file}")
    except IOError as e:
        print(f"Error saving overall results to {results_file}: {e}")


if __name__ == "__main__":
    main()
