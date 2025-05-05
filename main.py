from flask import Flask, request, jsonify
import asyncio
import aiohttp
from handlers.dashboard_widget_handler import fetch_dashboard_json, validate_nrql_query
from handlers.alert_condition_handler import fetch_alert_conditions
from handlers.shared import send_graphql_request
from modules.modules import extract_widget_configs_from_dashboard_json, update_configs_with_status
from modules.queries import build_update_widget_mutation, build_update_alert_condition_mutation
from common.common import export_dashboard_to_file, save_to_csv

app = Flask(__name__)

@app.route('/update-dashboard', methods=['POST'])
def update_dashboard():
    data = request.get_json()
    dashboard_guid = data.get("dashboard_guid")
    if not dashboard_guid:
        return {"error": "dashboard_guid is required"}, 400

    async def run():
        async with aiohttp.ClientSession() as session:
            dashboard_json = await fetch_dashboard_json(session, dashboard_guid)
            export_dashboard_to_file(dashboard_json, f"{dashboard_json['name']}_export.json")

            configs = extract_widget_configs_from_dashboard_json(dashboard_json)
            validated = [
                await validate_nrql_query(session, c['account_id'], c['updated_query'])
                for c in configs
            ]
            valid_configs = [c for c, ok in zip(configs, validated) if ok]

            tasks = [
                send_graphql_request(session, build_update_widget_mutation(c))
                for c in valid_configs
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            updated_configs = update_configs_with_status(valid_configs, results)
            save_to_csv(updated_configs, f"{dashboard_json['name']}_widgets_updated.csv")

            account_ids = {c['account_id'] for c in configs}
            for aid in account_ids:
                alert_conditions = await fetch_alert_conditions(session, aid)
                for cond in alert_conditions:
                    old = cond['nrql']['query']
                    new = old.replace("K8s", "OTelK8s")
                    if await validate_nrql_query(session, aid, new):
                        mutation = build_update_alert_condition_mutation(
                            condition_id=cond['id'],
                            name=cond['name'] + " Migrated",
                            query=new
                        )
                        await send_graphql_request(session, mutation)

            return {
                "dashboard": dashboard_json['name'],
                "widgets_total": len(configs),
                "widgets_updated": len(valid_configs)
            }

    result = asyncio.run(run())
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)