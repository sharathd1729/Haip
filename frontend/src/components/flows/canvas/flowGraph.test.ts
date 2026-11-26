import { describe, expect, it } from "vitest";
import { GAP_Y, autoLayout, fromStored, previewPath, pruneEdges, toStored, validateFlow } from "./flowGraph";
import { BLOCKS, outputsOf, summarize, type StoredEdge, type StoredNode } from "./flowModel";
import { FLOW_TEMPLATES } from "./flowTemplates";

// An old linear flow as the step list saved it: no position, x/y = 0, trigger + action keys in `content`,
// condition edge labelled "true".
const legacy: StoredNode[] = [
  { id: "t", type: "trigger", label: "Contact opts in", content: "opt_in", x: 0, y: 0 },
  { id: "m", type: "message", label: "Welcome", content: "Hi there\nsecond line", x: 0, y: 0 },
  { id: "c", type: "condition", label: "Replied?", condition: "replied", x: 0, y: 0 },
  { id: "a", type: "action", label: "VIP", content: "tag_vip", x: 0, y: 0 },
  { id: "z", type: "end", label: "End", x: 0, y: 0 },
];
const legacyEdges: StoredEdge[] = [
  { id: "e1", from: "t", to: "m", label: null },
  { id: "e2", from: "m", to: "c", label: null },
  { id: "e3", from: "c", to: "a", label: "true" },
  { id: "e4", from: "a", to: "z", label: null },
];

describe("autoLayout", () => {
  it("lays position-less nodes out top to bottom from the trigger", () => {
    const out = autoLayout(legacy, legacyEdges);
    // the condition (2 outputs) gets one extra line of room below it
    expect(out.map(n => n.position!.y)).toEqual([0, GAP_Y, 2 * GAP_Y, 3 * GAP_Y + 26, 4 * GAP_Y + 26]);
    expect(out.every(n => n.position!.x === 0)).toBe(true);
  });
  it("spreads siblings sideways and keeps existing positions", () => {
    const nodes: StoredNode[] = [
      { id: "t", type: "trigger", position: { x: 50, y: 7 } },
      { id: "a", type: "message" }, { id: "b", type: "message" }, { id: "orphan", type: "end" },
    ];
    const out = autoLayout(nodes, [{ id: "1", from: "t", to: "a", label: null }, { id: "2", from: "t", to: "b", label: null }]);
    expect(out[0].position).toEqual({ x: 50, y: 7 });
    expect(out[1].position!.y).toBe(GAP_Y);
    expect(out[1].position!.x).toBe(-out[2].position!.x);
    expect(out[3].position!.y).toBe(2 * GAP_Y);
  });
});

describe("stored <-> canvas", () => {
  it("opens an old flow and saves it in the new shape", () => {
    const canvas = fromStored(legacy, legacyEdges);
    expect(canvas.edges.find(e => e.id === "e3")!.sourceHandle).toBe("yes");
    expect(canvas.nodes.find(n => n.id === "t")!.deletable).toBe(false);
    const back = toStored(canvas.nodes, canvas.edges);
    expect(back.nodes[0]).toEqual({ id: "t", type: "trigger", label: "Contact opts in", content: "opt_in", trigger: "opt_in", position: { x: 0, y: 0 } });
    expect(back.nodes[3]).toMatchObject({ action: "tag_vip", content: "tag_vip" });
    expect(back.nodes.some(n => "x" in n)).toBe(false);
    expect(back.edges.map(e => e.label)).toEqual([null, null, "yes", null]);
  });
  it("keeps btn:/row:/other labels on branching edges", () => {
    const nodes: StoredNode[] = [
      { id: "t", type: "trigger", trigger: "keyword", keywords: ["menu"], position: { x: 0, y: 0 } },
      { id: "b", type: "buttons", content: "Pick", buttons: [{ id: "v", title: "Villas" }, { id: "w", title: "Weddings" }], position: { x: 0, y: 100 } },
      { id: "l", type: "list", content: "Pick", button_label: "Rooms", rows: [{ id: "r1", title: "Pool villa" }], position: { x: 0, y: 200 } },
      { id: "m", type: "message", content: "x", position: { x: 0, y: 300 } },
    ];
    const edges: StoredEdge[] = [
      { id: "1", from: "t", to: "b", label: null },
      { id: "2", from: "b", to: "l", label: "btn:w" },
      { id: "3", from: "b", to: "m", label: "other" },
      { id: "4", from: "l", to: "m", label: "row:r1" },
    ];
    const canvas = fromStored(nodes, edges);
    expect(toStored(canvas.nodes, canvas.edges).edges).toEqual(edges);
    expect(outputsOf(nodes[1]).map(o => o.id)).toEqual(["btn:v", "btn:w", "other"]);
  });
  it("drops edges of a removed button and duplicate edges from one handle", () => {
    const canvas = fromStored(
      [{ id: "b", type: "buttons", buttons: [{ id: "v", title: "V" }], position: { x: 0, y: 0 } }, { id: "m", type: "message", position: { x: 0, y: 1 } }, { id: "n", type: "message", position: { x: 0, y: 2 } }],
      [{ id: "1", from: "b", to: "m", label: "btn:gone" }, { id: "2", from: "b", to: "m", label: "btn:v" }, { id: "3", from: "b", to: "n", label: "btn:v" }],
    );
    expect(canvas.edges.map(e => e.id)).toEqual(["2"]);
    expect(pruneEdges(canvas.nodes.filter(n => n.id !== "m"), canvas.edges)).toEqual([]);
  });
});

