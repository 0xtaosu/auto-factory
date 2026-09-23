from __future__ import annotations

from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

from .common import ONTOLOGY_PATH, dumps

INV = Namespace("https://example.org/inventory/")
METRIC = Namespace("https://example.org/metric/")
ASSESSMENT = Namespace("https://example.org/assessment/")
POLICY = Namespace("https://example.org/policy/")
EX = Namespace("https://example.org/resource/")
PROV = Namespace("http://www.w3.org/ns/prov#")


def resource(identifier: str) -> URIRef:
    # Keep readable path structure while safely encoding codes/names from ERP.
    return URIRef(str(EX) + quote(identifier, safe="/"))


def build_graph(result: dict) -> Graph:
    graph = Graph().parse(ONTOLOGY_PATH, format="turtle")
    for prefix, ns in (("inv", INV), ("metric", METRIC), ("assessment", ASSESSMENT), ("policy", POLICY), ("ex", EX), ("prov", PROV)):
        graph.bind(prefix, ns)

    def lit(subject, predicate, value, datatype=None):
        if value is not None:
            graph.add((subject, predicate, Literal(value, datatype=datatype)))

    def link(subject, predicate, identifier):
        if identifier is not None:
            graph.add((subject, predicate, resource(identifier)))

    run = resource("run/" + result["run"]["run_id"])
    graph.add((run, RDF.type, INV.AnalysisRun))
    lit(run, INV.runManifest, dumps(result["run"], sort_keys=True))
    for material in result["materials"]:
        node = resource(material["material_id"])
        graph.add((node, RDF.type, INV.Material))
        for key, prop in (("material_code", INV.materialCode), ("material_name", INV.materialName), ("material_specification", INV.materialSpecification), ("material_category", INV.materialCategory), ("unit", INV.unit)):
            lit(node, prop, material[key])
        link(node, PROV.wasDerivedFrom, material["metadata_source_record_id"])
        lit(node, INV.metadataConflicts, dumps(material["metadata_conflicts"], sort_keys=True))
    for kind, cls in (("departments", INV.Department), ("suppliers", INV.Supplier)):
        key = "department_id" if kind == "departments" else "supplier_id"
        for entity in result[kind]:
            node = resource(entity[key])
            graph.add((node, RDF.type, cls))
            lit(node, RDFS.label, entity["name"])
    for record in result["source_records"]:
        node = resource(record["source_record_id"])
        graph.add((node, RDF.type, INV.SourceRecord))
        for key, prop in (("source_file_sha256", INV.sourceFileSha256), ("source_filename", INV.sourceFilename), ("sheet_name", INV.sheetName), ("status", INV.recordStatus)):
            lit(node, prop, record[key])
        lit(node, INV.excelRow, record["excel_row"], XSD.integer)
        for key, prop in (("raw_values", INV.rawValues), ("normalized_values", INV.normalizedValues), ("issues", INV.issues)):
            lit(node, prop, dumps(record[key], sort_keys=True))
        link(node, INV.duplicateOf, record.get("duplicate_of"))
    for event in result["movement_events"]:
        node = resource(event["movement_id"])
        graph.add((node, RDF.type, INV.InventoryMovementEvent))
        lit(node, INV.movementId, event["movement_id"])
        link(node, INV.hasMaterial, "material/" + event["material_code"])
        link(node, INV.hasDepartment, event["department_id"])
        link(node, INV.hasSupplier, event["supplier_id"])
        link(node, PROV.wasDerivedFrom, event["source_record_id"])
        lit(node, INV.transactionDate, event["transaction_date"], XSD.date)
        graph.add((node, INV.transactionType, INV.Inbound if event["transaction_type"] == "inbound" else INV.Outbound))
        for key, prop in (("quantity", INV.quantity), ("unit_price", INV.unitPrice), ("amount", INV.amount)):
            lit(node, prop, event[key], XSD.decimal)
        lit(node, INV.unit, event["unit"])
        lit(node, INV.remark, event["remark"])
    policy = result["policy"]
    policy_node = resource(policy["policy_snapshot_id"])
    graph.add((policy_node, RDF.type, POLICY.SlowMovingPolicy))
    graph.add((policy_node, POLICY.metric, METRIC[policy["metric"]]))
    for key, prop in (("policy_id", POLICY.policyId), ("policy_name", POLICY.policyName), ("operator", POLICY.operator), ("threshold_unit", POLICY.thresholdUnit), ("material_category", POLICY.materialCategory)):
        lit(policy_node, prop, policy[key])
    lit(policy_node, POLICY.thresholdValue, policy["threshold_value"], XSD.integer)
    lit(policy_node, POLICY.effectiveFrom, policy["effective_from"], XSD.date)
    lit(policy_node, POLICY.effectiveTo, policy["effective_to"], XSD.date)
    lit(policy_node, POLICY.policySnapshot, dumps(policy, sort_keys=True))
    for observation in result["metric_observations"]:
        node = resource(observation["observation_id"])
        graph.add((node, RDF.type, METRIC.MetricObservation))
        graph.add((node, METRIC.metricType, METRIC[observation["metric_type"]]))
        graph.add((node, PROV.wasGeneratedBy, run))
        link(node, METRIC.observedFor, "material/" + observation["material_code"])
        value = observation["numeric_value"]
        lit(node, METRIC.hasNumericValue, value, XSD.integer if isinstance(value, int) else XSD.decimal)
        for key, prop in (("observation_date", METRIC.observationDate), ("last_movement_date", METRIC.lastMovementDate), ("window_start", METRIC.windowStart), ("window_end", METRIC.windowEnd), ("data_window_start", METRIC.dataWindowStart), ("data_window_end", METRIC.dataWindowEnd)):
            lit(node, prop, observation[key], XSD.date)
        lit(node, METRIC.unit, observation["unit"])
        lit(node, METRIC.status, observation["status"])
        lit(node, METRIC.unavailableReason, observation["unavailable_reason"])
        if observation["quantity_by_unit"] is not None:
            lit(node, METRIC.quantityByUnit, dumps(observation["quantity_by_unit"], sort_keys=True))
        for event_id in observation["evidence_event_ids"]:
            link(node, PROV.wasDerivedFrom, event_id)
        for event_id in observation["last_movement_event_ids"]:
            link(node, METRIC.lastMovementEvent, event_id)
    for assessment in result["activity_assessments"]:
        node = resource(assessment["assessment_id"])
        material_node = resource("material/" + assessment["material_code"])
        graph.add((node, RDF.type, ASSESSMENT.MaterialActivityAssessment))
        graph.add((node, ASSESSMENT.assessesMaterial, material_node))
        graph.add((material_node, INV.hasActivityAssessment, node))
        graph.add((node, ASSESSMENT.evaluatedByPolicy, policy_node))
        graph.add((node, ASSESSMENT.hasClassification, ASSESSMENT[assessment["classification"]]))
        graph.add((node, PROV.wasGeneratedBy, run))
        lit(node, ASSESSMENT.inactiveCandidate, assessment["inactive_candidate"], XSD.boolean)
        lit(node, ASSESSMENT.evaluationStatus, assessment["evaluation_status"])
        lit(node, ASSESSMENT.leftCensoredPopulation, True, XSD.boolean)
        for key, prop in (("observation_date", METRIC.observationDate), ("data_window_start", METRIC.dataWindowStart), ("data_window_end", METRIC.dataWindowEnd)):
            lit(node, prop, assessment[key], XSD.date)
        for metric_id in assessment["metric_observation_ids"]:
            link(node, ASSESSMENT.usesObservation, metric_id)
    return graph


def export_rdf(result: dict, path) -> None:
    build_graph(result).serialize(destination=str(path), format="turtle")
