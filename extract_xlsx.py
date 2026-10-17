#!/usr/bin/env python3
"""Extract structure + content of an xlsx workbook to TSV/JSON artifacts.

Outputs (in extracted/):
  <safe_sheet>__formulas.tsv   cell_ref \t formula_or_literal  (non-empty cells)
  <safe_sheet>__values.tsv     cell_ref \t cached_value        (non-empty cells)
  metadata.json                sheets, dims, counts, names, validations,
                              merges, comments, cond. formatting, charts,
                              hidden sheets
  crossrefs.txt                which sheet names appear in each sheet's formulas
"""
import json
import os
import re
import sys

import openpyxl
from openpyxl.utils import get_column_letter

FILE = sys.argv[1] if len(sys.argv) > 1 else "excel_mitigation_model.xlsx"
OUT = "extracted"
os.makedirs(OUT, exist_ok=True)


def sanitize(v):
    """Make any value TSV-safe (single line, no tabs)."""
    if v is None:
        return ""
    s = str(v)
    s = s.replace("\\", "\\\\").replace("\t", "\\t")
    s = s.replace("\r", "\\r").replace("\n", "\\n")
    return s


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:80]


def is_empty(v):
    return v is None or (isinstance(v, str) and v.strip() == "")


def chart_title_text(ch):
    try:
        t = ch.title
        if t is None:
            return None
        if isinstance(t, str):
            return t
        tx = getattr(t, "tx", None)
        if tx is not None:
            rich = getattr(tx, "rich", None)
            if rich is not None and getattr(rich, "p", None):
                parts = []
                for p in rich.p:
                    for r in (getattr(p, "r", None) or []):
                        if getattr(r, "t", None):
                            parts.append(r.t)
                if parts:
                    return "".join(parts)
    except Exception:
        pass
    return None


print(f"Loading {FILE} (formulas)...")
wb_f = openpyxl.load_workbook(FILE, data_only=False, rich_text=False)
print(f"Loading {FILE} (cached values)...")
wb_v = openpyxl.load_workbook(FILE, data_only=True, rich_text=False)

metadata = {
    "source_file": FILE,
    "openpyxl_version": openpyxl.__version__,
    "sheet_order": list(wb_f.sheetnames),
    "sheets": [],
    "defined_names_global": [],
    "defined_names_sheet_local": [],
    "hidden_sheets": [],
}

sheet_stats = {}

