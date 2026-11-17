"""Database triggers enforce the status allow-list for every identity (Slice 3 review, High finding #6; P9, P10).

Requirements: NFR-01, NFR-02, NFR-06; AC-RM-04.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests._repo import load_yaml

POLICY = load_yaml("policies/state-transitions.yaml")
FROM_RECEIVED = set(POLICY["transitions"]["RECEIVED"])
ALL_STATES = sorted({POLICY["initial_state"], *POLICY["terminal_states"], *POLICY["transitions"],
                     *(t for ts in POLICY["transitions"].values() for t in ts)})
MYSQL_SIGNAL = 1644  # ER_SIGNAL_EXCEPTION from SIGNAL SQLSTATE '45000'


def _insert(engine: Engine, status: str | None = None) -> int:
    columns, values = "release_id, correlation_id", ":rid, :cid"
    params = {"rid": "REL-20261117-0001", "cid": str(uuid.uuid4())}
    if status is not None:
        columns, values = columns + ", status", values + ", :status"
        params["status"] = status
    with engine.begin() as connection:
        connection.execute(text(f"INSERT INTO release_request ({columns}) VALUES ({values})"), params)  # noqa: S608
        row_id = connection.execute(text("SELECT id FROM release_request WHERE release_id = :rid"), params)
        return int(row_id.scalar_one())


def _status(engine: Engine, fk: int) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT status FROM release_request WHERE id = :i"), {"i": fk}).scalar_one())


def _set_status(engine: Engine, fk: int, status: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE release_request SET status = :s WHERE id = :i"), {"s": status, "i": fk})


def _signal_code(error: DBAPIError) -> int:
    return int(error.orig.args[0])  # type: ignore[union-attr]


@pytest.mark.parametrize("status", [s for s in ALL_STATES if s != "RECEIVED"])
def test_runtime_user_cannot_insert_release_in_non_initial_state(
    db: Engine, runtime_engine: Engine, status: str
) -> None:
    with pytest.raises(DBAPIError) as error:
        _insert(runtime_engine, status)
    assert _signal_code(error.value) == MYSQL_SIGNAL


def test_migration_identity_is_also_guarded(db: Engine) -> None:
    with pytest.raises(DBAPIError) as error:
        _insert(db, "COMPLETED")
    assert _signal_code(error.value) == MYSQL_SIGNAL


def test_insert_defaults_and_explicit_initial_status_are_allowed(db: Engine, runtime_engine: Engine) -> None:
    assert _status(db, _insert(runtime_engine)) == "RECEIVED"


@pytest.mark.parametrize("target", [s for s in ALL_STATES if s not in FROM_RECEIVED and s != "RECEIVED"])
def test_runtime_user_cannot_update_status_off_allow_list(db: Engine, runtime_engine: Engine, target: str) -> None:
    fk = _insert(runtime_engine)
    with pytest.raises(DBAPIError) as error:
        _set_status(runtime_engine, fk, target)
    assert _signal_code(error.value) == MYSQL_SIGNAL
    assert _status(db, fk) == "RECEIVED"


def test_terminal_status_cannot_be_reopened(db: Engine, runtime_engine: Engine) -> None:
    fk = _insert(runtime_engine)
    _set_status(runtime_engine, fk, "CANCELLED")
    with pytest.raises(DBAPIError):
        _set_status(runtime_engine, fk, "RECEIVED")
    assert _status(db, fk) == "CANCELLED"


@pytest.mark.parametrize("target", sorted(FROM_RECEIVED))
def test_allowed_edges_and_non_status_updates_pass(db: Engine, runtime_engine: Engine, target: str) -> None:
    fk = _insert(runtime_engine)
    _set_status(runtime_engine, fk, target)
    _set_status(runtime_engine, fk, target)  # unchanged status is not a transition
    with runtime_engine.begin() as connection:
        connection.execute(text("UPDATE release_request SET release_name = 'renamed' WHERE id = :i"), {"i": fk})
    assert _status(db, fk) == target
