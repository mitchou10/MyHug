class FileProblem(Exception):
    """A file that cannot be read, and it is the file's fault: reading it again would give the same."""


class UnreadableFile(FileProblem):
    """A csv, tsv, jsonl or parquet file that cannot be read as such."""


class FileMissing(FileProblem):
    """The storage does not have the file."""
