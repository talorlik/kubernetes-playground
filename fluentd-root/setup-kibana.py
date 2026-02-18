#!/usr/bin/env python3
"""
Creates Kibana index patterns (predefined common indexes) and two dashboards:
  - HTTP Access Logs  (all httpd traffic)
  - HTTP Errors       (4xx / 5xx only)

Run after the stack is up:  python3 setup-kibana.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

KIBANA_URL = os.environ.get("KIBANA_URL", "http://localhost:5601")

# Predefined common index patterns (created automatically).
# All EFK logs use fluentd-*; add more here if you use other index names.
COMMON_INDEX_PATTERNS = [
    {
        "id": "fluentd-index-pattern",
        "title": "fluentd-*",
        "timeFieldName": "@timestamp",
        "default": True,
    },
    # Optional: add more patterns as your stack grows, e.g.:
    # {"id": "logs-index-pattern", "title": "logs-*", "timeFieldName": "@timestamp", "default": False},
]
INDEX_PATTERN_ID = COMMON_INDEX_PATTERNS[0]["id"]  # used by dashboards


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req(method, path, body=None):
    url = f"{KIBANA_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"kbn-xsrf": "true", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return {"status": "exists"}
        print(f"  HTTP {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        sys.exit(1)


def wait_for_kibana(max_seconds=180):
    print("Waiting for Kibana to be green...")
    for _ in range(max_seconds // 5):
        try:
            with urllib.request.urlopen(f"{KIBANA_URL}/api/status", timeout=5) as r:
                state = json.loads(r.read()).get("status", {}).get("overall", {}).get("state", "")
                if state == "green":
                    print("  Kibana is ready.\n")
                    return
                print(f"  state={state}, retrying...")
        except Exception as exc:
            print(f"  not reachable ({exc}), retrying...")
        time.sleep(5)
    print("Kibana never became ready.", file=sys.stderr)
    sys.exit(1)


def _search_source(query=""):
    return json.dumps({
        "query": {"query": query, "language": "kuery"},
        "filter": [],
        "indexRefName": "kibanaSavedObjectMeta.searchSourceJSON.index",
    })


# ---------------------------------------------------------------------------
# Saved-object creators
# ---------------------------------------------------------------------------

def refresh_index_pattern_fields(pattern_id):
    """
    Reload the index pattern's field list from Elasticsearch so @timestamp
    and other fields exist. Prevents 'field @timestamp no longer exists' in Discover.
    Uses Kibana 7.13+ Update index pattern API (optional; may not exist in all setups).
    """
    url = f"{KIBANA_URL}/api/index_patterns/index_pattern/{pattern_id}"
    body = json.dumps({
        "refresh_fields": True,
        "index_pattern": {"fields": []},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"kbn-xsrf": "true", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            json.loads(resp.read())
        print(f"  Refreshed field list for {pattern_id}")
        return True
    except urllib.error.HTTPError as e:
        print(f"  Note: could not refresh index pattern fields ({e.code}); "
              "if Discover shows '@timestamp no longer exists', refresh the "
              "index pattern in Stack Management or re-run this script after "
              "logs are flowing.", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"  Note: could not refresh index pattern ({exc}); "
              "if Discover shows '@timestamp no longer exists', refresh the "
              "index pattern in Stack Management.", file=sys.stderr)
        return False


def create_index_patterns():
    """Create all predefined common index patterns and set default."""
    print("Creating predefined index patterns...")
    default_id = None
    for spec in COMMON_INDEX_PATTERNS:
        pid = spec["id"]
        title = spec["title"]
        time_field = spec.get("timeFieldName", "@timestamp")
        print(f"  {title} (id={pid})")
        _req("POST", f"/api/saved_objects/index-pattern/{pid}?overwrite=true", {
            "attributes": {"title": title, "timeFieldName": time_field},
        })
        if spec.get("default"):
            default_id = pid
    if default_id:
        _set_default_index_pattern(default_id)
    # Reload field list from ES so @timestamp exists (avoids Discover error)
    refresh_index_pattern_fields(default_id)


def _set_default_index_pattern(pattern_id):
    """Set the default index pattern for Discover/dashboards."""
    url = f"{KIBANA_URL}/api/kibana/settings/defaultIndex"
    body = json.dumps({"value": pattern_id}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"kbn-xsrf": "true", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            json.loads(resp.read())
            print(f"  Default index pattern set to: {pattern_id}")
    except urllib.error.HTTPError as e:
        # 7.13 may use a different API; non-fatal
        print(f"  Note: could not set default index pattern ({e.code})", file=sys.stderr)


def create_viz(vis_id, title, vis_type, params, aggs, query=""):
    print(f"  viz: {title}")
    vis_state = json.dumps({"title": title, "type": vis_type, "params": params, "aggs": aggs})
    _req("POST", f"/api/saved_objects/visualization/{vis_id}?overwrite=true", {
        "attributes": {
            "title": title,
            "visState": vis_state,
            "uiStateJSON": "{}",
            "description": "",
            "kibanaSavedObjectMeta": {"searchSourceJSON": _search_source(query)},
        },
        "references": [{
            "name": "kibanaSavedObjectMeta.searchSourceJSON.index",
            "type": "index-pattern",
            "id": INDEX_PATTERN_ID,
        }],
    })


def create_dashboard(dash_id, title, panels, dash_query=""):
    """panels = list of (vis_id, x, y, w, h)"""
    print(f"Dashboard: {title}")
    panel_json = []
    refs = []
    for i, (vid, x, y, w, h) in enumerate(panels):
        pname = f"panel_{i + 1}"
        panel_json.append({
            "version": "7.13.1",
            "type": "visualization",
            "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(i + 1)},
            "panelIndex": str(i + 1),
            "embeddableConfig": {"enhancements": {}},
            "panelRefName": pname,
        })
        refs.append({"name": pname, "type": "visualization", "id": vid})

    _req("POST", f"/api/saved_objects/dashboard/{dash_id}?overwrite=true", {
        "attributes": {
            "title": title,
            "hits": 0,
            "description": "",
            "panelsJSON": json.dumps(panel_json),
            "optionsJSON": json.dumps({"useMargins": True, "syncColors": False, "hidePanelTitles": False}),
            "version": 1,
            "timeRestore": True,
            "timeTo": "now",
            "timeFrom": "now-24h",
            "refreshInterval": {"pause": False, "value": 30000},
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps({
                    "query": {"query": dash_query, "language": "kuery"},
                    "filter": [],
                }),
            },
        },
        "references": refs,
    })


# ---------------------------------------------------------------------------
# Visualisation definitions
# ---------------------------------------------------------------------------

AREA_BASE_PARAMS = {
    "type": "area",
    "grid": {"categoryLines": False},
    "categoryAxes": [{"id": "CategoryAxis-1", "type": "category", "position": "bottom",
                      "show": True, "style": {}, "scale": {"type": "linear"},
                      "labels": {"show": True, "filter": True, "truncate": 100}, "title": {}}],
    "valueAxes": [{"id": "ValueAxis-1", "name": "LeftAxis-1", "type": "value", "position": "left",
                   "show": True, "style": {}, "scale": {"type": "linear", "mode": "normal"},
                   "labels": {"show": True, "rotate": 0, "filter": False, "truncate": 100},
                   "title": {"text": "Count"}}],
    "seriesParams": [{"show": True, "type": "area", "mode": "stacked",
                      "data": {"label": "Count", "id": "1"},
                      "drawLinesBetweenPoints": True, "lineWidth": 2,
                      "showCircles": True, "interpolate": "linear",
                      "valueAxis": "ValueAxis-1"}],
    "addTooltip": True, "addLegend": True, "legendPosition": "right",
    "times": [], "addTimeMarker": False,
    "thresholdLine": {"show": False, "value": 10, "width": 1, "style": "full", "color": "#E7664C"},
    "labels": {},
}

DATE_HIST_AGG = {
    "id": "2", "enabled": True, "type": "date_histogram",
    "params": {"field": "@timestamp", "useNormalizedEsInterval": True,
               "scaleMetricValues": False, "interval": "auto",
               "drop_partials": False, "min_doc_count": 1, "extended_bounds": {}},
    "schema": "segment",
}

COUNT_AGG = {"id": "1", "enabled": True, "type": "count", "params": {}, "schema": "metric"}


def terms_agg(field, size=10, agg_id="2"):
    return {
        "id": agg_id, "enabled": True, "type": "terms",
        "params": {"field": field, "orderBy": "1", "order": "desc", "size": size,
                   "otherBucket": False, "otherBucketLabel": "Other",
                   "missingBucket": False, "missingBucketLabel": "Missing"},
        "schema": "segment" if agg_id == "2" else "bucket",
    }


def metric_params(label="", color_on_value=False):
    return {
        "addTooltip": True, "addLegend": False, "type": "metric",
        "metric": {
            "percentageMode": False, "useRanges": False,
            "colorSchema": "Green to Red",
            "metricColorMode": "Labels" if color_on_value else "None",
            "colorsRange": [{"type": "range", "from": 0, "to": 1},
                            {"type": "range", "from": 1, "to": 100000}],
            "labels": {"show": True}, "invertColors": False,
            "style": {"bgFill": "#000", "bgColor": False, "labelColor": color_on_value,
                      "subText": "", "fontSize": 60},
        },
    }


def pie_params(donut=True, show_labels=False):
    return {
        "type": "pie", "addTooltip": True, "addLegend": True,
        "legendPosition": "right", "isDonut": donut,
        "labels": {"show": show_labels, "values": True, "last_level": True, "truncate": 100},
    }


TABLE_PARAMS = {
    "perPage": 10, "showPartialRows": False, "showMetricsAtAllLevels": False,
    "sort": {"columnIndex": None, "direction": None},
    "showTotal": False, "totalFunc": "sum", "percentageCol": "",
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    wait_for_kibana()
    create_index_patterns()

    # ── HTTP Access Log visualisations ──────────────────────────────────────
    HTTP_Q = '@log_name: "httpd"'
    print("\nHTTP Access Log visualisations:")

    create_viz("viz-http-total", "HTTP – Total Requests", "metric",
               metric_params("Total Requests"),
               [{"id": "1", "enabled": True, "type": "count",
                 "params": {"customLabel": "Total Requests"}, "schema": "metric"}],
               HTTP_Q)

    create_viz("viz-http-over-time", "HTTP – Requests Over Time", "area",
               AREA_BASE_PARAMS,
               [COUNT_AGG, DATE_HIST_AGG],
               HTTP_Q)

    create_viz("viz-http-status-codes", "HTTP – Status Code Distribution", "pie",
               pie_params(donut=True),
               [COUNT_AGG, terms_agg("code")],
               HTTP_Q)

    create_viz("viz-http-methods", "HTTP – Request Methods", "pie",
               pie_params(donut=False, show_labels=True),
               [COUNT_AGG, terms_agg("method")],
               HTTP_Q)

    create_viz("viz-http-top-paths", "HTTP – Top Requested Paths", "table",
               TABLE_PARAMS,
               [COUNT_AGG, {**terms_agg("path"), "schema": "bucket"}],
               HTTP_Q)

    create_viz("viz-http-top-clients", "HTTP – Top Client IPs", "table",
               TABLE_PARAMS,
               [COUNT_AGG, {**terms_agg("host"), "schema": "bucket"}],
               HTTP_Q)

    # ── Error visualisations ─────────────────────────────────────────────────
    ERR_Q = '@log_name: "httpd" and code >= 400'
    print("\nError visualisations:")

    create_viz("viz-err-total", "Errors – Total Count", "metric",
               metric_params("Total Errors", color_on_value=True),
               [{"id": "1", "enabled": True, "type": "count",
                 "params": {"customLabel": "Total Errors (4xx/5xx)"}, "schema": "metric"}],
               ERR_Q)

    create_viz("viz-err-over-time", "Errors – Over Time", "area",
               {**AREA_BASE_PARAMS,
                "valueAxes": [{**AREA_BASE_PARAMS["valueAxes"][0],
                               "title": {"text": "Error Count"}}]},
               [COUNT_AGG, DATE_HIST_AGG],
               ERR_Q)

    create_viz("viz-err-status-breakdown", "Errors – Status Code Breakdown", "pie",
               pie_params(donut=True, show_labels=True),
               [COUNT_AGG, terms_agg("code")],
               ERR_Q)

    create_viz("viz-err-top-paths", "Errors – Top Error Paths", "table",
               TABLE_PARAMS,
               [COUNT_AGG,
                {**terms_agg("path", agg_id="2"), "schema": "bucket"},
                {**terms_agg("code", agg_id="3"), "schema": "bucket"}],
               ERR_Q)

    # ── Dashboards ───────────────────────────────────────────────────────────
    # Grid is 48 columns wide; heights in rows (~20 px each)
    print("\nCreating dashboards...")

    create_dashboard(
        "dashboard-http-access-logs",
        "HTTP Access Logs",
        [
            # Row 0: metric (small) + methods pie
            ("viz-http-total",        0,  0, 12,  8),
            ("viz-http-methods",     12,  0, 12,  8),
            ("viz-http-status-codes",24,  0, 24,  8),
            # Row 8: requests over time (full width)
            ("viz-http-over-time",    0,  8, 48, 15),
            # Row 23: tables
            ("viz-http-top-paths",    0, 23, 24, 15),
            ("viz-http-top-clients", 24, 23, 24, 15),
        ],
        '@log_name: "httpd"',
    )

    create_dashboard(
        "dashboard-errors",
        "HTTP Errors (4xx / 5xx)",
        [
            # Row 0: error metric + status breakdown
            ("viz-err-total",           0,  0, 12,  8),
            ("viz-err-status-breakdown",12,  0, 36,  8),
            # Row 8: errors over time
            ("viz-err-over-time",       0,  8, 48, 15),
            # Row 23: top error paths table
            ("viz-err-top-paths",       0, 23, 48, 15),
        ],
        '@log_name: "httpd" and code >= 400',
    )

    print("\n✓  All done!")
    base = KIBANA_URL.rstrip("/")
    print(f"\n  HTTP Access Logs →  {base}/app/dashboards#/view/dashboard-http-access-logs")
    print(f"  HTTP Errors      →  {base}/app/dashboards#/view/dashboard-errors")


if __name__ == "__main__":
    main()
