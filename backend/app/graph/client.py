from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import AuthError, ConfigurationError, Neo4jError, ServiceUnavailable


class GraphUnavailableError(RuntimeError):
    """Raised when Neo4j cannot be reached or a graph operation fails."""


GraphHealthStatus = Literal[
    "connected",
    "unreachable",
    "authentication_failure",
    "invalid_configuration",
]


@dataclass(frozen=True)
class GraphHealth:
    status: GraphHealthStatus
    database: str
    detail: str | None = None


class Neo4jClient:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        if not uri.strip() or not user.strip() or not password or not database.strip():
            raise ValueError("NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, and NEO4J_DATABASE are required")
        self.database = database
        try:
            self.driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        except (ConfigurationError, ValueError) as exc:
            raise ValueError("Invalid Neo4j connection configuration") from exc

    def verify_connectivity(self) -> None:
        try:
            self.driver.verify_connectivity()
            self.driver.execute_query(
                "RETURN 1 AS ok",
                database_=self.database,
            )
        except (AuthError, ServiceUnavailable, Neo4jError) as exc:
            raise GraphUnavailableError("Neo4j connectivity check failed") from exc
        except ConfigurationError as exc:
            raise ValueError("Invalid Neo4j connection configuration") from exc
        except OSError as exc:
            raise GraphUnavailableError("Neo4j connectivity check failed") from exc

    def run(self, query: str, parameters: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        try:
            records, _, _ = self.driver.execute_query(
                query,
                parameters_=dict(parameters or {}),
                database_=self.database,
            )
            return [record.data() for record in records]
        except (AuthError, ServiceUnavailable, OSError) as exc:
            raise GraphUnavailableError("Neo4j query failed") from exc
        except ConfigurationError as exc:
            raise ValueError("Invalid Neo4j connection configuration") from exc

    def health(self) -> GraphHealth:
        try:
            self.verify_connectivity()
        except ValueError as exc:
            return GraphHealth("invalid_configuration", self.database, str(exc))
        except GraphUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, AuthError):
                return GraphHealth("authentication_failure", self.database, "Neo4j authentication failed")
            return GraphHealth("unreachable", self.database, "Neo4j Bolt endpoint is unreachable")
        return GraphHealth("connected", self.database)

    def close(self) -> None:
        self.driver.close()
