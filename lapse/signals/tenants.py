from falkordb import FalkorDB

from lapse.config import settings


def tenant_uids() -> list[str]:
    config = settings()
    client = FalkorDB(host=config.falkordb_host, port=config.falkordb_port)
    names = client.list_graphs()
    return sorted(name.removeprefix("lapse:u:") for name in names if name.startswith("lapse:u:"))
