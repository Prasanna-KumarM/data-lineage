"""Extract FPL-to-PAR lineage from the database baseline scripts into a lineage.db.

Input: a checkout of the baseline repository (metadata/PAR), using
par_owner/ins/DB_codebase/{Tables_baseline,Tables_delta,Views,DML_baseline,DML_delta}.
Output: a SQLite database with the same schema the read-only lineage API serves.
"""