describe("validateFlow", () => {
  const start: StoredNode = { id: "t", type: "trigger", trigger: "keyword", keywords: ["hi"] };
  it("accepts every starter template once its files and templates are filled in", () => {
    for (const t of FLOW_TEMPLATES) {
      const { nodes, edges } = t.build();
      const filled = nodes.map(n => (n.type === "media" ? { ...n, file_key: "ten/wa_flows/x.pdf" } : n.type === "template" ? { ...n, template_id: "tp" } : n));
      expect(validateFlow(filled, edges), t.key).toEqual([]);
    }
  });
  it("mirrors the server's rules", () => {
    const msgs = (nodes: StoredNode[], edges: StoredEdge[] = []) => validateFlow(nodes, edges).map(p => p.message);
    expect(msgs([])).toContain("The flow needs a start block.");
    expect(msgs([start, { ...start, id: "t2" }])).toContain("A flow can have only one start block.");
    expect(msgs([{ ...start, keywords: [" "] }])).toContain("Add at least one keyword.");
    expect(msgs([start, { id: "t", type: "end" }])).toContain("Two blocks share the id t.");
    expect(msgs([start, { id: "b", type: "buttons", content: "x", buttons: [{ id: "1", title: "a".repeat(21) }] }])).toEqual([`"${"a".repeat(21)}" is longer than 20 characters.`]);
    expect(msgs([start, { id: "b", type: "buttons", content: "x", buttons: ["1", "2", "3", "4"].map(id => ({ id, title: id })) }])).toContain("Use 1 to 3 buttons.");
    expect(msgs([start, { id: "l", type: "list", content: "x", button_label: "Go", rows: [{ id: "r", title: "a".repeat(25), description: "d".repeat(73) }] }]))
      .toEqual([`"${"a".repeat(25)}" is longer than 24 characters.`, "A row description is longer than 72 characters."]);
    expect(msgs([start, { id: "u", type: "cta_url", content: "x", button_label: "Open", url: "http://example.com" }])).toEqual(["The link must start with https://"]);
    expect(msgs([start, { id: "h", type: "http", url: "https://example.com/hook" }])).toEqual([]);
    expect(msgs([start, { id: "p", type: "media", media_kind: "image" }])).toEqual(["Upload a file for each media block."]);
    expect(msgs([start, { id: "b", type: "buttons", content: "x", buttons: [{ id: "1", title: "Yes" }, { id: "2", title: "yes " }] }])).toEqual(["Two options have the same title."]);
    expect(msgs([start, { id: "q", type: "question", content: "x", save_as: "custom:" }])).toEqual(["Choose where to save the answer."]);
    expect(msgs([start], [{ id: "e", from: "t", to: "ghost", label: null }])).toEqual(["A connection points at a block that no longer exists."]);
    expect(msgs([start, { id: "g", type: "action", action: "add_label", content: "add_label", tag: "" }])).toEqual(["Write the label to add."]);
  });
});

describe("preview and summaries", () => {
  it("walks the first path through buttons", () => {
    const { nodes, edges } = FLOW_TEMPLATES.find(t => t.key === "menu")!.build();
    const path = previewPath(nodes, edges).map(s => (s.data.type === "trigger" ? "trigger" : s.data.content));
    expect(path).toEqual(["trigger", "Hi {first_name}, what are you planning?", "Great, here is what we offer for villas."]);
  });
  it("stops on a loop", () => {
    const loop: StoredEdge[] = [{ id: "1", from: "t", to: "m", label: null }, { id: "2", from: "m", to: "t", label: null }];
    expect(previewPath([{ id: "t", type: "trigger" }, { id: "m", type: "message" }], loop)).toHaveLength(2);
  });
  it("summarises a block in one short line", () => {
    expect(summarize(legacy[1])).toBe("Hi there");
    expect(summarize({ type: "media", filename: "brochure.pdf" })).toBe("brochure.pdf");
    expect(summarize({ type: "buttons", buttons: [{ id: "a", title: "Villas" }, { id: "b", title: "Weddings" }] })).toBe("Villas / Weddings");
    expect(summarize({ type: "trigger", trigger: "keyword", keywords: ["hi", "hey"] })).toBe("Keyword: hi, hey");
    expect(new Set(BLOCKS.map(b => b.key)).size).toBe(BLOCKS.length);
  });
});
