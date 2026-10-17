import { useEffect, useRef, useState } from "react";
import cytoscape from "cytoscape";
import type { Core, StylesheetJson } from "cytoscape";
import dagre from "cytoscape-dagre";
import { Maximize2, Minus, Plus } from "lucide-react";
import type { Explanation, GraphData, ScenarioResult } from "../api";
import { useReducedMotion } from "../useReducedMotion";

cytoscape.use(dagre);

const graphStyle: StylesheetJson = [
  {
    selector: "node",
    style: {
      shape: "round-rectangle",
      width: 170,
      height: 44,
      label: "data(label)",
      color: "#dddeda",
      "font-family": "DM Sans",
      "font-size": 14,
      "font-weight": 500,
      "text-valign": "center",
      "text-halign": "center",
      "background-color": "#242c28",
      "border-color": "#58665c",
      "border-width": 1.2,
      "text-wrap": "wrap",
      "text-max-width": "128px",
      "overlay-opacity": 0,
    },
  },
  {
    selector: "node.root",
    style: {
      shape: "round-rectangle",
      "background-color": "#33392e",
      "border-color": "#b0b99a",
      "border-width": 1.6,
    },
  },
  {
    selector: "node.safe",
    style: {
      "background-color": "#23372e",
      "border-color": "#6eac8a",
      color: "#c8e4cf",
    },
  },
  {
    selector: "node.takeover",
    style: {
      "background-color": "#442b29",
      "border-color": "#dc8a7b",
      color: "#ffcec4",
    },
  },
  {
    selector: "node.lockout",
    style: {
      "background-color": "#423921",
      "border-color": "#d7b669",
      color: "#f2dfad",
    },
  },
  {
    selector: "node.unknown",
    style: {
      "background-opacity": 0,
      "border-style": "dashed",
      "border-width": 2,
      "border-color": "#b3b3ab",
      color: "#c6c7bf",
    },
  },
  { selector: "node.unrevealed", style: { opacity: 0.22 } },
  {
    selector: "edge",
    style: {
      width: 1.2,
      "line-color": "#526258",
      "target-arrow-color": "#526258",
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.7,
      "curve-style": "bezier",
      "control-point-step-size": 28,
      opacity: 0.55,
      label: "",
      "font-size": 9,
      color: "#c5c8bc",
      "text-background-color": "#1b221e",
      "text-background-opacity": 1,
      "text-background-padding": "3px",
      "text-rotation": "autorotate",
    },
  },
  {
    selector: "edge.unconfirmed",
    style: {
      "line-style": "dashed",
      "line-color": "#80877e",
      "target-arrow-color": "#80877e",
    },
  },
  {
    selector: "edge.takeover",
    style: {
      "line-color": "#bc776c",
      "target-arrow-color": "#bc776c",
      opacity: 0.78,
      width: 1.6,
    },
  },
  {
    selector: "edge.lockout",
    style: {
      "line-color": "#ba9c57",
      "target-arrow-color": "#ba9c57",
      opacity: 0.78,
      width: 1.6,
    },
  },
  { selector: "edge.unrevealed", style: { opacity: 0.1 } },
  { selector: ".dimmed", style: { opacity: 0.13 } },
  {
    selector: "node.highlighted",
    style: { "border-width": 3, "border-color": "#ece9ce", opacity: 1 },
  },
  {
    selector: "edge.highlighted",
    style: {
      "line-color": "#dcd7b1",
      "target-arrow-color": "#dcd7b1",
      width: 2.4,
      opacity: 1,
      label: "data(label)",
    },
  },
  {
    selector: "node:selected",
    style: { "border-width": 3, "border-color": "#f0eccb" },
  },
];

