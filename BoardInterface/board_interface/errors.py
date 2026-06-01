class SCPICommandFailedError(Exception):
    def __init__(self, command: str) -> None:
        super().__init__(f"Command {command} has returned -1")
        self.command = command


class SCPIError:
    _MESSAGES = {
        0: "No Error",
        -101: "Invalid character",
        -102: "Syntax error",
        -103: "Invalid Separator",
        -104: "Data type error",
        -108: "Parameter not allowed",
        -109: "Missing parameter",
        -113: "Undefined header",
        -120: "Numeric data error",
        -121: "Invalid character in number",
        -138: "Suffix not allowed",
        -222: "Data out of range",
    }

    def __init__(self, error_code: int) -> None:
        self.error_code = error_code
        self.message = self._MESSAGES.get(error_code, "Other error")

    def __str__(self) -> str:
        return f"{self.error_code}: {self.message}"
