// Runs the FPL Planner app's own projection model (model.ts, copied verbatim from the
// Lovable app's src/lib/model.ts) and prints per-player projections as JSON.
//
// Usage: node --experimental-strip-types appmodel/run.ts <input.json>
// input.json = { "bootstrap": <bootstrap-static>, "fixtures": <fixtures>, "horizon": 8 }
import { readFileSync } from "node:fs";
import { buildModel } from "./model.ts";

const input = JSON.parse(readFileSync(process.argv[2], "utf8"));
const horizon: number = input.horizon ?? 8;
const m = buildModel(input.bootstrap, input.fixtures);
const gws = m.horizonGws(horizon);

const players = input.bootstrap.elements.map((el: { id: number }) => {
  const p = m.project(el.id);
  const byGw: Record<string, { pts: number; xmins: number; p60: number; fixtures: number }> = {};
  for (const gw of gws) {
    const g = p.byGw.get(gw);
    const n = g?.fixtures.length ?? 0;
    // expMin is per match, so a double gameweek doubles the expected minutes and a blank has none.
    byGw[String(gw)] = { pts: g?.total ?? 0, xmins: (g?.expMin ?? 0) * n, p60: g?.p60 ?? 0, fixtures: n };
  }
  return { id: el.id, byGw };
});

process.stdout.write(JSON.stringify({ nextGw: m.nextGw, gws, players }));
