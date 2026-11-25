class FileProblem(Exception):
    """A file that cannot be read, and it is the file's fault: reading it again would give the same."""


class UnreadableFile(FileProblem):
    """A csv, tsv, jsonl or parquet file that cannot be read as such."""


class FileMissing(FileProblem):
    """The storage does not have the file."""


class CodeProblem(Exception):
    """The host answered something that cannot be used, or the address is not one the worker may call. Asking again
    would give the same."""


class HostUnavailable(Exception):
    """The host is down, or limits the calls: the lookup is made again later."""


class EvaluationProblem(Exception):
    """The predictions do not match the split, or are not what the task takes: it is the data's fault, and reading them
    again would give the same."""
