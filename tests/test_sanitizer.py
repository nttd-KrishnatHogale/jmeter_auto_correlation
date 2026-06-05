from __future__ import annotations

from jmeter_auto_correlation.parser import parse_jmx


def test_parse_jmx_removes_invalid_numeric_xml_references() -> None:
    sample = b'''<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan><hashTree>
  <HTTPSamplerProxy testname="binary-body"><elementProp name="HTTPsampler.Arguments"><collectionProp name="Arguments.arguments"><elementProp name="" elementType="HTTPArgument"><stringProp name="Argument.value">&#x1f;abc&#x8;&#x0;&#31;&#55296;def</stringProp></elementProp></collectionProp></elementProp></HTTPSamplerProxy><hashTree/>
</hashTree></jmeterTestPlan>'''

    tree, fixes = parse_jmx(sample)
    value = tree.find(".//stringProp[@name='Argument.value']")

    assert fixes >= 5
    assert value is not None
    assert value.text == "abcdef"
