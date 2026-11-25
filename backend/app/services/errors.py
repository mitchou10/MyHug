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


class FingerprintMismatch(ServiceError):
    """The content of a file is not the one its sender announced."""

    message = "A file is not the one that was announced"


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


class NoParquetCopy(ServiceError):
    """The file has no copy in Parquet (yet): it is too small or too large, not a table, or still being converted."""

    message = "No copy of this file in Parquet is ready"


class SplitNotFound(ServiceError):
    message = "This split does not exist"


# ---- notifications
class NotificationNotFound(ServiceError):
    """Also used for somebody else's notification: it must look like it does not exist."""

    message = "This notification does not exist"


class InvalidUrl(ServiceError):
    message = "The link must be a path of the app (starting with a single /) or an http(s) address"


class NotBeingProcessed(ServiceError):
    """The worker reports on a version that it does not hold (it was taken over, or it is not being read)."""

    message = "This version is not being read"


class DerivativeNotFound(ServiceError):
    message = "This copy does not exist"


# ---- models
class ModelNotFound(ServiceError):
    """Also used for a private model the user may not see: it must look like it does not exist."""

    message = "This model does not exist"


class ModelNameTaken(ServiceError):
    message = "You already have a model with this name"


class InvalidCodeUrl(ServiceError):
    message = "The code must be at an https address of an allowed host (GitHub, GitLab)"


class InvalidMember(ServiceError):
    message = "The creator and the admins already have every right: they are not members"


class MemberNotFound(ServiceError):
    message = "This person is not a member"


class ModelVersionNotFound(ServiceError):
    message = "This version does not exist"


class ModelFileNotFound(ServiceError):
    message = "This file does not exist"


class EmptyVersion(ServiceError):
    message = "A version needs files, a link to the code, or both"


class InvalidCodeReference(ServiceError):
    message = "This reference to the code is not accepted"


class InvalidSha(ServiceError):
    message = "A commit is 40 or 64 hexadecimal characters, in lowercase"


class VersionFailed(ServiceError):
    message = "The files of this version did not pass the checks"


# ---- trying a model: the relay to the server that serves it
class NoEndpoint(ServiceError):
    message = "This model has no server to try it on"


class InvalidEndpoint(ServiceError):
    message = "This endpoint is not accepted"


class EndpointUnavailable(ServiceError):
    message = "The server of this model does not answer"


class EndpointTimeout(ServiceError):
    message = "The server of this model took too long to answer"


class BadEndpointAnswer(ServiceError):
    message = "The server of this model gave an answer that cannot be used"


class InputRejected(ServiceError):
    message = "The model refused this input"


class InputTooLarge(ServiceError):
    message = "This input is too large"


class TooManyRequests(ServiceError):
    message = "Too many tries: wait a little"


# ---- the registry of the models (MLflow)
class RegistryUnavailable(ServiceError):
    """MLflow does not answer, or does not take what the backend sends it (a key it refuses, an error of its own)."""

    message = "The models service is not available"


class RegistryNotFound(ServiceError):
    message = "This model or version does not exist in the registry"


class RegistryConflict(ServiceError):
    message = "This name is already used in the registry"


class RegistryRejected(ServiceError):
    """MLflow refuses a value: a name it does not accept."""

    message = "The registry refuses this value"


# ---- access tokens
class TokenNotFound(ServiceError):
    """Also used for somebody else's token: it must look like it does not exist."""

    message = "This token does not exist"


class TooManyTokens(ServiceError):
    message = "Too many access tokens: revoke one first"


class InvalidToken(ServiceError):
    """Unknown, revoked or expired: the caller is told nothing more."""

    message = "Not authenticated"


# ---- evaluations
class EvaluationNotFound(ServiceError):
    message = "This evaluation does not exist"


class InvalidEvaluation(ServiceError):
    """A result that cannot be taken: the reason is in the message."""

    message = "This evaluation is not valid"


class TooManyEvaluations(ServiceError):
    message = "Too many evaluations of this model are waiting or running: wait for one to finish, or delete one"
