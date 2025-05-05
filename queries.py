def build_update_widget_mutation(config: dict) -> str:
    import json
    def clean_nrql(query: str) -> str:
        lines = query.encode("utf-8").decode("unicode_escape").splitlines()
        no_comments = [line for line in lines if not line.strip().startswith("--")]
        joined = " ".join(no_comments).replace('"', '\\"')
        return joined

    clean_query = clean_nrql(config["updated_query"])

    raw_config = {
        "nrqlQueries": [{
            "accountId": config["account_id"],
            "query": clean_query
        }],
        "visualization": config.get("visualization_id", "viz.line"),
        "facet": config.get("facet", []),
        "yAxisLeft": config.get("y_axis_left", {}),
        "yAxisRight": config.get("y_axis_right", {}),
        "linkedEntityGuids": config.get("linked_entity_guids", []),
        "thresholds": config.get("thresholds", []),
        "legend": config.get("legend", {}),
        "title": config.get("title", "")
    }

    escaped_raw_config = json.dumps(raw_config).replace('"', '\"')
    layout_fields = ', '.join(f'{k}: {v}' for k, v in config["layout"].items())

    return f"""
    mutation {{
      dashboardUpdateWidget(
        guid: \"{config['widget_guid']}\",
        rawConfiguration: \"{escaped_raw_config}\",
        layout: {{
          {layout_fields}
        }}
      ) {{
        errors {{
          description
        }}
        widget {{
          id
          title
          layout {{
            column
            row
            width
            height
          }}
          rawConfiguration
        }}
      }}
    }}
    """

def build_update_alert_condition_mutation(condition_id: int, name: str, query: str, enabled: bool = True) -> str:
    escaped_query = query.replace('"', '\\"')
    return f"""
    mutation {{
      alertsNrqlConditionStaticUpdate(
        id: {condition_id},
        condition: {{
          name: \"{name}\"
          enabled: {str(enabled).lower()}
          nrql: {{
            query: \"{escaped_query}\"
          }}
        }}
      ) {{
        nrqlCondition {{
          id
          name
          nrql {{ query }}
        }}
      }}
    }}
    """

def build_dashboard_export_query(guid: str) -> str:
    return f"""
    query {{
      actor {{
        entity(guid: \"{guid}\") {{
          ... on DashboardEntity {{
            name
            pages {{
              name
              widgets {{
                id
                title
                rawConfiguration
                layout {{ column row width height }}
              }}
            }}
          }}
        }}
      }}
    }}
    """

def build_alert_conditions_export_query(account_id: int) -> str:
    return f"""
    query {{
      actor {{
        account(id: {account_id}) {{
          alerts {{
            nrqlConditionsSearch(searchCriteria: {{}}) {{
              nrqlConditions {{
                id
                name
                nrql {{ query }}
              }}
            }}
          }}
        }}
      }}
    }}
    """

def build_nrql_validation_query(account_id: int, query: str) -> str:
    safe_query = query.encode("utf-8").decode("unicode_escape").replace('"', '\\"').replace("\n", " ")
    return f"""
    query {{
      actor {{
        account(id: {account_id}) {{
          nrql {{
            queryValidate(query: \"{safe_query}\") {{
              valid
              error {{
                description
              }}
            }}
          }}
        }}
      }}
    }}
    """