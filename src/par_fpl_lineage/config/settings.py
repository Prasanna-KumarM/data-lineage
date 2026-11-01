"""FPL extraction configuration."""

PROJECT = "FPL"
DEFAULT_BASELINE = "metadata/PAR"
DEFAULT_OUTPUT = "outputs/FPL/lineage.db"
CODEBASE_RELATIVE = "par_owner/ins/DB_codebase"

# Filled by the loader procedure, not by the view.
LOADER_COLUMNS = {
    "PAR_ID": "PAR_SEQ.NEXTVAL",
    "PAR_PROCESSING_UNIT": "p_processing_unit (loader parameter)",
    "PAR_PROCESS_DATE": "l_process_date (loader)",
}

PARSER_VERSION = "2.0.0"
SCHEMA_VERSION = "1.0.0"
IDENTITY_VERSION = "IDV1"
