"""The plot model: the single source of truth.

The renderer, the code generator and the project file all read these classes,
and the GUI mutates them only through commands. The classes stay dumb on
purpose: validators check values, they never compute anything or call into
other subsystems, so that the storage library behind them could be replaced.
"""

from figscribe.model.artists import (
    Annotation,
    Artist,
    ArtistBase,
    Colorbar,
    ColorMesh,
    ErrorbarPlot,
    ExpressionFit,
    FitCurve,
    FitModel,
    FitResult,
    Histogram,
    ImagePlot,
    LinePlot,
    PredefinedFit,
    ResidualPlot,
    ScatterPlot,
)
from figscribe.model.axes import Axes, AxisSpec, Legend
from figscribe.model.base import Identified, StrictModel, new_id
from figscribe.model.data import (
    ArrayRef,
    ColumnRef,
    CsvSource,
    DataSource,
    Hdf5Source,
    NumpySource,
)
from figscribe.model.figure import Figure, GridLayout
from figscribe.model.project import (
    SCHEMA_VERSION,
    Project,
    SchemaVersionError,
    dumps,
    loads,
)
from figscribe.model.validate import ReferenceIssue, validate_references

__all__ = [
    "SCHEMA_VERSION",
    "Annotation",
    "ArrayRef",
    "Artist",
    "ArtistBase",
    "Axes",
    "AxisSpec",
    "ColorMesh",
    "Colorbar",
    "ColumnRef",
    "CsvSource",
    "DataSource",
    "ErrorbarPlot",
    "ExpressionFit",
    "Figure",
    "FitCurve",
    "FitModel",
    "FitResult",
    "GridLayout",
    "Hdf5Source",
    "Histogram",
    "Identified",
    "ImagePlot",
    "Legend",
    "LinePlot",
    "NumpySource",
    "PredefinedFit",
    "Project",
    "ReferenceIssue",
    "ResidualPlot",
    "SchemaVersionError",
    "ScatterPlot",
    "StrictModel",
    "dumps",
    "loads",
    "new_id",
    "validate_references",
]
