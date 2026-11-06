"""Interactive HTML reporting for roof alternative analysis."""

import json
from pathlib import Path

import polars as pl
from plotly.offline import get_plotlyjs

REPORT_COLUMNS = (
    "asset_id",
    "year",
    "scenario_id",
    "official_current_material_id",
    "installation_event",
    "burnout_replacement_event",
    "annual_repair_cost_usd",
    "annual_climate_risk_cost_usd",
    "annual_avoided_damage_usd",
    "cumulative_avoided_damage_usd",
    "cumulative_discounted_avoided_damage_usd",
    "annual_net_benefit_usd",
    "cumulative_net_benefit_usd",
    "net_present_value_usd",
)
REPORT_EXCLUDED_SCENARIOS = ("NEW_TILE",)


def write_alternative_analysis_report(
    annual_analysis: pl.DataFrame,
    output_path: Path,
) -> None:
    """Write one self-contained report with client-side asset and metric selection."""
    missing = sorted(set(REPORT_COLUMNS) - set(annual_analysis.columns))
    if missing:
        raise ValueError(f"annual_analysis is missing report columns: {missing}")
    if annual_analysis.is_empty():
        raise ValueError("annual_analysis cannot be empty")
    records = (
        annual_analysis.filter(
            ~pl.col("scenario_id").is_in(REPORT_EXCLUDED_SCENARIOS)
        )
        .select(REPORT_COLUMNS)
        .sort(["asset_id", "year", "scenario_id"])
        .to_dicts()
    )
    assets = sorted(annual_analysis["asset_id"].unique().to_list())
    payload = json.dumps(records, separators=(",", ":")).replace("<", "\\u003c")
    asset_options = "".join(
        f'<option value="{_escape_html(asset)}">{_escape_html(asset)}</option>'
        for asset in assets
    )
    html = _document(payload, asset_options, get_plotlyjs())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".html.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output_path)


