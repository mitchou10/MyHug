"""The errors services raise. They know nothing about HTTP: `app/routers/errors.py` turns them into answers."""


class ServiceError(Exception):
    """Base of every error a service raises on purpose."""

    message = "Something went wrong"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)


# ---- images (profile photo, screenshots)
class ImageTooLarge(ServiceError):
    message = "The image is too large"


class UnsupportedImage(ServiceError):
    message = "The image must be a PNG, JPEG or WebP"


# ---- profile
class ProfileError(ServiceError):
    pass


class AvatarNotFound(ProfileError):
    message = "No profile photo"


# ---- feedback
class FeedbackNotFound(ServiceError):
    """Also used when the feedback exists but the user may not see it: it must look like it does not exist."""

    message = "This feedback does not exist"


class AttachmentNotFound(ServiceError):
    message = "This screenshot does not exist"


class ReferenceNotFound(ServiceError):
    message = "This type or status does not exist"


class InvalidReference(ServiceError):
    """An id sent in a request that matches no type or status (as opposed to one named in the address)."""

    message = "This type or status does not exist"


class ReferenceArchived(ServiceError):
    message = "This type or status is archived and can no longer be chosen"


class DuplicateName(ServiceError):
    message = "A value with this name already exists"


class ProtectedStatus(ServiceError):
    message = "This status is used by the app itself and cannot be archived"


class NotAllowed(ServiceError):
    message = "You are not allowed to do this"


class TooManyAttachments(ServiceError):
    message = "Too many screenshots"


class InvalidCursor(ServiceError):
    message = "This page cursor is not valid"


class InvalidPage(ServiceError):
    """The page a feedback was sent from is not a path of the app."""

    message = "The page must be a path of the app, starting with a single /"


class EmptyMessage(ServiceError):
    message = "The message is empty"


# ---- datasets
class DatasetNotFound(ServiceError):
    """Also used for a private dataset the user may not see: it must look like it does not exist."""

    message = "This dataset does not exist"


class DatasetNameTaken(ServiceError):
    message = "You already have a dataset with this name"


class InvalidFilePath(ServiceError):
    message = "A file path must be relative, without `..`, and at most 512 characters"


class FileTooLarge(ServiceError):
    message = "This file is too large"


class TooManyFiles(ServiceError):
    message = "Too many files in one version"


class NothingToCommit(ServiceError):
    message = "Send at least one file to add or to remove"


class UnreadableDataFile(ServiceError):
    """A csv, tsv, jsonl or parquet file that cannot be read as such."""

    message = "This file cannot be read"


class VersionNotFound(ServiceError):
    message = "This version does not exist"


class VersionNotReady(ServiceError):
    """The files of the version have not been read yet (or could not be): there is nothing to show of their rows."""

    message = "This version is still being processed"


class UploadNotFound(ServiceError):
    """Also used for somebody else's upload: it must look like it does not exist."""

    message = "This upload does not exist"


class UploadClosed(ServiceError):
    """An upload that was completed, given up, or that took too long: nothing more can be sent to it."""

    message = "This upload is closed"


class UploadIncomplete(ServiceError):
    message = "The upload is not complete"


class EmptyFile(ServiceError):
    message = "A file cannot be empty"


class DatasetFileNotFound(ServiceError):
    message = "This file does not exist"


class SplitNotFound(ServiceError):
    message = "This split does not exist"


# ---- notifications
class NotificationNotFound(ServiceError):
    """Also used for somebody else's notification: it must look like it does not exist."""

    message = "This notification does not exist"


class InvalidUrl(ServiceError):
    message = "The link must be a path of the app (starting with a single /) or an http(s) address"