export function AccountGraph({
  graph,
  results,
  depth,
  selected,
  explanation,
  onSelect,
  fixedAccountIds,
}: {
  graph: GraphData;
  results: ScenarioResult[];
  depth: "direct" | "full";
  selected: string | null;
  explanation: Explanation | null;
  onSelect: (id: string) => void;
  fixedAccountIds: string[];
}) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<Core | null>(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const reduced = useReducedMotion();
  const [round, setRound] = useState(1);
  const maxRound = Math.max(1, ...results.map((result) => result.rounds));
  const scenarioKey = results.map((result) => result.id).join(":");
  const reachedIds = results.flatMap((result) =>
    result.affected_accounts.map((item) => item.node_id),
  );
  const rootIds = results.flatMap((result) => result.root_ids);
  const relevantIds = new Set([
    ...reachedIds,
    ...rootIds,
    ...fixedAccountIds,
    ...results.flatMap((result) => result.unknown_accounts),
  ]);
  for (const edge of graph.edges)
    if (rootIds.includes(edge.source) || reachedIds.includes(edge.source))
      relevantIds.add(edge.target);
  const fixedClosure = [...fixedAccountIds];
  const visited = new Set(fixedClosure);
  const fixedRounds = new Map(fixedAccountIds.map((id) => [id, 1]));
  for (let index = 0; index < fixedClosure.length; index++) {
    for (const edge of graph.edges.filter(
      (item) => item.source === fixedClosure[index],
    )) {
      relevantIds.add(edge.target);
      if (!visited.has(edge.target)) {
        visited.add(edge.target);
        fixedRounds.set(edge.target, (fixedRounds.get(edge.source) ?? 0) + 1);
        fixedClosure.push(edge.target);
      }
    }
  }
  if (selected) relevantIds.add(selected);
  for (const edge of graph.edges)
    if (
      relevantIds.has(edge.target) &&
      graph.nodes.some(
        (node) => node.id === edge.source && node.node_type === "Root",
      )
    )
      relevantIds.add(edge.source);
  for (const node of graph.nodes)
    if (node.root?.kind === "phone" || node.root?.kind === "device")
      relevantIds.add(node.id);
  const membershipKey = [...relevantIds].sort().join(":");

  useEffect(() => {
    setRound(depth === "direct" ? 1 : reduced ? maxRound : 1);
    if (depth !== "full" || reduced) return;
    const timers = Array.from({ length: maxRound - 1 }, (_, i) =>
      window.setTimeout(() => setRound(i + 2), (i + 1) * 650),
    );
    return () => timers.forEach(window.clearTimeout);
  }, [depth, maxRound, scenarioKey, reduced]);

  useEffect(() => {
    if (!container.current) return;
    const cy = cytoscape({
      container: container.current,
      elements: [
        ...graph.nodes
          .filter((node) => relevantIds.has(node.id))
          .map((node) => ({
            data: { id: node.id, label: node.label },
            classes: node.node_type === "Root" ? "root" : "",
          })),
        ...graph.edges
          .filter(
            (edge) =>
              relevantIds.has(edge.source) && relevantIds.has(edge.target),
          )
          .map((edge) => ({
            data: edge,
            classes: edge.confirmed ? "" : "unconfirmed",
          })),
      ],
      style: graphStyle,
      minZoom: 0.3,
      maxZoom: 2.5,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
    });
    const layout: dagre.DagreLayoutOptions = {
      name: "dagre",
      rankDir: "LR",
      nodeSep: 22,
      rankSep: 95,
      edgeSep: 8,
      ranker: "longest-path",
      fit: true,
      padding: 38,
      animate: false,
    };
    cy.layout(layout).run();
    const reached = new Map([
      ...fixedRounds,
      ...results.flatMap((result) =>
        result.affected_accounts.map(
          (item) => [item.node_id, item.round] as const,
        ),
      ),
    ]);
    const columns = new Map<number, string[]>();
    for (const node of graph.nodes.filter((item) => relevantIds.has(item.id))) {
      const incoming = graph.edges.filter((edge) => edge.target === node.id);
      const inheritedRound =
        Math.max(0, ...incoming.map((edge) => reached.get(edge.source) ?? 0)) +
        1;
      const column =
        reached.get(node.id) ??
        (node.node_type === "Root" || node.account?.modelled === false
          ? 0
          : inheritedRound);
      const ids = columns.get(column) ?? [];
      ids.push(node.id);
      columns.set(column, ids);
    }
    const longest = Math.max(...[...columns.values()].map((ids) => ids.length));
    for (const [column, ids] of columns) {
      ids.sort(
        (a, b) =>
          cy.getElementById(a).position("y") -
          cy.getElementById(b).position("y"),
      );
      ids.forEach((id, index) =>
        cy.getElementById(id).position({
          x: column * 300,
          y: (index + (longest - ids.length) / 2) * 54,
        }),
      );
    }
    cy.fit(undefined, 32);
    cy.on("tap", "node", (event) => {
      if (
        graph.nodes.some(
          (node) =>
            node.id === event.target.id() && node.node_type === "Account",
        )
      )
        selectRef.current(event.target.id());
    });
    const resize = new ResizeObserver(() => {
      cy.resize();
      cy.fit(undefined, 38);
    });
    resize.observe(container.current);
    instance.current = cy;
    return () => {
      resize.disconnect();
      cy.destroy();
      instance.current = null;
    };
  }, [graph, scenarioKey, membershipKey]);

  useEffect(() => {
    const cy = instance.current;
    if (!cy) return;
    const reached = new Map(
      results.flatMap((result) =>
        result.affected_accounts.map(
          (item) => [item.node_id, { ...item, kind: result.kind }] as const,
        ),
      ),
    );
    const direct = new Set(results.flatMap((result) => result.direct_accounts));
    const seeds = new Set(results.flatMap((result) => result.root_ids));
    const unknown = new Set(
      results.flatMap((result) => result.unknown_accounts),
    );
    const visible = (id: string) => {
      const item = reached.get(id);
      return (
        !item || (depth === "direct" ? direct.has(id) : item.round <= round)
      );
    };
    cy.batch(() => {
      cy.elements().removeClass(
        "safe takeover lockout unknown unrevealed dimmed highlighted",
      );
      for (const node of graph.nodes) {
        const element = cy.getElementById(node.id);
        const item = reached.get(node.id);
        if (node.account?.modelled === false || unknown.has(node.id))
          element.addClass("unknown");
        else if (item && visible(node.id)) element.addClass(item.kind);
        else if (seeds.has(node.id))
          element.addClass(
            results.find((r) => r.root_ids.includes(node.id))?.kind || "safe",
          );
        else if (
          !item &&
          (node.node_type === "Account" || visited.has(node.id))
        )
          element.addClass("safe");
        if (item && !visible(node.id)) element.addClass("unrevealed");
      }
      for (const edge of graph.edges) {
        const element = cy.getElementById(edge.id);
        const target = reached.get(edge.target);
        if (!visible(edge.source) || !visible(edge.target))
          element.addClass("unrevealed");
        else if (target && (reached.has(edge.source) || seeds.has(edge.source)))
          element.addClass(target.kind);
      }
      if (selected) {
        cy.elements().addClass("dimmed");
        cy.getElementById(selected)
          .removeClass("dimmed unrevealed")
          .addClass("highlighted");
        for (const step of explanation?.steps ?? []) {
          cy.getElementById(step.from_id)
            .removeClass("dimmed unrevealed")
            .addClass("highlighted");
          cy.getElementById(step.to_id)
            .removeClass("dimmed unrevealed")
            .addClass("highlighted");
          for (const edge of graph.edges.filter(
            (e) => e.source === step.from_id && e.target === step.to_id,
          ))
            cy.getElementById(edge.id)
              .removeClass("dimmed unrevealed")
              .addClass("highlighted");
        }
        if (!explanation?.steps.length)
          cy.getElementById(selected).neighborhood().removeClass("dimmed");
      }
    });
  }, [graph, results, depth, round, selected, explanation, fixedAccountIds]);

  return (
    <div className="graph-visual">
      <div
        className="graph-canvas"
        ref={container}
        role="img"
        aria-label="Account dependency graph. Use the account selector below for keyboard access."
      />
      <div className="graph-corner">
        <span className="mono">
          {depth === "direct" ? "DEPTH 1" : `ROUND ${round} / ${maxRound}`}
        </span>
        <span>
          {depth === "direct"
            ? "The connections you can see."
            : round < maxRound
              ? "Following the next connection…"
              : "The complete chain, under modelled methods."}
        </span>
      </div>
      <div className="graph-tools">
        <button
          className="icon-button"
          aria-label="Zoom in"
          onClick={() => instance.current?.zoom(instance.current.zoom() * 1.2)}
        >
          <Plus size={16} />
        </button>
        <button
          className="icon-button"
          aria-label="Zoom out"
          onClick={() => instance.current?.zoom(instance.current.zoom() / 1.2)}
        >
          <Minus size={16} />
        </button>
        <button
          className="icon-button"
          aria-label="Fit graph"
          onClick={() => instance.current?.fit(undefined, 38)}
        >
          <Maximize2 size={15} />
        </button>
      </div>
    </div>
  );
}
