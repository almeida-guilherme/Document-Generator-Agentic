import graphviz
from schemas import PDD


def build_flowchart(pdd: PDD, output_path: str = "cache/flowchart", max_nodes: int = 12) -> str:
    dot = graphviz.Digraph(format="png")
    dot.attr(rankdir="TB")
    dot.attr("node", shape="box", style="rounded,filled", fillcolor="#D9E2F3", fontname="Helvetica", fontsize="10")

    dot.node("start", "Start", shape="ellipse", fillcolor="#2F5496", fontcolor="white")

    steps_to_render = pdd.as_is
    if len(steps_to_render) > max_nodes:
        # placeholder simples: trunca com um nó indicando "..."
        steps_to_render = pdd.as_is[:max_nodes]

    prev_node_id = "start"
    for step in steps_to_render:
        node_id = f"step_{step.number}"
        label = f"{step.number}. {step.short_label}"
        dot.node(node_id, label)
        dot.edge(prev_node_id, node_id)
        prev_node_id = node_id

    if len(pdd.as_is) > max_nodes:
        dot.node("more", f"... +{len(pdd.as_is) - max_nodes} more steps", shape="box", style="dashed", fillcolor="white")
        dot.edge(prev_node_id, "more")
        prev_node_id = "more"

    dot.node("end", "End", shape="ellipse", fillcolor="#2F5496", fontcolor="white")
    dot.edge(prev_node_id, "end")

    return dot.render(filename=output_path, cleanup=True)