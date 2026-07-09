"""SAP lookup via OData (SAP Gateway / S/4HANA API services).

Configured entirely through environment variables so credentials stay out of
the database:
  SAP_BASE_URL      e.g. https://s4hana.example.com:443/sap/opu/odata/sap
  SAP_USER          service account user
  SAP_PASSWORD      service account password
  SAP_CLIENT        optional, e.g. 100
  SAP_VERIFY_SSL    set to "false" only for self-signed test systems
  SAP_BOM_SERVICE   override BOM service segment (default API_BILL_OF_MATERIAL_SRV;v=0002)
  SAP_STOCK_SERVICE override stock service segment (default API_MATERIAL_STOCK_SRV)
"""
import json
import os

import requests
from flask import Blueprint, render_template, request
from flask_login import login_required

bp = Blueprint("sap", __name__, url_prefix="/sap")

# Columns shown first when present; keeps 50-field SAP entities readable.
STOCK_COLUMNS = [
    "Material", "Plant", "StorageLocation", "Batch", "InventoryStockType",
    "InventorySpecialStockType", "MatlWrhsStkQtyInMatlBaseUnit", "MaterialBaseUnit",
]
BOM_ITEM_COLUMNS = [
    "BillOfMaterialItemNumber", "BillOfMaterialComponent", "BillOfMaterialItemQuantity",
    "BillOfMaterialItemUnit", "BillOfMaterialItemCategory", "ComponentDescription",
]
BOM_HEADER_COLUMNS = [
    "BillOfMaterial", "Material", "Plant", "BillOfMaterialVariantUsage",
    "BillOfMaterialVariant", "BaseQuantity", "BaseUnit", "BillOfMaterialStatus",
]
MAX_COLS = 12


def sap_config():
    base = os.environ.get("SAP_BASE_URL", "").rstrip("/")
    return {
        "base": base,
        "user": os.environ.get("SAP_USER", ""),
        "password": os.environ.get("SAP_PASSWORD", ""),
        "client": os.environ.get("SAP_CLIENT", ""),
        "verify": os.environ.get("SAP_VERIFY_SSL", "true").lower() != "false",
        "bom_service": os.environ.get("SAP_BOM_SERVICE", "API_BILL_OF_MATERIAL_SRV;v=0002"),
        "stock_service": os.environ.get("SAP_STOCK_SERVICE", "API_MATERIAL_STOCK_SRV"),
        "configured": bool(base),
    }


def sap_get(cfg, path, params=None):
    params = dict(params or {})
    params.setdefault("$format", "json")
    if cfg["client"]:
        params["sap-client"] = cfg["client"]
    resp = requests.get(
        f"{cfg['base']}/{path.lstrip('/')}",
        params=params,
        auth=(cfg["user"], cfg["password"]) if cfg["user"] else None,
        headers={"Accept": "application/json"},
        timeout=20,
        verify=cfg["verify"],
    )
    resp.raise_for_status()
    return resp.json()


def scalars(item):
    return {
        k: v
        for k, v in item.items()
        if not k.startswith("__") and not isinstance(v, (dict, list))
    }


def results_of(data):
    """Result list from an OData v2 (d/results) or v4 (value) payload."""
    d = data.get("d", data)
    results = d.get("results", d.get("value", d))
    if isinstance(results, dict):
        results = [results]
    return results if isinstance(results, list) else []


def rows_from(data):
    return [scalars(item) for item in results_of(data)]


def pick_columns(rows, preferred=None):
    """Preferred columns that exist in the data, topped up to MAX_COLS with the rest."""
    if not rows:
        return []
    present = list(rows[0].keys())
    cols = [c for c in (preferred or []) if c in present]
    cols += [c for c in present if c not in cols]
    return cols[:MAX_COLS]


def escape_odata(value):
    return value.replace("'", "''")


def eq_filter(field, value):
    return f"{field} eq '{escape_odata(value)}'"


@bp.route("/")
@login_required
def lookup():
    cfg = sap_config()
    mode = request.args.get("mode", "product")
    q = request.args.get("q", "").strip()
    plant = request.args.get("plant", "").strip()
    rows, boms, raw, error = [], [], None, None
    preferred = None
    if cfg["configured"] and q:
        try:
            if mode == "product":
                data = sap_get(
                    cfg,
                    "API_PRODUCT_SRV/A_Product",
                    {"$filter": f"startswith(Product,'{escape_odata(q)}')", "$top": "25"},
                )
                rows = rows_from(data)
            elif mode == "batch":
                data = sap_get(
                    cfg,
                    "API_BATCH_SRV/Batch",
                    {"$filter": eq_filter("Material", q), "$top": "25"},
                )
                rows = rows_from(data)
            elif mode == "stock":
                filt = eq_filter("Material", q)
                if plant:
                    filt += " and " + eq_filter("Plant", plant)
                data = sap_get(
                    cfg,
                    f"{cfg['stock_service']}/A_MatlStkInAcctMod",
                    {"$filter": filt, "$top": "50"},
                )
                rows = rows_from(data)
                preferred = STOCK_COLUMNS
            elif mode == "bom":
                filt = eq_filter("Material", q)
                if plant:
                    filt += " and " + eq_filter("Plant", plant)
                data = sap_get(
                    cfg,
                    f"{cfg['bom_service']}/MaterialBOM",
                    {
                        "$filter": filt,
                        "$top": "10",
                        "$expand": "to_BillOfMaterialItem",
                    },
                )
                for header in results_of(data):
                    items_raw = header.get("to_BillOfMaterialItem") or {}
                    if isinstance(items_raw, dict):
                        items_raw = items_raw.get("results", [])
                    items = [scalars(i) for i in items_raw]
                    boms.append(
                        {
                            "header": scalars(header),
                            "header_cols": pick_columns([scalars(header)], BOM_HEADER_COLUMNS),
                            "components": items,
                            "item_cols": pick_columns(items, BOM_ITEM_COLUMNS),
                        }
                    )
            else:  # custom relative OData path, e.g. API_PRODUCT_SRV/A_Product?$top=5
                data = sap_get(cfg, q)
                raw = json.dumps(data, indent=2)[:20000]
        except requests.exceptions.RequestException as exc:
            error = f"SAP request failed: {exc}"
        except ValueError:
            error = "SAP returned a non-JSON response — check the service path and credentials."
    columns = pick_columns(rows, preferred)
    return render_template(
        "sap.html",
        cfg=cfg,
        mode=mode,
        q=q,
        plant=plant,
        rows=rows,
        boms=boms,
        columns=columns,
        raw=raw,
        error=error,
    )
