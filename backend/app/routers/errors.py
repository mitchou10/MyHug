"""Turns the errors of the services into HTTP answers. The services know nothing about status codes."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.services import errors

STATUS_CODES: dict[type[errors.ServiceError], int] = {
    errors.FeedbackNotFound: status.HTTP_404_NOT_FOUND,
    errors.AttachmentNotFound: status.HTTP_404_NOT_FOUND,
    errors.ReferenceNotFound: status.HTTP_404_NOT_FOUND,
    errors.AvatarNotFound: status.HTTP_404_NOT_FOUND,
    errors.NotificationNotFound: status.HTTP_404_NOT_FOUND,
    errors.DatasetNotFound: status.HTTP_404_NOT_FOUND,
    errors.DatasetNameTaken: status.HTTP_409_CONFLICT,
    errors.VersionNotFound: status.HTTP_404_NOT_FOUND,
    errors.DatasetFileNotFound: status.HTTP_404_NOT_FOUND,
    errors.VersionNotReady: status.HTTP_409_CONFLICT,
    errors.NotBeingProcessed: status.HTTP_409_CONFLICT,
    errors.DerivativeNotFound: status.HTTP_404_NOT_FOUND,
    errors.ModelNotFound: status.HTTP_404_NOT_FOUND,
    errors.ModelNameTaken: status.HTTP_409_CONFLICT,
    errors.InvalidCodeUrl: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.InvalidMember: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.MemberNotFound: status.HTTP_404_NOT_FOUND,
    errors.ModelVersionNotFound: status.HTTP_404_NOT_FOUND,
    errors.ModelFileNotFound: status.HTTP_404_NOT_FOUND,
    errors.EmptyVersion: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.InvalidCodeReference: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.InvalidSha: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.VersionFailed: status.HTTP_409_CONFLICT,
    errors.NoEndpoint: status.HTTP_409_CONFLICT,
    errors.InvalidEndpoint: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.EndpointUnavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
    errors.EndpointTimeout: status.HTTP_504_GATEWAY_TIMEOUT,
    errors.BadEndpointAnswer: status.HTTP_502_BAD_GATEWAY,
    errors.InputRejected: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.InputTooLarge: status.HTTP_413_CONTENT_TOO_LARGE,
    errors.TooManyRequests: status.HTTP_429_TOO_MANY_REQUESTS,
    errors.RegistryUnavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
    errors.RegistryNotFound: status.HTTP_404_NOT_FOUND,
    errors.RegistryConflict: status.HTTP_409_CONFLICT,
    errors.RegistryRejected: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.UploadNotFound: status.HTTP_404_NOT_FOUND,
    errors.UploadClosed: status.HTTP_409_CONFLICT,
    errors.UploadIncomplete: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.EmptyFile: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.SplitNotFound: status.HTTP_404_NOT_FOUND,
    errors.FileTooLarge: status.HTTP_413_CONTENT_TOO_LARGE,
    errors.InvalidFilePath: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.TooManyFiles: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.NothingToCommit: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.UnreadableDataFile: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.NotAllowed: status.HTTP_403_FORBIDDEN,
    errors.DuplicateName: status.HTTP_409_CONFLICT,
    errors.ProtectedStatus: status.HTTP_409_CONFLICT,
    errors.ImageTooLarge: status.HTTP_413_CONTENT_TOO_LARGE,
    errors.UnsupportedImage: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    errors.InvalidReference: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.ReferenceArchived: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.TooManyAttachments: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.InvalidCursor: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.InvalidPage: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.EmptyMessage: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.InvalidUrl: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def status_code_of(error: errors.ServiceError) -> int:
    """The code of the error; one nobody mapped is a bad request."""
    return next((code for cls, code in STATUS_CODES.items() if isinstance(error, cls)), status.HTTP_400_BAD_REQUEST)


def register_error_handlers(app: FastAPI) -> None:
    async def handle(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, errors.ServiceError)
        return JSONResponse({"detail": str(error)}, status_code=status_code_of(error))

    app.add_exception_handler(errors.ServiceError, handle)
