"""Typed service errors. Services raise these; main.py maps them to HTTP. Services never import FastAPI."""


class DomainError(Exception):
    status = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    status = 404


class Conflict(DomainError):
    status = 409


class Forbidden(DomainError):
    status = 403


class Unauthorized(DomainError):
    status = 401


class Invalid(DomainError):
    status = 422


class Unavailable(DomainError):
    status = 503
