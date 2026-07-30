"""
Source connectors: pull raw documents from a source system into
``toolkit.metadata.DocumentRecord`` objects.

Every connector implements ``toolkit.connectors.base.SourceConnector`` so the
rest of the pipeline (validation, chunking, indexing) never needs to know
which system a document came from.
"""

from toolkit.connectors.base import SourceConnector
from toolkit.connectors.core_banking import CoreBankingAPIConnector
from toolkit.connectors.relational_db import RelationalDBConnector
from toolkit.connectors.unstructured_files import UnstructuredFileConnector

#: Registry used by the CLI to resolve --source flag values.
CONNECTOR_REGISTRY: dict[str, type[SourceConnector]] = {
    "core-banking": CoreBankingAPIConnector,
    "relational-db": RelationalDBConnector,
    "unstructured-files": UnstructuredFileConnector,
}

__all__ = [
    "SourceConnector",
    "CoreBankingAPIConnector",
    "RelationalDBConnector",
    "UnstructuredFileConnector",
    "CONNECTOR_REGISTRY",
]
