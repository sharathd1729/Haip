import { describe, expect, it } from "vitest";
import { appendIndex, describeDelay, insertNode, moveNode, relink, splitDelay } from "./flowOrder";

const chain = [{ id: "t", type: "trigger" }, { id: "a", type: "message" }, { id: "b", type: "delay" }, { id: "z", type: "end" }];
const edges = relink(chain, [{ id: "keep", from: "t", to: "a", label: "true" }]);

describe("flow order", () => {
  it("links each step to the next and keeps existing labels", () => {
    expect(edges.map(e => `${e.from}>${e.to}`)).toEqual(["t>a", "a>b", "b>z"]);
    expect(edges[0]).toEqual({ id: "keep", from: "t", to: "a", label: "true" });
  });
  it("moves a step but never above the trigger", () => {
    const moved = moveNode(chain, edges, "b", 0);
    expect(moved.nodes.map(n => n.id)).toEqual(["t", "b", "a", "z"]);
    expect(moved.edges.map(e => `${e.from}>${e.to}`)).toEqual(["t>b", "b>a", "a>z"]);
    expect(moveNode(chain, edges, "t", 3).nodes).toBe(chain);
  });
  it("inserts before a trailing End and an End step never points onward", () => {
    const ins = insertNode(chain, edges, { id: "n", type: "template" }, appendIndex(chain));
    expect(ins.nodes.map(n => n.id)).toEqual(["t", "a", "b", "n", "z"]);
    const after = moveNode(chain, edges, "z", 1);
    expect(after.edges.find(e => e.from === "z")).toBeUndefined();
  });
  it("describes and splits waits", () => {
    expect(describeDelay(1440)).toBe("Wait 1 day");
    expect(describeDelay(4320)).toBe("Wait 3 days");
    expect(describeDelay(90)).toBe("Wait 90 min");
    expect(splitDelay(120)).toEqual({ amount: 2, unit: "hours" });
  });
});
