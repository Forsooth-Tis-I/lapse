from uuid import uuid4

import pytest
from redis.exceptions import ResponseError

from lapse.graph.db import graph


@pytest.fixture
def isolated_graph():
    g = graph(f"lapse:test:wp0:{uuid4().hex}")
    try:
        yield g
    finally:
        try:
            g.delete()
        except ResponseError as exc:
            if "Invalid graph operation on empty key" not in str(exc):
                raise
