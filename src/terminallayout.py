from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Container, Horizontal, Vertical, Grid

# Implement worskstation grid layout


class FinanceTerminal(Widget):
    CSS_PATH = "styles.tcss"

    def __init__(self, *panels: Widget, **kwargs) -> None:
        super().__init__(**kwargs)
        self.panels = panels

    def compose(self) -> ComposeResult:
        # Apply css grid layout to the terminal
        with Grid(id="terminal-grid"):
            for panel in self.panels:
                yield panel