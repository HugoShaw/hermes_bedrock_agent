from enum import Enum

RELATIONSHIP_TYPES = {
    "HAS_OBJECT", "HAS_PROCESS", "HAS_STEP", "NEXT_STEP", "OPERATES_ON",
    "STORED_IN", "REPRESENTED_BY", "HAS_COLUMN", "HAS_STATUS_FIELD",
    "HAS_ENUM_VALUE", "HAS_METHOD", "IMPLEMENTED_BY", "CALLS_METHOD",
    "EXECUTES_SQL", "READS_TABLE", "WRITES_TABLE", "APPLIES_TO",
    "USES_FIELD", "REQUIRES", "REQUIRES_CHANGE_TO", "TESTS", "TESTS_API",
    "VERIFIES_RULE", "DEPENDS_ON_MODULE", "SHARES_TABLE_WITH",
    "CALLS_MODULE", "WRITES_BACK_TO", "POSSIBLY_RELATED",
}

LINK_METHODS = {
    "hard_id", "api_path", "table_name", "column_name", "class_name",
    "method_name", "method_call", "sql_usage", "foreign_key",
    "enum_reference", "test_reference", "table_comment", "column_comment",
    "code_comment", "document_reference", "name_similarity",
    "co_occurrence", "semantic_similarity", "manual_inference",
}

NODE_PREFIXES = {
    "module", "object", "process", "step", "controller", "service",
    "class", "method", "api", "sql", "table", "column", "enum",
    "rule", "req", "concept", "test", "batch",
}

LAYERS = {"business", "process", "system", "data", "knowledge", "test"}

CATEGORIES = {
    "module", "object", "process", "step", "code", "data",
    "rule", "concept", "requirement", "test",
}

SOURCE_TYPES = {
    "user_manual", "requirement_doc", "design_doc", "api_doc", "ddl",
    "source_code", "sql_mapper", "enum_or_constant", "test_case", "unknown",
}

REVIEW_STATUSES = {"verified", "pending", "rejected"}
VIEW_SCOPES = {"core", "detail", "candidate"}

CONFIDENCE_HIGH = 0.85
CONFIDENCE_MED = 0.70
CONFIDENCE_LOW = 0.50

# Confidence bands by link method
CONFIDENCE_BY_METHOD = {
    "hard_id": 0.95,
    "api_path": 0.93,
    "foreign_key": 0.92,
    "method_call": 0.90,
    "sql_usage": 0.88,
    "table_name": 0.87,
    "column_name": 0.86,
    "document_reference": 0.85,
    "table_comment": 0.78,
    "column_comment": 0.75,
    "code_comment": 0.73,
    "class_name": 0.72,
    "method_name": 0.71,
    "enum_reference": 0.70,
    "test_reference": 0.70,
    "name_similarity": 0.65,
    "co_occurrence": 0.60,
    "semantic_similarity": 0.58,
    "manual_inference": 0.55,
}

STATUS_FIELD_PATTERNS = [
    "STATUS", "STATE", "KBN", "FLG", "FLAG",
    "区分", "ステータス", "状態", "状況",
]

# Murata-specific business modules
MURATA_BUSINESS_MODULES = {
    "payment": {"ja": "付款申請", "en": "Payment Request", "prefix": "payment"},
    "journal": {"ja": "仕訳基礎/対帳単", "en": "Journal/Reconciliation", "prefix": "journal"},
    "receiving": {"ja": "入金管理", "en": "Receiving Management", "prefix": "receiving"},
    "system_mgmt": {"ja": "システム管理", "en": "System Management", "prefix": "system_mgmt"},
    "user_mgmt": {"ja": "ユーザ管理", "en": "User Management", "prefix": "user_mgmt"},
}

JAVA_PACKAGE_TO_MODULE = {
    "payment": "payment",
    "receigIng": "receiving",
    "receiving": "receiving",
    "system": "system_mgmt",
    "login": "user_mgmt",
    "common": "system_mgmt",
}

DISPLAY_GRAPH_MIN_NODES = 40
DISPLAY_GRAPH_MAX_NODES = 70
DISPLAY_GRAPH_MIN_EDGES = 60
DISPLAY_GRAPH_MAX_EDGES = 100
DISPLAY_CONFIDENCE_MIN = 0.8
DISPLAY_REVIEW_STATUS = "verified"
