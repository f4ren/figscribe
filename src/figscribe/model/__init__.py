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
    ErrorBand,
    ErrorbarPlot,
    ExpressionFit,
    FitCurve,
    FitModel,
    FitResult,
    Histogram,
    ImagePlot,
    LinePlot,
    PredefinedFit,
    ReferenceLine,
    ResidualPlot,
    ScatterPlot,
    ShadedSpan,
)
from figscribe.model.axes import Axes, AxisSpec, Inset, Legend
from figscribe.model.base import Identified, StrictModel, new_id
from figscribe.model.data import (
    ArrayRef,
    ColumnRef,
    CsvSource,
    DataSource,
    Hdf5Source,
    NumpySource,
)
from figscribe.model.figure import Figure, GridLayout, PanelLabels
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
    "ErrorBand",
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
    "Inset",
    "Legend",
    "LinePlot",
    "NumpySource",
    "PanelLabels",
    "PredefinedFit",
    "Project",
    "ReferenceIssue",
    "ReferenceLine",
    "ResidualPlot",
    "SchemaVersionError",
    "ScatterPlot",
    "ShadedSpan",
    "StrictModel",
    "dumps",
    "loads",
    "new_id",
    "validate_references",
]
