import pytest

from app.registry import MlflowLinks
from app.registry.names import registered_name

BASE = "http://localhost:5000"


def test_each_page_has_its_address() -> None:
    links = MlflowLinks(BASE)
    assert links.model("ada~m") == "http://localhost:5000/#/models/ada~m"
    assert links.version("ada~m", "3") == "http://localhost:5000/#/models/ada~m/versions/3"
    assert links.run("3", "abc123") == "http://localhost:5000/#/experiments/3/runs/abc123"


@pytest.mark.parametrize("public", ["", "   "])
def test_without_an_address_there_is_no_link(public: str) -> None:
    links = MlflowLinks(public)
    assert (links.model("a"), links.version("a", "1"), links.run("1", "r")) == (None, None, None)


def test_a_slash_at_the_end_of_the_address_does_not_double() -> None:
    assert MlflowLinks("https://ml.example.com/").model("a") == "https://ml.example.com/#/models/a"
    assert MlflowLinks("https://ml.example.com///").run("1", "r") == "https://ml.example.com/#/experiments/1/runs/r"


@pytest.mark.parametrize(
    ("name", "encoded"),
    [
        ("ada/m", "ada%2Fm"),
        ("a b", "a%20b"),
        ("a#b", "a%23b"),
        ("a?b=c", "a%3Fb%3Dc"),
        ("a%b", "a%25b"),
        ("../x", "..%2Fx"),
        ("é", "%C3%A9"),
    ],
)
def test_a_name_cannot_change_the_path_of_the_address(name: str, encoded: str) -> None:
    links = MlflowLinks(BASE)
    assert links.model(name) == f"{BASE}/#/models/{encoded}"
    assert links.version(name, "1") == f"{BASE}/#/models/{encoded}/versions/1"
    assert links.run(name, name) == f"{BASE}/#/experiments/{encoded}/runs/{encoded}"


def test_the_name_of_a_platform_model_is_left_readable() -> None:
    assert MlflowLinks(BASE).model(registered_name("ada", "sentiment-fr")) == f"{BASE}/#/models/ada~sentiment-fr"


def test_the_address_the_backend_calls_mlflow_by_never_appears(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings
    from app.registry import get_links

    monkeypatch.setattr(settings, "MLFLOW_TRACKING_URI", "http://mlflow:5000")
    monkeypatch.setattr(settings, "MLFLOW_PUBLIC_URL", "")
    links = get_links()
    assert links.model("a") is None  # an empty public address is not replaced by the internal one
    monkeypatch.setattr(settings, "MLFLOW_PUBLIC_URL", "https://ml.example.com")
    for link in (get_links().model("a"), get_links().version("a", "1"), get_links().run("1", "r")):
        assert link is not None and "mlflow:5000" not in link and link.startswith("https://ml.example.com/")
