import math
import textwrap
import graphviz
from schemas import ProcessModel

# A column taller than this no longer fits a page at a readable size, so longer processes are laid out
# in several columns that are read top to bottom, left to right.
MAX_PER_COLUMN = 10
MAX_COLUMNS = 4


def columns_for(n_steps: int) -> int:
    return min(MAX_COLUMNS, max(1, math.ceil(n_steps / MAX_PER_COLUMN)))


def build_flowchart(model: ProcessModel, output_path: str = "cache/flowchart", start_label: str = "Start",
                    end_label: str = "End") -> str:
    dot = graphviz.Digraph(format="png")
    dot.attr(rankdir="TB", ranksep="0.25", nodesep="0.5", dpi="150", newrank="true")
    dot.attr("node", shape="box", style="rounded,filled", fillcolor="#D9E2F3", fontname="Helvetica", fontsize="10",
             width="2.2")
    terminal = {"shape": "ellipse", "fillcolor": "#2F5496", "fontcolor": "white", "width": "1"}

    steps = model.as_is
    per_column = math.ceil(len(steps) / columns_for(len(steps))) if steps else 1
    columns = [steps[i:i + per_column] for i in range(0, len(steps), per_column)]

    connector = {"shape": "circle", "style": "filled", "fillcolor": "#2F5496", "fontcolor": "white", "width": "0.35",
                 "fixedsize": "true"}

    dot.node("start", start_label, **terminal)
    tops = ["start"]  # first node of each column, kept on one row
    prev = "start"
    for c, column in enumerate(columns):
        if c > 0:
            # Standard off-page connectors: the circle at the bottom of a column continues at the top of the next.
            letter = chr(ord("A") + c - 1)
            dot.node(f"to_{c}", letter, **connector)
            dot.edge(prev, f"to_{c}")
            dot.node(f"from_{c}", letter, **connector)
            tops.append(f"from_{c}")
            prev = f"from_{c}"
        for step in column:
            node = f"step_{step.number}"
            label = "\n".join(textwrap.wrap(f"{step.number}. {step.short_label}", 26))
            if step.decision:
                dot.node(node, label, shape="diamond", style="filled", fillcolor="#FCE4D6", width="2.6", height="1")
            else:
                dot.node(node, label)
            dot.edge(prev, node)
            prev = node
    dot.node("end", end_label, **terminal)
    dot.edge(prev, "end")

    with dot.subgraph() as same:
        same.attr(rank="same")
        for node in tops:
            same.node(node)
    return dot.render(filename=output_path, cleanup=True)
