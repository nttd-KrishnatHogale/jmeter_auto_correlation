# JMeter Auto-Correlation Generator

This is the modular version of the original single-file Streamlit app.

## Folder structure

```text
jmeter_auto_correlation_modular/
├── app.py
├── requirements.txt
├── pyproject.toml
├── README.md
├── jmeter_auto_correlation/
│   ├── __init__.py
│   ├── config.py
│   ├── detection.py
│   ├── jmeter_tree.py
│   ├── models.py
│   ├── modifier.py
│   ├── parser.py
│   ├── self_test.py
│   ├── table.py
│   ├── ui.py
│   └── xml_utils.py
└── tests/
    └── test_sanitizer.py
```

## Run the app

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Run the built-in self-test

```bash
python app.py --self-test
```

or:

```bash
python -m jmeter_auto_correlation.self_test
```

## Module responsibilities

- `app.py`: thin entry point for Streamlit or self-test mode.
- `config.py`: app version, token-name patterns, and compiled regex constants.
- `models.py`: `Sampler` and `Candidate` dataclasses.
- `xml_utils.py`: encoding detection, invalid XML cleanup, tag helpers, parse diagnostics, and indentation.
- `parser.py`: robust JMX parsing with sanitizer and optional `lxml` recovery.
- `jmeter_tree.py`: JMeter XML traversal helpers for samplers, headers, arguments, and extractors.
- `detection.py`: token classification, confidence scoring, variable naming, extraction regex generation, and candidate detection.
- `modifier.py`: Regex Extractor creation, hardcoded-value replacement, and final JMX writing.
- `table.py`: converts detected candidates into a Pandas table for Streamlit.
- `ui.py`: Streamlit user interface.
- `self_test.py`: parser/sanitizer smoke test.
- `tests/test_sanitizer.py`: pytest test for invalid XML numeric character references.

