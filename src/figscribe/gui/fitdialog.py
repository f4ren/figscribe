"""The fit dialog: pick a model, see the result at once, add it to the figure.

Every change of model, start value, held parameter or bound fits again right
away, on the data of the target plot, without touching the project; only
"Add fit" pushes the FitCurve (and its residual panel) as one undo step.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from figscribe.fit import (
    FitError,
    free_names,
    initial_guess,
    parameter_names,
    run_fit,
    source_of,
    within,
)
from figscribe.gui import theme
from figscribe.gui.names import artist_name, with_error
from figscribe.gui.numbers import number
from figscribe.gui.properties import GREEK
from figscribe.gui.widgets import label
from figscribe.model import ErrorbarPlot, ExpressionFit, FitCurve, PredefinedFit

MODELS = [
    ("gaussian", "Gaussian", "A peak with a constant background"),
    ("lorentzian", "Lorentzian", "A peak with a constant background"),
    ("linear", "Straight line", "a * x + b"),
    ("polynomial", "Polynomial", "Of the degree you choose"),
    ("exponential", "Exponential", "Decay or growth with a constant background"),
    ("expression", "Own formula", "Any expression in x"),
]


class FitDialog(QDialog):
    """Fits a model to the plot `target`; `fit()` is the result for the model."""

    def __init__(self, target, data, residuals_default: bool = False, parent=None):
        super().__init__(parent)
        self.target = target
        self.x = data(target.x)
        self.y = data(target.y)
        self.yerr = (
            data(target.yerr)
            if isinstance(target, ErrorbarPlot) and target.yerr is not None
            else None
        )
        self.result = None
        self.start: dict[str, QLineEdit] = {}
        self.fixed: dict[str, QCheckBox] = {}
        """Per parameter: held at its start value instead of fitted."""
        self.lower: dict[str, QLineEdit] = {}
        self.upper: dict[str, QLineEdit] = {}
        """Per parameter: the range a fitted value stays in; empty is open."""
        self._guessed: dict[str, float] = {}
        self.setWindowTitle(f"Fit {artist_name(target)}")

        self.models = QButtonGroup(self)
        self.models.idToggled.connect(lambda _, on: on and self._model_changed())
        self.degree = QSpinBox()
        self.degree.setRange(1, 9)
        self.degree.setValue(2)
        self.degree.valueChanged.connect(self._model_changed)
        self.expression = QLineEdit()
        self.expression.setPlaceholderText("e.g. a * exp(-x / tau) + c")
        self.expression.setFont(theme.mono_font(13))
        self.expression.editingFinished.connect(self._model_changed)
        self.formula = label("", "value")
        self.label = QLineEdit()
        self.label.setPlaceholderText("not in the legend")
        self.residuals = QCheckBox("Show the residuals in a panel below")
        self.residuals.setChecked(residuals_default)
        self.error = label("", "error")
        self._start_form = QFormLayout()
        self._result_grid = QGridLayout()

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Add fit")
        ok.setObjectName("primary")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self._layout()
        self.resize(820, 560)
        self.models.button(0).setChecked(True)

    # --- layout ---------------------------------------------------------------

    def _layout(self) -> None:
        weighting = (
            f"weighted by {self.target.yerr.column}"
            if self.yerr is not None
            else "unweighted: the plot has no y errors"
        )
        top = QVBoxLayout()
        top.setContentsMargins(24, 20, 24, 16)
        top.setSpacing(4)
        top.addWidget(label(f"Fit {artist_name(self.target)}", "dialogTitle"))
        top.addWidget(label(f"{len(self.x)} points · {weighting}", "caption"))

        choices = QVBoxLayout()
        choices.setSpacing(6)
        choices.addWidget(label("Model", "sectionHeading"))
        for i, (_, name, detail) in enumerate(MODELS):
            button = QPushButton(name)
            button.setToolTip(detail)
            button.setObjectName("modelChoice")
            button.setCheckable(True)
            self.models.addButton(button, i)
            choices.addWidget(button)
        choices.addStretch(1)
        left = QWidget()
        left.setObjectName("aside")
        left.setFixedWidth(270)
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(20, 16, 20, 16)
        left_box.addLayout(choices)

        self._details = QFormLayout()
        self._details.setHorizontalSpacing(12)
        self._details.addRow(_caption("Formula"), self.formula)
        self._details.addRow(_caption("Degree"), self.degree)
        self._details.addRow(_caption("Formula in x"), self.expression)
        self._start_form.setHorizontalSpacing(12)
        card = QFrame()
        card.setObjectName("card")
        self._result_grid.setContentsMargins(12, 10, 12, 10)
        self._result_grid.setHorizontalSpacing(16)
        card.setLayout(self._result_grid)
        extra = QFormLayout()
        extra.addRow(_caption("Legend label"), self.label)

        right = QVBoxLayout()
        right.setContentsMargins(24, 16, 24, 16)
        right.setSpacing(10)
        right.addLayout(self._details)
        right.addWidget(label("Start values, held parameters, bounds", "sectionTitle"))
        right.addLayout(self._start_form)
        guess = QPushButton("Guess again from the data")
        guess.setObjectName("link")
        guess.clicked.connect(self._guess_again)
        right.addWidget(guess, 0, Qt.AlignmentFlag.AlignLeft)
        right.addWidget(label("Result", "sectionTitle"))
        right.addWidget(card)
        right.addWidget(self.error)
        right.addLayout(extra)
        right.addWidget(self.residuals)
        right.addStretch(1)

        middle = QHBoxLayout()
        middle.setSpacing(0)
        middle.addWidget(left)
        middle.addLayout(right, 1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(24, 12, 24, 16)
        bottom.addStretch(1)
        bottom.addWidget(self.buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(_rule())
        layout.addLayout(middle, 1)
        layout.addWidget(_rule())
        layout.addLayout(bottom)

    # --- model ----------------------------------------------------------------

    @property
    def model_key(self) -> str:
        return MODELS[self.models.checkedId()][0]

    def choose(self, key: str) -> None:
        index = [k for k, _, _ in MODELS].index(key)
        self.models.button(index).setChecked(True)

    def model(self):
        """The chosen model; raises FitError for an unusable own formula."""
        key = self.model_key
        if key == "expression":
            text = self.expression.text().strip()
            if not text:
                raise FitError("type a formula in x, e.g. a * x + b")
            names = free_names(text)
            if not names:
                raise FitError("the formula has no parameter to fit")
            return ExpressionFit(expression=text, parameters=names)
        degree = self.degree.value() if key == "polynomial" else None
        return PredefinedFit(name=key, degree=degree)

    def _model_changed(self) -> None:
        key = self.model_key
        _show_row(self._details, self.degree, key == "polynomial")
        _show_row(self._details, self.expression, key == "expression")
        _show_row(self._details, self.formula, key != "expression")
        if not self.label.isModified():
            name = dict((k, n) for k, n, _ in MODELS)[key]
            self.label.setText(f"{name} fit" if key != "expression" else "Fit")
        try:
            model = self.model()
            names = parameter_names(model)
        except (FitError, ValueError) as exc:
            self._show_error(str(exc))
            self._fill_start([])
            return
        if key != "expression":
            self.formula.setText(source_of(model)[0])
        self._guessed = initial_guess(model, self.x, self.y)
        self._fill_start(names)
        self.refit()

    def _fill_start(self, names: list[str]) -> None:
        while self._start_form.rowCount():
            self._start_form.removeRow(0)
        self.start, self.fixed, self.lower, self.upper = {}, {}, {}, {}
        for name in names:
            line = QLineEdit(f"{self._guessed.get(name, 1.0):.6g}")
            line.setFont(theme.mono_font(13))
            line.editingFinished.connect(self.refit)
            held = QCheckBox("held")
            held.setToolTip("Keep this parameter at its start value; fit the rest.")
            held.toggled.connect(self.refit)
            lower, upper = _bound("−∞"), _bound("+∞")
            for bound in (lower, upper):
                bound.setToolTip("The fitted value stays within; empty is open.")
                bound.editingFinished.connect(self.refit)
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(line, 2)
            row.addWidget(held)
            row.addWidget(label("within", "caption"))
            row.addWidget(lower, 1)
            row.addWidget(label("to", "caption"))
            row.addWidget(upper, 1)
            self.start[name], self.fixed[name] = line, held
            self.lower[name], self.upper[name] = lower, upper
            self._start_form.addRow(_caption(GREEK.get(name, name)), row)

    def _guess_again(self) -> None:
        for name, line in self.start.items():
            line.setText(f"{self._guessed.get(name, 1.0):.6g}")
        self.refit()

    def held(self) -> list[str]:
        return [name for name, box in self.fixed.items() if box.isChecked()]

    def bounds(self) -> dict[str, tuple[float | None, float | None]]:
        """The typed bounds, for parameters that have one."""
        found = {}
        for name in self.start:
            ends = []
            for side, line in (
                ("lower", self.lower[name]),
                ("upper", self.upper[name]),
            ):
                text = line.text().strip()
                try:
                    ends.append(number(text) if text else None)
                except ValueError as exc:
                    raise FitError(f"the {side} bound of {name}: {exc}") from None
            if ends != [None, None]:
                found[name] = tuple(ends)
        return found

    def start_values(self) -> dict[str, float]:
        values = {}
        for name, line in self.start.items():
            try:
                values[name] = number(line.text())
            except ValueError as exc:
                raise FitError(f"the start value of {name}: {exc}") from None
        return values

    # --- fitting --------------------------------------------------------------

    def refit(self) -> None:
        """Fit with the current model and start values; show the outcome."""
        self.result = None
        try:
            model = self.model()
            self._guesses_within(self.bounds())
            result = run_fit(
                model,
                self.start_values(),
                self.x,
                self.y,
                self.yerr,
                fixed=self.held(),
                bounds=self.bounds(),
            )
        except (FitError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self.result = result
        self.error.setText("" if result.converged else "The fit did not converge.")
        self._show_result()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def _guesses_within(self, bounds) -> None:
        """Move start values the user did not type into their bounds; a typed
        one outside is the user's to change, and is refused."""
        for name, ends in bounds.items():
            line = self.start[name]
            if line.isModified():
                continue
            try:
                value = number(line.text())
            except ValueError:
                continue
            moved = within({name: value}, {name: ends})[name]
            if moved != value:
                line.setText(f"{moved:.6g}")

    def fit(self) -> FitCurve | None:
        """The FitCurve to add, with the start values it was fitted from."""
        if self.result is None:
            return None
        return FitCurve(
            target=self.target.id,
            model=self.model(),
            initial_values=self.start_values(),
            fixed=self.held(),
            parameter_bounds=self.bounds(),
            result=self.result,
            label=self.label.text().strip() or None,
        )

    def _show_error(self, message: str) -> None:
        self.result = None
        self.error.setText(message[:1].upper() + message[1:])
        _clear(self._result_grid)
        self._result_grid.addWidget(label("No result yet.", "hint"), 0, 0)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def _show_result(self) -> None:
        _clear(self._result_grid)
        result = self.result
        for row, (name, value) in enumerate(result.parameters.items()):
            error = result.uncertainties.get(name)
            self._result_grid.addWidget(label(GREEK.get(name, name), "value"), row, 0)
            shown = f"{value:.6g} (held)" if name in self.held() else None
            self._result_grid.addWidget(
                label(shown or with_error(value, error), "value"), row, 1
            )
        row = len(result.parameters)
        if result.reduced_chi_square is not None:
            self._result_grid.addWidget(label("χ²ᵣ", "value"), row, 0)
            chi = f"{result.reduced_chi_square:.2f} · {len(self.x)} points"
            self._result_grid.addWidget(label(chi, "value"), row, 1)
        self._result_grid.setColumnStretch(1, 1)


def _bound(placeholder: str) -> QLineEdit:
    line = QLineEdit()
    line.setPlaceholderText(placeholder)
    line.setFont(theme.mono_font(13))
    return line


def _caption(text: str):
    widget = label(text, "caption")
    widget.setWordWrap(False)
    return widget


def _show_row(form: QFormLayout, field: QWidget, visible: bool) -> None:
    form.setRowVisible(field, visible)


def _clear(grid: QGridLayout) -> None:
    while grid.count():
        widget = grid.takeAt(0).widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


def _rule() -> QFrame:
    line = QFrame()
    line.setObjectName("rule")
    line.setFixedHeight(1)
    return line
