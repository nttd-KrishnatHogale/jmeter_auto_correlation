from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, List

from .config import APP_VERSION
from .detection import detect_candidates
from .jmeter_tree import collect_samplers
from .modifier import apply_candidates
from .parser import parse_jmx
from .table import candidates_to_df
from .xml_utils import describe_parse_position, sanitize_jmx_xml


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="JMeter Auto-Correlation", layout="wide")
    st.title("JMeter Auto-Correlation Generator")
    st.caption(
        "Upload a .jmx, review dynamic candidates, then download a correlated "
        f".jmx with Regex Extractors and ${{VARIABLE}} replacements. Version: {APP_VERSION}"
    )

    with st.expander("Important limitation", expanded=False):
        st.write(
            "A .jmx file normally contains recorded requests, not live response bodies. "
            "This app detects dynamic-looking hardcoded request values and infers the "
            "extractor source sampler as the previous HTTP request. Review the source "
            "sampler before downloading the final file."
        )

    uploaded = st.file_uploader("Upload JMeter .jmx file", type=["jmx", "xml"])
    min_len = st.sidebar.slider("Minimum value length", min_value=6, max_value=32, value=8)
    require_reuse = st.sidebar.checkbox(
        "Only show values that appear in at least one request",
        value=True,
    )

    if not uploaded:
        st.info("Upload a JMX file to start.")
        return

    raw = uploaded.read()
    try:
        tree, xml_fixes = parse_jmx(raw)
    except ET.ParseError as exc:
        cleaned_preview, fix_count = sanitize_jmx_xml(raw)
        st.error(
            f"Could not parse XML/JMX with {APP_VERSION} even after sanitizing "
            f"invalid recorder characters: {exc}"
        )
        if fix_count:
            st.warning(
                f"The pre-parser sanitizer removed {fix_count} invalid XML character "
                "reference(s), but another XML issue remains."
            )

        diag_raw = describe_parse_position(raw, exc)
        diag_clean = describe_parse_position(cleaned_preview, exc)
        if diag_raw:
            st.code(diag_raw, language="text")
        if diag_clean and diag_clean != diag_raw:
            st.code("After sanitizer:\n" + diag_clean, language="text")

        st.download_button(
            "Download sanitized JMX for troubleshooting",
            data=cleaned_preview,
            file_name=uploaded.name.rsplit(".", 1)[0] + "_sanitized_for_debug.jmx",
            mime="application/xml",
        )
        return

    if xml_fixes:
        st.warning(
            f"The JMX contained {xml_fixes} XML-invalid binary/control character "
            "reference(s). They were removed for parsing. This usually comes from "
            "recorded gzip/protobuf/binary request bodies."
        )

    samplers = collect_samplers(tree.getroot())
    candidates = detect_candidates(samplers, min_length=min_len, require_reuse=require_reuse)

    col1, col2 = st.columns(2)
    col1.metric("HTTP samplers found", len(samplers))
    col2.metric("Correlation candidates", len(candidates))

    if not candidates:
        st.warning(
            "No candidates found. Try reducing the minimum value length or check that "
            "the JMX contains hardcoded tokens in request parameters, paths, bodies, or headers."
        )
        return

    st.subheader("Review candidates")
    edited = st.data_editor(
        candidates_to_df(candidates, samplers),
        width="stretch",
        hide_index=True,
        disabled=[
            "id",
            "parameter",
            "type",
            "extractor",
            "confidence",
            "score",
            "used_in",
            "target_samplers",
            "sample_value",
            "reason",
        ],
        column_config={
            "selected": st.column_config.CheckboxColumn("Apply", default=True),
            "id": None,
            "source_sampler": st.column_config.SelectboxColumn(
                "Extractor source sampler",
                options=[sampler.name for sampler in samplers],
            ),
            "variable": st.column_config.TextColumn("Variable name"),
        },
    )

    name_to_index = {sampler.name: sampler.index for sampler in samplers}
    selected_ids: List[str] = []
    source_overrides: Dict[str, int] = {}

    for _, row in edited.iterrows():
        candidate_id = row["id"]
        candidate = next(candidate for candidate in candidates if candidate.id == candidate_id)
        candidate.variable_name = (
            re.sub(r"[^A-Za-z0-9_]", "_", str(row["variable"]).strip())
            or candidate.variable_name
        )
        candidate.source_sampler_index = name_to_index.get(
            row["source_sampler"],
            candidate.source_sampler_index,
        )
        source_overrides[candidate_id] = candidate.source_sampler_index
        if bool(row["selected"]):
            selected_ids.append(candidate_id)

    st.subheader("Details")
    with st.expander("Show extraction patterns"):
        for candidate in candidates:
            st.code(f"{candidate.variable_name}: {candidate.extraction_pattern}", language="text")

    if st.button("Generate correlated JMX", type="primary", disabled=not selected_ids):
        try:
            fresh_tree, _ = parse_jmx(raw)
            new_bytes, added, replaced = apply_candidates(
                fresh_tree,
                candidates,
                selected_ids,
                source_overrides,
            )
            output_name = uploaded.name.rsplit(".", 1)[0] + "_correlated.jmx"
            st.success(
                f"Generated file. Added {added} extractor(s), replaced "
                f"{replaced} value occurrence(s)."
            )
            st.download_button(
                "Download correlated JMX",
                data=new_bytes,
                file_name=output_name,
                mime="application/xml",
            )
        except Exception as exc:
            st.exception(exc)
