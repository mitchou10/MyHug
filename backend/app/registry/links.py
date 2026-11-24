from urllib.parse import quote


class MlflowLinks:
    """The addresses of the pages of MLflow, to see the detail of a model there (its runs, its metrics, its artifacts).

    It builds addresses and calls nothing. They start from `public_url` (where a person opens MLflow), never from the
    address the backend calls it by. Empty `public_url`: there is no link (every method gives None)."""

    def __init__(self, public_url: str) -> None:
        self._base = public_url.strip().rstrip("/")

    @staticmethod
    def _part(value: str) -> str:
        """One piece of an address: nothing is left as it is, so a `/`, a `#` or a space cannot change the path."""
        return quote(value, safe="")

    def model(self, name: str) -> str | None:
        return f"{self._base}/#/models/{self._part(name)}" if self._base else None

    def version(self, name: str, version: str) -> str | None:
        return f"{self._base}/#/models/{self._part(name)}/versions/{self._part(version)}" if self._base else None

    def run(self, experiment_id: str, run_id: str) -> str | None:
        if not self._base:
            return None
        return f"{self._base}/#/experiments/{self._part(experiment_id)}/runs/{self._part(run_id)}"
