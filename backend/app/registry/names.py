"""The name of a model in MLflow. MLflow does not accept `/` or `:` in the name of a registered model, so `owner/name`
cannot be used. `~` is accepted by MLflow and can never be in an owner or in a name (those are made of lowercase
letters, digits, dots, dashes and underscores): `ada~sentiment-fr` can always be taken apart again."""

SEPARATOR = "~"


def registered_name(owner: str, name: str) -> str:
    return f"{owner}{SEPARATOR}{name}"


def split_registered_name(registered: str) -> tuple[str, str]:
    """The owner and the name. Raises ValueError for a name that was not made by `registered_name`."""
    owner, separator, name = registered.partition(SEPARATOR)
    if not separator or not owner or not name or SEPARATOR in name:
        raise ValueError(f"{registered!r} is not the name of a model of the platform")
    return owner, name