for sheet_name in wb_f.sheetnames:
    ws_f = wb_f[sheet_name]
    ws_v = wb_v[sheet_name]
    safe = safe_name(sheet_name)
    f_path = os.path.join(OUT, f"{safe}__formulas.tsv")
    v_path = os.path.join(OUT, f"{safe}__values.tsv")

    n_cells = 0
    n_formulas = 0
    n_missing_cached = 0
    comments = []

    with open(f_path, "w", encoding="utf-8") as ff, open(
        v_path, "w", encoding="utf-8"
    ) as vf:
        # iterate via calculated dimension to skip fully empty rows/cols
        max_r = ws_f.max_row or 0
        max_c = ws_f.max_column or 0
        for row in ws_f.iter_rows(min_row=1, max_row=max_r,
                                  min_col=1, max_col=max_c):
            for cell in row:
                v = cell.value
                if is_empty(v):
                    continue
                n_cells += 1
                ref = cell.coordinate
                if cell.data_type == "f" or (
                    isinstance(v, str) and v.startswith("=")
                ):
                    n_formulas += 1
                    ff.write(f"{ref}\t{sanitize(v)}\n")
                    cv = ws_v[ref].value
                    if is_empty(cv):
                        n_missing_cached += 1
                        vf.write(f"{ref}\t<NO_CACHED_VALUE>\n")
                    else:
                        vf.write(f"{ref}\t{sanitize(cv)}\n")
                else:
                    ff.write(f"{ref}\t{sanitize(v)}\n")
                    cv = ws_v[ref].value
                    if not is_empty(cv):
                        vf.write(f"{ref}\t{sanitize(cv)}\n")
                if cell.comment is not None:
                    comments.append(
                        {"ref": ref, "text": sanitize(cell.comment.text)}
                    )

    # data validations
    validations = []
    try:
        for dv in ws_f.data_validations.dataValidation:
            validations.append(
                {
                    "ranges": str(dv.sqref),
                    "type": dv.type,
                    "operator": dv.operator,
                    "formula1": sanitize(dv.formula1),
                    "formula2": sanitize(dv.formula2),
                    "allow_blank": dv.allowBlank,
                }
            )
    except Exception as e:
        validations.append({"error": str(e)})

    # merged cells
    merges = [str(m) for m in ws_f.merged_cells.ranges]

    # conditional formatting
    cond_fmt = []
    try:
        for cf in ws_f.conditional_formatting:
            rules = []
            for rule in cf.rules:
                rd = {"type": rule.type}
                if getattr(rule, "operator", None):
                    rd["operator"] = rule.operator
                if getattr(rule, "formula", None):
                    rd["formula"] = [sanitize(f) for f in rule.formula]
                rules.append(rd)
            cond_fmt.append({"range": str(cf.sqref), "rules": rules})
    except Exception as e:
        cond_fmt.append({"error": str(e)})

    # charts
    charts = []
    try:
        for ch in getattr(ws_f, "_charts", []) or []:
            charts.append(
                {
                    "class": type(ch).__name__,
                    "tagname": getattr(ch, "tagname", None),
                    "title": chart_title_text(ch),
                }
            )
    except Exception as e:
        charts.append({"error": str(e)})

    # sheet-local defined names
    try:
        for dn_name, dn in ws_f.defined_names.items():
            metadata["defined_names_sheet_local"].append(
                {"sheet": sheet_name, "name": dn_name, "target": dn.value}
            )
    except Exception:
        pass

    state = ws_f.sheet_state
    if state in ("hidden", "veryHidden"):
        metadata["hidden_sheets"].append(
            {"sheet": sheet_name, "state": state}
        )

    sheet_info = {
        "name": sheet_name,
        "safe_name": safe,
        "visibility": state,
        "dimensions": ws_f.dimensions,
        "max_row": ws_f.max_row,
        "max_column": ws_f.max_column,
        "non_empty_cells": n_cells,
        "formula_cells": n_formulas,
        "formulas_missing_cached_value": n_missing_cached,
        "merged_ranges": merges,
        "data_validations": validations,
        "comments": comments,
        "conditional_formatting": cond_fmt,
        "charts": charts,
        "formulas_tsv": f"{safe}__formulas.tsv",
        "values_tsv": f"{safe}__values.tsv",
    }
    metadata["sheets"].append(sheet_info)
    sheet_stats[sheet_name] = n_cells
    print(
        f"  [{sheet_name}] dims={ws_f.dimensions} cells={n_cells} "
        f"formulas={n_formulas} comments={len(comments)} "
        f"charts={len(charts)} dv={len(validations)} cf={len(cond_fmt)} "
        f"merges={len(merges)} state={state}"
    )

# global defined names
try:
    for dn_name, dn in wb_f.defined_names.items():
        metadata["defined_names_global"].append(
            {"name": dn_name, "target": dn.value}
        )
except Exception as e:
    metadata["defined_names_global"].append({"error": str(e)})

with open(os.path.join(OUT, "metadata.json"), "w", encoding="utf-8") as f:
    json.dump(metadata, f, indent=2, ensure_ascii=False)

# crossrefs: which other sheet names appear in each sheet's formulas
all_names = list(wb_f.sheetnames)
with open(os.path.join(OUT, "crossrefs.txt"), "w", encoding="utf-8") as f:
    for sheet_name in all_names:
        safe = safe_name(sheet_name)
        fpath = os.path.join(OUT, f"{safe}__formulas.tsv")
        refs = []
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as tf:
                text = tf.read()
            for other in all_names:
                if other == sheet_name:
                    continue
                cnt = 0
                for pat in (f"'{other}'!", f"{other}!"):
                    if pat:
                        cnt += text.count(pat)
                if cnt:
                    refs.append(f"{other} ({cnt} refs)")
        f.write(
            f"{sheet_name} -> "
            + (", ".join(refs) if refs else "(no cross-sheet references)")
            + "\n"
        )

print("Done. Artifacts in extracted/")
