/*
 * One-off generator: copies the curated GAME_SYSTEMS array out of the Mod:Side
 * source verbatim into a JSON data file. The array is plain data (no closures),
 * so it is evaluated with its two small constructor shims in scope.
 * Run with: node tools/extract_systems.cjs
 */
const fs = require("fs");
const path = require("path");

const REPO = process.env.CS_SOURCE_REPO || "/home/windows/project/RevivalSide";
const OUT = path.join(__dirname, "..", "src", "counterside_mcp", "data", "systems.json");

const viewer = fs.readFileSync(path.join(REPO, "server/assetViewer.js"), "utf8");
const start = viewer.indexOf("const GAME_SYSTEMS = [");
if (start < 0) throw new Error("GAME_SYSTEMS not found");
const end = viewer.indexOf("\n];", start);
if (end < 0) throw new Error("GAME_SYSTEMS terminator not found");
const literal = viewer.slice(start + "const GAME_SYSTEMS = ".length, end + 2);

// The array literal is built from these two helpers; reproduce them exactly so
// `eval` yields the same objects the Node server builds.
const system = (id, title, description, keywords, directories, prefixes, priorityTables, commonEdits) => ({
  id,
  title,
  description,
  keywords,
  directories,
  prefixes,
  priorityTables,
  commonEdits,
});
const edit = (label, query, location) => ({ label, query, location });

const GAME_SYSTEMS = eval(literal);

const ids = GAME_SYSTEMS.map((s) => s.id);
if (new Set(ids).size !== ids.length) throw new Error("duplicate system ids in GAME_SYSTEMS");

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(GAME_SYSTEMS, null, 2) + "\n");
console.log("wrote", GAME_SYSTEMS.length, "systems to", OUT);
console.log("ids:", ids.join(", "));
