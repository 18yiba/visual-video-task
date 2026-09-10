class ConverterError(RuntimeError):
    """A contextual, user-facing conversion error."""

    def __init__(self, code: str, message: str, source_record_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.source_record_id = source_record_id

    def __str__(self) -> str:
        context = f" source_record_id={self.source_record_id}" if self.source_record_id else ""
        return f"{self.code}{context}: {super().__str__()}"

