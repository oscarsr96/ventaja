"""Error hierarchy for ventaja."""


class VentajaError(Exception):
    """Base class for all ventaja errors."""


class DataNotFoundError(VentajaError):
    """A required raw or built data file is missing."""


class CorruptFileError(VentajaError):
    """A data file exists but its content is invalid."""


class NoTrackingError(VentajaError):
    """Tracking data is not available for the requested game or frame."""


class AmbiguousQueryError(VentajaError):
    """A name or id query matched no entity or more than one; the message lists candidates."""