def _document(payload: str, asset_options: str, plotly_javascript: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CADENCE Roof Alternative Analysis</title>
<style>
:root {{ --ink:#17211c; --muted:#607067; --paper:#f5f7f2; --line:#cfd8d1; --accent:#087e8b; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:linear-gradient(135deg,#edf3ed 0%,#f8f6ef 55%,#eef4f6 100%); color:var(--ink); font-family:"Avenir Next","Gill Sans",sans-serif; }}
main {{ min-height:100vh; padding:24px clamp(16px,4vw,56px) 32px; }}
header {{ display:flex; align-items:end; justify-content:space-between; gap:20px; border-bottom:1px solid var(--line); padding-bottom:18px; }}
h1 {{ margin:0; font-family:"Iowan Old Style","Palatino Linotype",serif; font-size:clamp(28px,4vw,48px); font-weight:600; letter-spacing:0; }}
.controls {{ display:flex; flex-wrap:wrap; gap:12px; }}
label {{ display:grid; gap:5px; color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }}
select {{ min-width:180px; border:1px solid #aebcb3; border-radius:4px; background:#fff; color:var(--ink); padding:9px 34px 9px 10px; font:600 14px "Avenir Next","Gill Sans",sans-serif; }}
#chart {{ width:100%; height:min(72vh,720px); min-height:430px; margin-top:20px; background:rgba(255,255,255,.7); border:1px solid var(--line); border-radius:6px; }}
.status {{ min-height:22px; margin:10px 2px 0; color:var(--muted); font-size:13px; }}
@media (max-width:760px) {{ main {{ padding-top:16px; }} header {{ align-items:start; flex-direction:column; }} .controls,label,select {{ width:100%; }} #chart {{ height:66vh; min-height:420px; }} }}
</style>
<script>{plotly_javascript}</script>
</head>
<body>
<main>
<header><h1>Roof Alternative Analysis</h1><div class="controls">
<label>Asset<select id="asset-select">{asset_options}</select></label>
<label>Metric<select id="metric-select">
<option value="annual_repair_cost_usd">Annual repair cost</option>
<option value="annual_climate_risk_cost_usd">Repair + loss of use</option>
<option value="annual_avoided_damage_usd">Annual avoided damage</option>
<option value="cumulative_avoided_damage_usd">Cumulative avoided damage</option>
<option value="cumulative_discounted_avoided_damage_usd">Discounted avoided damage</option>
<option value="annual_net_benefit_usd">Annual lifecycle net benefit</option>
<option value="cumulative_net_benefit_usd">Cumulative lifecycle net benefit</option>
<option value="net_present_value_usd">Net present value</option>
</select></label>
</div></header>
<div id="chart"></div><div class="status" id="status"></div>
</main>
<script>
const rows={payload};
const scenarios=["BASELINE_CURRENT","NEW_ASPHALT","NEW_METAL"];
const colors={{BASELINE_CURRENT:"#26352d",NEW_ASPHALT:"#d1495b",NEW_METAL:"#087e8b"}};
const metricLabels={{annual_repair_cost_usd:"Annual repair cost",annual_climate_risk_cost_usd:"Repair + loss of use",annual_avoided_damage_usd:"Annual avoided damage",cumulative_avoided_damage_usd:"Cumulative avoided damage",cumulative_discounted_avoided_damage_usd:"Discounted avoided damage",annual_net_benefit_usd:"Annual lifecycle net benefit",cumulative_net_benefit_usd:"Cumulative lifecycle net benefit",net_present_value_usd:"Net present value"}};
const assetSelect=document.getElementById("asset-select");
const metricSelect=document.getElementById("metric-select");
function formatMaterial(materialId) {{
    const value=(materialId||"").replace("OFFICIAL_","").toLowerCase();
    return value.charAt(0).toUpperCase()+value.slice(1);
}}
function render() {{
  const asset=assetSelect.value, metric=metricSelect.value;
  const selected=rows.filter(row=>row.asset_id===asset);
    const currentMaterial=selected.find(row=>row.scenario_id==="BASELINE_CURRENT")?.official_current_material_id;
    const labels={{BASELINE_CURRENT:`Installed roof ${{formatMaterial(currentMaterial)}}`,NEW_ASPHALT:"New asphalt",NEW_METAL:"New metal"}};
  const traces=scenarios.map(scenario=>{{
    const values=selected.filter(row=>row.scenario_id===scenario).sort((a,b)=>a.year-b.year);
        return {{type:"bar",name:labels[scenario],x:values.map(row=>row.year),y:values.map(row=>row[metric]),marker:{{color:colors[scenario]}},hovertemplate:"%{{x}}<br>%{{y:$,.0f}}<extra>"+labels[scenario]+"</extra>"}};
  }});
  const events=selected.filter(row=>row.installation_event && row[metric]!==null);
  if(events.length) traces.push({{type:"scatter",mode:"markers",name:"Installation / replacement",x:events.map(row=>row.year),y:events.map(row=>row[metric]),text:events.map(row=>labels[row.scenario_id]),marker:{{symbol:"diamond",size:9,color:events.map(row=>colors[row.scenario_id]),line:{{color:"#ffffff",width:1}}}},hovertemplate:"%{{text}}<br>%{{x}}<br>%{{y:$,.0f}}<extra>Roof event</extra>"}});
  const missing=selected.filter(row=>row[metric]===null).length;
  document.getElementById("status").textContent=missing?`${{missing}} values unavailable and shown as gaps.`:"All values available for this view.";
    Plotly.react("chart",traces,{{title:{{text:metricLabels[metric]+" · "+asset,x:0.02,font:{{size:20}}}},barmode:"group",bargap:0.15,bargroupgap:0.05,paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(255,255,255,.55)",font:{{family:"Avenir Next, Gill Sans, sans-serif",color:"#17211c"}},margin:{{l:72,r:24,t:64,b:62}},hovermode:"x unified",legend:{{orientation:"h",y:1.08,x:0}},xaxis:{{title:"Year",dtick:2,gridcolor:"#dfe5df"}},yaxis:{{title:"Real 2026 USD",tickprefix:"$",tickformat:",.0f",gridcolor:"#dfe5df",zerolinecolor:"#89988f"}}}},{{responsive:true,displaylogo:false}});
}}
assetSelect.addEventListener("change",render); metricSelect.addEventListener("change",render); render();
</script>
</body>
</html>"""


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )